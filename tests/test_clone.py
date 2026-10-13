"""Shadow-clone: next-code generation + persistent counter mirror."""

import os

import pytest

from lib.clone_state import CloneState
from lib.keeloq_tx import clone_next_subs, predicted_counters
from lib.keystore import Keystore
from lib.protocols import KeeLoqDecoder
from lib.subfile import SubFile

DEMO_MF = "Unleashed-Pi Demo"
DEMO_KEY = 0x1122334455667788


def _demo_keystore():
    ks = Keystore()
    ks.add(DEMO_MF, DEMO_KEY, "simple")
    return ks


def _sample():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return SubFile.load(os.path.join(root, "assets", "subghz",
                                     "SAMPLE_KeeLoq.sub"))


def test_clone_next_subs_counters():
    ks = _demo_keystore()
    sub = _sample()
    subs, counters = clone_next_subs(sub, keystore=ks, steps=3,
                                    counter_mode=2)
    assert counters == [0x4567, 0x789A, 0xABCD]
    assert len(subs) == 3


def test_clones_decode_back_with_exact_counters():
    ks = _demo_keystore()
    sub = _sample()
    subs, counters = clone_next_subs(sub, keystore=ks, steps=3,
                                    counter_mode=2)
    dec = KeeLoqDecoder(keystore=ks)
    for clone, cnt in zip(subs, counters):
        result = dec.make_result_from_data(clone.key)
        assert result.cnt == cnt
        assert result.manufacture_name == DEMO_MF
        assert clone.manufacture == DEMO_MF


def test_predicted_counters_chain():
    ks = _demo_keystore()
    sub = _sample()
    mf, chain = predicted_counters(sub, keystore=ks, count=3,
                                   counter_mode=2)
    assert mf == DEMO_MF
    assert chain == [0x4567, 0x789A, 0xABCD]


def test_clone_unknown_manufacture_replays():
    sub = _sample()
    sub.manufacture = "Unknown"
    subs, counters = clone_next_subs(sub, keystore=None, steps=3,
                                     counter_mode=2)
    assert counters == []
    assert len(subs) == 3
    assert subs[0].key == sub.key  # exact replay, no re-encryption


def test_clone_state_wrap_aware_and_persistent(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    state = CloneState(path)
    assert state.observe(DEMO_MF, 0x2C5B1F, 1, 0x1000) == 0x1000
    # stale frame (counter went backwards) must NOT move the mirror
    assert state.observe(DEMO_MF, 0x2C5B1F, 1, 0x0800) == 0x1000
    # a jump towards 0xFFFF is still forward
    assert state.observe(DEMO_MF, 0x2C5B1F, 1, 0xFFF0) == 0xFFF0
    # wrap past 0xFFFF counts as forward
    assert state.observe(DEMO_MF, 0x2C5B1F, 1, 0x0010) == 0x0010
    state.advance(DEMO_MF, 0x2C5B1F, 0x4567)
    # persistence: a fresh instance reloads the file
    assert CloneState(path).get(DEMO_MF, 0x2C5B1F)["cnt"] == 0x4567
    assert CloneState(path).get(DEMO_MF, 0xFFFFFFF) is None
