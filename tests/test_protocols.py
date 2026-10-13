"""Protocol encoders/decoders through the mock radio path."""

import pytest

from lib.cc1101 import CC1101, MockSPI
from lib.gpio_backend import MockBackend
from lib.keystore import Keystore
from lib.presets import AM650
from lib.protocols import (CameEncoder, HoltekEncoder, KeeLoqDecoder,
                            KeeLoqEncoder, NiceFloEncoder, PrincetonDecoder,
                            PrincetonEncoder)
from lib.rx_engine import RxEngine

DEMO_MF = "Unleashed-Pi Demo"
DEMO_KEY = 0x1122334455667788


def _demo_keystore():
    ks = Keystore()
    ks._entries[DEMO_MF] = type("M", (), {"name": DEMO_MF, "key": DEMO_KEY,
                                         "type": "simple"})()
    return ks


def _rx_with(keystore=None):
    mock = MockBackend()
    radio = CC1101(spi=MockSPI())
    rx = RxEngine(radio, mock, 27, keystore=keystore)
    rx.start(AM650, 433_920_000)
    return mock, rx


def test_princeton_roundtrip():
    enc = PrincetonEncoder(data=0x1A2B3C, data_count_bit=24, te=390, guard_time=30)
    mock, rx = _rx_with()
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, enc.build_upload() * 3)
    rx.stop()
    assert len(found) == 1
    r = found[0]
    assert r.protocol_name == "Princeton"
    assert r.data == 0x1A2B3C
    assert abs(r.te - 390) <= 2
    assert (r.data >> 4) == 0x1A2B3 and (r.data & 0xF) == 0xC


def test_came_roundtrip():
    enc = CameEncoder(data=0x6A3, data_count_bit=12)
    mock, rx = _rx_with()
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, enc.build_upload() * 3)
    rx.stop()
    assert found
    assert found[-1].protocol_name == "CAME"
    assert found[-1].data == 0x6A3
    assert found[-1].data_count_bit == 12


def test_nice_roundtrip():
    enc = NiceFloEncoder(data=0x345, data_count_bit=12)
    mock, rx = _rx_with()
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, enc.build_upload() * 3)
    rx.stop()
    assert found
    assert found[-1].protocol_name == "Nice FLO"
    assert found[-1].data == 0x345


def test_holtek_roundtrip():
    data = 0x5123456789 & 0xFFFFFFFFFF
    enc = HoltekEncoder(data=data, data_count_bit=40)
    mock, rx = _rx_with()
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, enc.build_upload() * 3)
    rx.stop()
    assert found
    assert found[-1].protocol_name == "Holtek"
    assert found[-1].data == data
    assert found[-1].data_count_bit == 40


def test_keeloq_roundtrip_identifies_manufacturer():
    ks = _demo_keystore()
    enc = KeeLoqEncoder(keystore=ks)
    enc.set_frame(serial=0x2C5B1F, btn=0x1, cnt=0x1234,
                  manufacture_name=DEMO_MF, counter_mode=6)  # freeze
    upload, repeat = enc.get_upload()
    assert repeat == 3
    assert len(upload) > 130  # header + 66 bits
    mock, rx = _rx_with(keystore=ks)
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, upload)
    rx.stop()
    assert found
    r = found[0]
    assert r.protocol_name == "KeeLoq"
    assert r.manufacture_name == DEMO_MF
    assert r.serial == 0x2C5B1F
    assert r.btn == 0x1
    assert r.cnt == 0x1234


def test_keeloq_counter_mode_2_over_the_air():
    ks = _demo_keystore()
    enc = KeeLoqEncoder(keystore=ks)
    enc.set_frame(serial=0x2C5B1F, btn=0x1, cnt=0x1000,
                  manufacture_name=DEMO_MF, counter_mode=2)
    upload1, _ = enc.get_upload()
    d1 = enc.data
    upload2, _ = enc.get_upload()
    d2 = enc.data
    assert d1 != d2
    mock, rx = _rx_with(keystore=ks)
    seen = []
    rx.on_found(seen.append)
    mock.feed_levels(27, upload1 + upload2)
    rx.stop()
    assert [r.cnt for r in seen] == [0x4333, 0x7666]


def test_keeloq_unknown_manufacture():
    from lib import keeloq_crypto as kq
    from lib.protocols.keeloq import build_upload
    key = kq.join_frame(kq.build_fix(0x1111111, 0x2), 0xAAAAAAAA)
    mock, rx = _rx_with()
    found = []
    rx.on_found(found.append)
    mock.feed_levels(27, build_upload(key, 400))
    rx.stop()
    assert found
    assert found[0].protocol_name == "KeeLoq"
    assert found[0].manufacture_name == "Unknown"
    assert found[0].cnt is None


def test_keeloq_decoder_offline_analysis():
    ks = _demo_keystore()
    dec = KeeLoqDecoder(keystore=ks)
    from lib import keeloq_crypto as kq
    hop = kq.keeloq_encrypt(kq.build_decrypt(0x1, 0x2C5B1F, 0x1234), DEMO_KEY)
    key = kq.join_frame(kq.build_fix(0x2C5B1F, 0x1), hop)
    r = dec.make_result_from_data(key)
    assert r.manufacture_name == DEMO_MF
    assert r.cnt == 0x1234
    assert r.btn == 0x1
    assert r.serial == 0x2C5B1F


def test_princeton_encoder_exact_waveform():
    enc = PrincetonEncoder(data=0x0BADC0, data_count_bit=24, te=390)
    wave = enc.build_upload()
    assert wave[0] == (True, 390)     # MSB of 0x0BADC0 is 0 -> 1T high
    assert wave[1] == (False, 390 * 3)
    total = sum(d for _l, d in wave)
    assert total == 24 * 4 * 390 + 390 + 30 * 390  # bits + stop + guard
