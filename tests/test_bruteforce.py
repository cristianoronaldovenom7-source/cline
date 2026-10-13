"""Brute-force generators and attack runners."""

import pytest

from lib.bruteforce import (BruteForcer, frames_came, frames_keeloq_counters,
                            frames_nice)
from lib.cc1101 import CC1101, MockSPI
from lib.gpio_backend import MockBackend
from lib.keystore import Keystore
from lib.presets import AM650, FM476
from lib.subfile import SubFile
from lib.tx_engine import TxEngine

DEMO_MF = "Unleashed-Pi Demo"
DEMO_KEY = 0x1122334455667788


def _tx(keystore=None):
    mock = MockBackend()
    radio = CC1101(spi=MockSPI())
    return TxEngine(radio, mock, 27, allow_extended=True,
                   keystore=keystore), mock


def _sample_keeloq_sub():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return SubFile.load(os.path.join(root, "assets", "subghz",
                                     "SAMPLE_KeeLoq.sub"))


def _demo_keystore():
    ks = Keystore()
    ks.add(DEMO_MF, DEMO_KEY, "simple")
    return ks


def test_frames_came_generator():
    codes = list(frames_came(0, 4096))
    assert len(codes) == 4096
    assert codes[0] == 0 and codes[-1] == 4095


def test_frames_nice_generator():
    codes = list(frames_nice(0x100, 16))
    assert codes[0] == 0x100
    assert len(codes) == 16


def test_frames_keeloq_counters_unknown_mf():
    sub = SubFile()
    sub.protocol = "KeeLoq"
    sub.bit = 64
    sub.key = 0x0123456789ABCDEF
    sub.manufacture = "Unknown"
    encs = list(frames_keeloq_counters(sub, None, 4, counter_mode=2))
    assert len(encs) == 4
    assert all(len(upload) > 130 for upload in encs)


def test_run_codes_sends_every_code():
    tx, mock = _tx()
    bf = BruteForcer(tx)
    sent = bf.run_codes(AM650, 433_920_000, "CAME", range(0, 10),
                       repeat_per_code=1, inter_code_gap_s=0)
    assert sent == 10
    assert len(mock.sent_waves) == 10


def test_run_keeloq_sweep_end_to_end():
    from lib.rx_engine import RxEngine
    from lib.protocols import KeeLoqDecoder  # noqa: F401

    ks = _demo_keystore()
    sub = _sample_keeloq_sub()
    tx, mock = _tx(keystore=ks)
    bf = BruteForcer(tx)

    sent = bf.run_keeloq_sweep(FM476, sub.frequency, sub, ks,
                               counter_from=0x4000, counter_to=0x4004,
                               step=1)
    assert sent == 5

    radio = CC1101(spi=MockSPI())
    rx = RxEngine(radio, mock, 27, keystore=ks)
    rx.start(FM476, sub.frequency)
    seen = []
    rx.on_found(seen.append)
    for wave in mock.sent_waves:
        mock.feed_levels(27, wave)
    rx.stop()
    counters = sorted(r.cnt for r in seen)
    assert counters == [0x4000, 0x4001, 0x4002, 0x4003, 0x4004]


def test_run_keeloq_sweep_needs_key():
    sub = SubFile()
    sub.protocol = "KeeLoq"
    sub.bit = 64
    sub.key = 0x0123456789ABCDEF
    sub.manufacture = "Unknown"
    tx, _mock = _tx()
    bf = BruteForcer(tx)
    with pytest.raises(ValueError):
        bf.run_keeloq_sweep(AM650, 433_920_000, sub, None,
                            counter_from=0, counter_to=4)
