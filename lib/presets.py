"""Firmware-exact CC1101 radio presets.

Register arrays mirror the Private Unleashed / Flipper `cc1101_configs.c`:
AM270, AM650, FM238, FM476 (+FM120), MSK99 and GFSK9, including PATABLEs.
All of them run the radio in *async serial data* mode (IOCFG0 = 0x0D for RX,
0x2D for TX) — the GDO0 line then carries the raw OOK/2-FSK bitstream which
the Pi drives/samples with µs-timed GPIO waves, exactly like the Flipper does
with its timer+DMA.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# CC1101 register addresses used below (for reference)
_IOCFG0 = 0x02
_MDMCFG4 = 0x10
_MDMCFG3 = 0x11
_MDMCFG2 = 0x12
_DEVIATN = 0x15

# shared registers of every async preset (values from the firmware configs)
_COMMON: Dict[int, int] = {
    _IOCFG0: 0x0D,   # GDO0: async serial data out (RX) / in (TX)
    0x03: 0x47,      # FIFOTHR
    0x06: 0x3E,      # PKTLEN
    0x07: 0x04,      # PKTCTRL1
    0x08: 0x32,      # PKTCTRL0
    0x0C: 0x06,      # FSCTRL1
    0x13: 0x22,      # MDMCFG1
    0x14: 0xF8,      # MDMCFG0
    0x18: 0x18,      # MCSM0: auto-calibrate on RX/TX
    0x19: 0x16,      # FOCCFG
    0x1A: 0x6C,      # BSCFG
    0x1B: 0x43,      # AGCCTRL2
    0x1C: 0x40,      # AGCCTRL1
    0x1D: 0x91,      # AGCCTRL0
    0x21: 0x56,      # FREND1
    0x23: 0xE9,      # FSCAL3
    0x24: 0x2A,      # FSCAL2
    0x25: 0x00,      # FSCAL1
    0x26: 0x1F,      # FSCAL0
    0x2C: 0x81,      # TEST2
    0x2D: 0x35,      # TEST1
    0x2E: 0x09,      # TEST0
}

_OOK_PATABLE = (0x00, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)  # 12 dBm on '1'
_FSK_PATABLE = (0xC0, 0xC0, 0xC0, 0xC0, 0xC0, 0xC0, 0xC0, 0xC0)  # 12 dBm


class Preset:
    """One named CC1101 configuration (registers + PATABLE)."""

    __slots__ = ("name", "short", "modulation", "registers", "patable")

    def __init__(self, name: str, short: str, modulation: str,
                 registers: Dict[int, int], patable):
        self.name = name                # long Flipper .sub name
        self.short = short              # CLI short name
        self.modulation = modulation    # "ASK/OOK" / "2-FSK" / "MSK" / "GFSK"
        self.registers = dict(registers)
        self.patable = tuple(patable)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Preset({self.short})"


def _make(name: str, short: str, modulation: str,
         overrides: Dict[int, int], patable) -> Preset:
    regs = dict(_COMMON)
    regs.update(overrides)
    return Preset(name, short, modulation, regs, patable)


# --- OOK / ASK ---------------------------------------------------------------

AM270 = _make(
    "FuriHalSubGhzPresetOok270Async", "AM270", "ASK/OOK",
    {_MDMCFG4: 0x67, _MDMCFG3: 0x32, _MDMCFG2: 0x30, _DEVIATN: 0x00},
    _OOK_PATABLE)      # 270 kHz RX BW — long range

AM650 = _make(
    "FuriHalSubGhzPresetOok650Async", "AM650", "ASK/OOK",
    {_MDMCFG4: 0x17, _MDMCFG3: 0x32, _MDMCFG2: 0x30, _DEVIATN: 0x00},
    _OOK_PATABLE)      # 650 kHz RX BW — the default (VW/Ford/Subaru/alarms)

# --- 2-FSK -------------------------------------------------------------------

FM238 = _make(
    "FuriHalSubGhzPreset2FSKDev238Async", "FM238", "2-FSK",
    {_MDMCFG4: 0x57, _MDMCFG3: 0x32, _MDMCFG2: 0x04, _DEVIATN: 0x71},
    _FSK_PATABLE)      # ~229 kHz deviation (Scher-Khan style)

FM476 = _make(
    "FuriHalSubGhzPreset2FSKDev476Async", "FM476", "2-FSK",
    {_MDMCFG4: 0x57, _MDMCFG3: 0x32, _MDMCFG2: 0x04, _DEVIATN: 0x47},
    _FSK_PATABLE)      # 47.6 kHz deviation (Kia/Hyundai/Mitsubishi/Suzuki)

FM120 = _make(
    "FuriHalSubGhzPreset2FSKDev120Async", "FM120", "2-FSK",
    {_MDMCFG4: 0x57, _MDMCFG3: 0x32, _MDMCFG2: 0x04, _DEVIATN: 0x5B},
    _FSK_PATABLE)      # ~120 kHz deviation

# --- MSK / GFSK --------------------------------------------------------------

MSK99 = _make(
    "FuriHalSubGhzPresetMSK99_97KBAsync", "MSK99", "MSK",
    {_MDMCFG4: 0x59, _MDMCFG3: 0x32, _MDMCFG2: 0x73, _DEVIATN: 0x00},
    _FSK_PATABLE)      # 99.97 kBaud MSK

GFSK9 = _make(
    "FuriHalSubGhzPresetGFSK9_99KBAsync", "GFSK9", "GFSK",
    {_MDMCFG4: 0x59, _MDMCFG3: 0x32, _MDMCFG2: 0x53, _DEVIATN: 0x00},
    _FSK_PATABLE)      # 9.99 kBaud GFSK

# registry keyed by short name (CLI choices)
PRESETS = {
    "AM270": AM270,
    "AM650": AM650,
    "FM238": FM238,
    "FM476": FM476,
    "FM120": FM120,
    "MSK99": MSK99,
    "GFSK9": GFSK9,
}

CUSTOM_PRESET_NAME = "FuriHalSubGhzPresetCustom"


def default_preset() -> Preset:
    return AM650


def preset_by_name(name) -> Preset:
    """Look up a preset by short ('AM650') or long ('FuriHal...') name."""
    if name is None:
        return default_preset()
    key = str(name).strip()
    if key in PRESETS:
        return PRESETS[key]
    lowered = key.lower()
    for preset in PRESETS.values():
        if preset.name.lower() == lowered or preset.short.lower() == lowered:
            return preset
    raise ValueError(f"unknown preset {name!r} "
                     f"(use one of {', '.join(PRESETS)} or a custom preset)")


def custom_preset_from_bytes(blob) -> Preset:
    """Parse a Flipper `Custom_Preset:` blob.

    Layout (same as the firmware's custom preset parser): register/value
    pairs until the 00 00 terminator, then 8 PATABLE bytes.
    """
    data = list(blob)
    registers: Dict[int, int] = {}
    i = 0
    while i + 1 < len(data):
        addr, val = data[i], data[i + 1]
        if addr == 0x00 and val == 0x00:
            i += 2
            break
        registers[addr & 0x3F] = val
        i += 2
    patable = list(data[i:i + 8])
    while len(patable) < 8:
        patable.append(0x00)
    return Preset(CUSTOM_PRESET_NAME, "CUSTOM", "custom", registers, patable)


def preset_to_bytes(preset: Preset) -> List[int]:
    """Inverse of custom_preset_from_bytes (writes a Custom_Preset blob)."""
    out: List[int] = []
    for addr, val in sorted(preset.registers.items()):
        if addr in (0x0D, 0x0E, 0x0F):  # frequency registers are live values
            continue
        out.extend((addr, val))
    out.extend((0x00, 0x00))
    out.extend(int(v) & 0xFF for v in preset.patable[:8])
    return out
