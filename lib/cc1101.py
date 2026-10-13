"""CC1101 sub-GHz radio driver (register level) for the Pi's SPI bus.

* `CC1101` — real radio through `spidev` (Pi 3/4/5, SPI0/SPI1).
* `MockSPI` — an in-memory CC1101 that answers register reads/writes like a
  real chip so the entire stack runs (and is tested) without hardware.

Everything the Flipper does with its STM32+DMA we do with spidev + GPIO waves:
the presets put the chip into async serial data mode and GDO0 then carries the
raw modulated bitstream.

Wiring (see README): VCC->3.3V, GND, MOSI->GPIO10, MISO->GPIO9,
SCK->GPIO11, CSN->GPIO8 (SPI0 CE0), GDO0->GPIO27.

Output power
------------
`set_power_dbm()` writes the PATABLE. Approximate CC1101 values for the
315/433 MHz bands (datasheet output-power tables; each step ~2-3 dB):

    dBm    PATABLE value
    +12    0xC0   (maximum)
    +10    0xB0
     +7    0x98
     +5    0x88
      0    0x70
     -5    0x58
    -10    0x44
    -15    0x34
    -20    0x24
    -30    0x14

OOK uses index 1 (index 0 is the '0' = off level), FSK/MSK/GFSK use index 0.
"""

from __future__ import annotations

import time

from .presets import Preset, preset_by_name
from .util import frequency_to_registers

# CC1101 strobes
SRES = 0x30  # reset chip
SCAL = 0x33  # calibrate
SRX = 0x34   # enter RX
STX = 0x35   # enter TX
SIDLE = 0x36  # idle
SPWD = 0x39  # power down

# status registers
REG_PARTNUM = 0x30
REG_VERSION = 0x31
REG_RSSI = 0x32

# PATABLE (0x3E) burst access header
_PATABLE_HDR = 0x3E | 0x40

# approximate dBm -> PATABLE value (315/433 MHz, see module docstring)
_POWER_TABLE = (
    (12, 0xC0), (10, 0xB0), (7, 0x98), (5, 0x88), (0, 0x70),
    (-5, 0x58), (-10, 0x44), (-15, 0x34), (-20, 0x24), (-30, 0x14),
)

GDO0_RX_ASYNC = 0x0D  # IOCFG0: GDO0 = async serial data OUT (receive)
GDO0_TX_ASYNC = 0x2D  # IOCFG0: GDO0 = async serial data IN (transmit)


class MockSPI:
    """In-memory CC1101 for demo mode and the test suite."""

    def __init__(self):
        # default power-up-ish register file; PARTNUM/VERSION identify a CC1101
        self.regs = {REG_PARTNUM: 0x00, REG_VERSION: 0x14, REG_RSSI: 0x3F}
        self.patable = [0] * 8
        self.strobes = []          # log of strobe codes (tests)
        self.writes = []           # log of (addr, value) writes (tests)

    # -- spidev-like interface ------------------------------------------
    def xfer2(self, data):
        return self.xfer(list(data))

    def xfer(self, data):
        data = list(data)
        if not data:
            return []
        out = [0x0F]  # status byte: state=IDLE, FIFOs empty
        head = data[0] & 0xFF
        if head & 0x80:  # read
            addr = head & 0x3F
            for _ in data[1:]:
                out.append(self.regs.get(addr, 0))
                addr = (addr + 1) & 0x3F
        else:  # write / strobe / PATABLE
            if head == _PATABLE_HDR:
                for i, val in enumerate(data[1:9]):
                    self.patable[i] = val & 0xFF
            elif 0x30 <= head <= 0x3D and not (head & 0x40):
                self.strobes.append(head)  # strobe command
            else:
                addr = head & 0x3F
                for val in data[1:]:
                    if addr <= 0x2E:
                        self.regs[addr] = val & 0xFF
                        self.writes.append((addr, val & 0xFF))
                    addr = (addr + 1) & 0x3F
        return out

    def close(self):
        pass


class CC1101:
    """Register-level CC1101 driver over spidev (or a MockSPI)."""

    def __init__(self, spi_bus: int = 0, spi_cs: int = 0, spi=None):
        self.spi_bus = spi_bus
        self.spi_cs = spi_cs
        if spi is None:
            spi = self._open_spidev(spi_bus, spi_cs)
        self.spi = spi
        self.frequency = 433_920_000
        self.preset = None
        self._closed = False

    # -- construction helpers --------------------------------------------
    @staticmethod
    def _open_spidev(bus: int, cs: int):
        import spidev  # lazy: absent on dev PCs -> caller falls back to MockSPI
        spi = spidev.SpiDev()
        spi.open(bus, cs)
        try:
            spi.max_speed_hz = 1_000_000  # conservative; CC1101 tolerates 10M
            spi.mode = 0
            spi.bits_per_word = 8
        except Exception:  # pragma: no cover
            pass
        return spi

    # -- low level --------------------------------------------------------
    def _xfer(self, data):
        return self.spi.xfer2(list(data))

    def _write_reg(self, addr: int, val: int):
        self._xfer([addr & 0x3F, val & 0xFF])

    def _read_reg(self, addr: int) -> int:
        return self._xfer([0x80 | (addr & 0x3F), 0x00])[1]

    def _strobe(self, code: int):
        self._xfer([code & 0xFF])

    # -- chip identity ------------------------------------------------------
    def get_partnum(self) -> int:
        return self._read_reg(REG_PARTNUM)

    def get_version(self) -> int:
        return self._read_reg(REG_VERSION)

    def check_alive(self) -> bool:
        """True when a real CC1101 answers on the bus (PARTNUM 0x00)."""
        try:
            part = self.get_partnum()
            version = self.get_version()
            return part == 0x00 and version not in (0x00, 0xFF)
        except Exception:
            return False

    # -- configuration -----------------------------------------------------
    def load_preset(self, preset):
        """Write all preset registers + PATABLE (frequency regs excluded)."""
        self.idle()
        if isinstance(preset, str):
            preset = preset_by_name(preset)
        for addr in sorted(preset.registers):
            if addr in (0x0D, 0x0E, 0x0F):  # FREQ2/1/0 set by set_frequency()
                continue
            self._write_reg(addr, preset.registers[addr])
        self._write_patable(preset.patable)
        self.preset = preset

    def _write_patable(self, patable):
        vals = [int(v) & 0xFF for v in list(patable)[:8]]
        while len(vals) < 8:
            vals.append(0x00)
        self._xfer([_PATABLE_HDR] + vals)

    def set_frequency(self, freq_hz: int):
        f2, f1, f0 = frequency_to_registers(freq_hz)
        self._write_reg(0x0D, f2)
        self._write_reg(0x0E, f1)
        self._write_reg(0x0F, f0)
        self.frequency = int(freq_hz)

    def set_power_dbm(self, dbm: int):
        """Set TX power (approximate; see the table in the module docstring)."""
        dbm = int(dbm)
        best = min(_POWER_TABLE, key=lambda kv: abs(kv[0] - dbm))
        value = best[1]
        ook = self.preset is not None and self.preset.modulation == "ASK/OOK"
        if ook:
            # index 0 is the off-level, index 1 radiates
            self._write_patable((0x00, value, 0, 0, 0, 0, 0, 0))
        else:
            self._write_patable((value,) * 8)

    # -- radio state --------------------------------------------------------
    def start_rx(self):
        """GDO0 outputs demodulated data; chip to RX (auto-calibrates)."""
        self._write_reg(0x02, GDO0_RX_ASYNC)
        self._strobe(SCAL)
        self._strobe(SRX)

    def start_tx(self):
        """GDO0 becomes the modulated data INPUT; chip to TX."""
        self._write_reg(0x02, GDO0_TX_ASYNC)
        self._strobe(SCAL)
        self._strobe(STX)

    def idle(self):
        self._strobe(SIDLE)

    def power_down(self):
        self._strobe(SPWD)

    def get_rssi_dbm(self) -> float:
        """RSSI in dBm (0.5 dB steps, -74 dBm offset — CC1101 formula)."""
        raw = self._read_reg(REG_RSSI)
        return raw / 2.0 - 74.0

    def reset(self):
        self._strobe(SRES)
        time.sleep(0.002)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.idle()
        except Exception:
            pass
        try:
            self.spi.close()
        except Exception:
            pass
        self.spi = None
