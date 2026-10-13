"""TX engine + RX engine end-to-end through the mock radio."""

import pytest

from lib.cc1101 import CC1101, MockSPI
from lib.gpio_backend import MockBackend
from lib.keystore import Keystore
from lib.presets import AM650
from lib.protocols import PrincetonEncoder
from lib.rx_engine import RxEngine
from lib.subfile import SubFile
from lib.tx_engine import TxEngine

DEMO_MF = "Unleashed-Pi Demo"
DEMO_KEY = 0x1122334455667788


def _tx(keystore=None):
    mock = MockBackend()
    radio = CC1101(spi=MockSPI())
    return TxEngine(radio, mock, 27, allow_extended=True, keystore=keystore), mock


def test_tx_mock_loopback_waveform():
    tx, mock = _tx()
    enc = PrincetonEncoder(data=0x0BADC0, data_count_bit=24, te=390)
    sent = tx.send(AM650, 433_920_000, enc.build_upload(), repeat=2)
    assert sent == 2
    assert len(mock.sent_waves) == 2
    wave = mock.sent_waves[0]
    assert wave[0] == (True, 390)
    assert wave[1] == (False, 390 * 3)
    total = sum(d for _l, d in wave)
    assert total == 24 * 4 * 390 + 390 + 30 * 390  # bits + stop + guard


def test_tx_range_rejected():
    tx, mock = _tx()
    enc = PrincetonEncoder(data=1, data_count_bit=24)
    # 500 MHz is outside even the extended bands
    with pytest.raises(ValueError):
        tx.send(AM650, 500_000_000, enc.build_upload(), repeat=1)


def test_send_subfile_raw():
    tx, mock = _tx()
    sub = SubFile()
    sub.filetype = "Flipper SubGhz RAW File"
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.raw_data = [400, -800, 1200, -400]
    sub.repeat = 4
    assert tx.send_subfile(sub) == 4
    assert len(mock.sent_waves) == 4
    assert mock.sent_waves[0] == [(True, 400), (False, 800),
                                 (True, 1200), (False, 400)]


def test_send_subfile_came():
    tx, mock = _tx()
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "CAME"
    sub.bit = 12
    sub.key = 0x6A3
    sub.te = 320
    sub.repeat = 2
    assert tx.send_subfile(sub) == 2
    wave = mock.sent_waves[0]
    assert wave[0] == (False, 320 * 24)  # leading guard


def test_send_subfile_keeloq_increments_counter():
    ks = Keystore()
    ks.add(DEMO_MF, DEMO_KEY, "simple")
    tx, mock = _tx(keystore=ks)
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "KeeLoq"
    sub.bit = 64
    from lib import keeloq_crypto as kq
    hop = kq.keeloq_encrypt(kq.build_decrypt(0x1, 0x2C5B1F, 0x1000), DEMO_KEY)
    sub.key = kq.join_frame(kq.build_fix(0x2C5B1F, 0x1), hop)
    sub.te = 400
    sub.manufacture = DEMO_MF
    sub.counter_mode = 2
    sub.repeat = 3
    sent = tx.send_subfile(sub)
    assert sent == 3

    # decode the transmitted wave back: counter must be 0x1000 + 0x3333
    radio = CC1101(spi=MockSPI())
    rx = RxEngine(radio, mock, 27, keystore=ks)
    rx.start(AM650, 433_920_000)
    seen = []
    rx.on_found(seen.append)
    mock.feed_levels(27, mock.sent_waves[0])
    rx.stop()
    assert [r.cnt for r in seen] == [0x4333]


def test_rssi_and_recording_paths():
    mock = MockBackend()
    radio = CC1101(spi=MockSPI())
    rx = RxEngine(radio, mock, 27)
    rx.start(AM650, 433_920_000)
    rx.start_recording()
    enc = PrincetonEncoder(data=0x1A2B3C, data_count_bit=24, te=390)
    mock.feed_levels(27, enc.build_upload())
    levels = rx.stop_recording()
    rx.stop()
    assert levels  # recorded the RAW level stream
    assert -100 < rx.rssi_dbm() < -20  # mock radio reports a plausible RSSI
