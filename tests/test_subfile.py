"""Flipper .sub file reading/writing."""

import os

import pytest

from lib.subfile import SubFile, raw_durations_to_levels

DEMO_MF = "Unleashed-Pi Demo"


def _tmp(tmp_path, name="t.sub"):
    return os.path.join(str(tmp_path), name)


def test_decoded_keeloq_roundtrip(tmp_path):
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = "FuriHalSubGhzPreset2FSKDev476Async"
    sub.protocol = "KeeLoq"
    sub.bit = 64
    sub.key = 0x0123456789ABCDEF
    sub.te = 400
    sub.manufacture = DEMO_MF
    sub.seed = 0xDEADBEEF
    sub.counter_mode = 2
    sub.repeat = 7
    path = _tmp(tmp_path)
    sub.save(path)
    back = SubFile.load(path)
    assert back.frequency == sub.frequency
    assert back.preset_name == sub.preset_name
    assert back.preset_short() == "FM476"
    assert back.protocol == "KeeLoq"
    assert back.bit == 64
    assert back.key == 0x0123456789ABCDEF
    assert back.manufacture == DEMO_MF
    assert back.seed == 0xDEADBEEF
    assert back.counter_mode == 2
    assert back.repeat == 7


def test_keeloq_written_flipper_style(tmp_path):
    sub = SubFile()
    sub.protocol = "KeeLoq"
    sub.bit = 64
    sub.key = 0x0123456789ABCDEF
    path = _tmp(tmp_path)
    sub.save(path)
    text = open(path).read()
    assert "Protocol: KeeLoq (64bit)" in text


def test_keeloq_read_flipper_style(tmp_path):
    path = _tmp(tmp_path)
    with open(path, "w") as fh:
        fh.write("Filetype: Flipper SubGhz Key File\nVersion: 1\n"
                 "Frequency: 433920000\n"
                 "Preset: FuriHalSubGhzPresetOok650Async\n"
                 "Protocol: KeeLoq (64bit)\nBit: 64\n"
                 "Key: 5A B5 09 2B E1 82 0C 5B\nTe: 400\nRepeat: 3\n")
    back = SubFile.load(path)
    assert back.protocol == "KeeLoq"
    assert back.key == 0x5AB5092BE1820C5B


def test_raw_roundtrip(tmp_path):
    raw = SubFile()
    raw.filetype = "Flipper SubGhz RAW File"
    raw.frequency = 315_000_000
    raw.preset_name = "FuriHalSubGhzPresetOok650Async"
    raw.raw_data = [400, -800, 1200, -400, 30000]
    path = _tmp(tmp_path)
    raw.save(path)
    back = SubFile.load(path)
    assert back.is_raw
    assert back.raw_data == [400, -800, 1200, -400, 30000]


def test_custom_preset_roundtrip(tmp_path):
    cust = SubFile()
    cust.preset_name = "FuriHalSubGhzPresetCustom"
    cust.custom_preset_bytes = [0x02, 0x0D, 0x10, 0x17, 0x00, 0x00,
                                0xC0, 0, 0, 0, 0, 0, 0, 0]
    cust.protocol = "CAME"
    cust.bit = 12
    cust.key = 0x6A3
    path = _tmp(tmp_path)
    cust.save(path)
    back = SubFile.load(path)
    assert back.custom_preset_bytes == cust.custom_preset_bytes
    p = back.preset()
    assert dict(p.registers) == {0x02: 0x0D, 0x10: 0x17}
    assert p.patable[0] == 0xC0


def test_princeton_guard_time_roundtrip(tmp_path):
    sub = SubFile()
    sub.protocol = "Princeton"
    sub.bit = 24
    sub.key = 0x1A2B3C
    sub.te = 390
    sub.guard_time = 30
    path = _tmp(tmp_path)
    sub.save(path)
    back = SubFile.load(path)
    assert back.guard_time == 30
    assert "GuardTime: 30" in open(path).read()


def test_key_padded_bytes(tmp_path):
    sub = SubFile()
    sub.protocol = "CAME"
    sub.bit = 12
    sub.key = 0x6A3
    path = _tmp(tmp_path)
    sub.save(path)
    assert "Key: 6A 30" in open(path).read()
    assert SubFile.load(path).key == 0x6A3


def test_raw_durations_to_levels():
    assert raw_durations_to_levels([400, -800, 1200, -400, 30000]) == [
        (True, 400), (False, 800), (True, 1200), (False, 400), (True, 30000)]


def test_holltek_alias(tmp_path):
    path = _tmp(tmp_path)
    with open(path, "w") as fh:
        fh.write("Filetype: Flipper SubGhz Key File\nVersion: 1\n"
                 "Frequency: 433920000\n"
                 "Preset: FuriHalSubGhzPresetOok650Async\n"
                 "Protocol: Holltek\nBit: 40\nKey: 51 23 45 67 89\n")
    back = SubFile.load(path)
    assert back.protocol == "Holtek"
    assert back.key == 0x5123456789


def test_sample_assets_roundtrip():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("SAMPLE_CAME.sub", "SAMPLE_Nice_FLO.sub",
                 "SAMPLE_Princeton.sub", "SAMPLE_Holtek.sub",
                 "SAMPLE_KeeLoq.sub", "SAMPLE_RAW.sub"):
        sub = SubFile.load(os.path.join(root, "assets", "subghz", name))
        assert sub.protocol or sub.is_raw
        assert sub.frequency == 433_920_000
