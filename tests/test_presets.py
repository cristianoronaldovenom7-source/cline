"""Radio presets + CC1101 frequency math."""

import pytest

from lib.presets import (AM270, AM650, CUSTOM_PRESET_NAME, FM476, PRESETS,
                          custom_preset_from_bytes, default_preset,
                          preset_by_name, preset_to_bytes)
from lib.util import (frequency_to_registers, is_tx_allowed,
                      registers_to_frequency)


def test_am650_firmware_registers():
    reg = dict(AM650.registers)
    assert reg[0x02] == 0x0D   # IOCFG0 async serial data
    assert reg[0x10] == 0x17   # MDMCFG4 -> 650 kHz RX BW
    assert reg[0x12] == 0x30   # MDMCFG2 -> ASK/OOK
    assert AM650.patable[1] == 0xC0  # 12 dBm on the OOK '1' level


def test_am270_270khz_bw():
    assert dict(AM270.registers)[0x10] == 0x67


def test_fm476_2fsk_47khz():
    reg = dict(FM476.registers)
    assert reg[0x15] == 0x47   # DEVIATN 47.6 kHz
    assert reg[0x12] == 0x04    # 2-FSK
    assert FM476.patable[0] == 0xC0


def test_preset_lookup_short_and_long():
    assert preset_by_name("FM476") is FM476
    assert preset_by_name("FuriHalSubGhzPresetOok650Async") is AM650
    assert preset_by_name(None) is default_preset()


def test_preset_lookup_unknown():
    with pytest.raises(ValueError):
        preset_by_name("NOPE")


def test_all_presets_registered():
    for short in ("AM270", "AM650", "FM238", "FM476", "FM120", "MSK99", "GFSK9"):
        assert short in PRESETS


def test_custom_preset_parse():
    blob = [0x02, 0x0D, 0x10, 0x17, 0x00, 0x00, 0xC0, 0, 0, 0, 0, 0, 0, 0]
    custom = custom_preset_from_bytes(blob)
    assert custom.name == CUSTOM_PRESET_NAME
    assert dict(custom.registers) == {0x02: 0x0D, 0x10: 0x17}
    assert custom.patable[0] == 0xC0


def test_frequency_math_firmware_exact():
    assert frequency_to_registers(433_920_000) == (0x10, 0xB0, 0x71)
    assert frequency_to_registers(315_000_000) == (0x0C, 0x1D, 0x89)
    real = registers_to_frequency(0x10, 0xB0, 0x71)
    assert abs(real - 433_920_000) < 1500


def test_frequency_math_common_channels():
    for freq in (300_000_000, 390_000_000, 418_000_000, 433_420_000,
                 434_775_000, 868_350_000, 915_000_000):
        f2, f1, f0 = frequency_to_registers(freq)
        assert abs(registers_to_frequency(f2, f1, f0) - freq) < 400


def test_tx_range_policing():
    assert is_tx_allowed(433_920_000)
    assert is_tx_allowed(315_000_000)
    assert not is_tx_allowed(464_500_000, extended=False)  # above 464 MHz
    assert not is_tx_allowed(480_000_000, extended=False)  # extended only
    assert is_tx_allowed(480_000_000, extended=True)
    assert is_tx_allowed(350_000_000, extended=True)  # 281-361 band
    assert not is_tx_allowed(500_000_000, extended=True)  # no band at all
