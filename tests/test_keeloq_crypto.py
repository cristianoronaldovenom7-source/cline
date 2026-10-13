"""KeeLoq cipher, learning derivations and frame helpers."""

import pytest

from lib import keeloq_crypto as kq

DEMO_KEY = 0x1122334455667788


def test_cipher_roundtrip_vectors():
    key = 0x5CE7B6A6AC2A54B3
    for data in (0x00000000, 0x111F1234, 0xFFFFFFFF, 0x0BADF00D, 0xDEADBEEF):
        enc = kq.keeloq_encrypt(data, key)
        assert enc != data
        assert kq.keeloq_decrypt(enc, key) == data


def test_cipher_differs_per_key():
    data = 0x12345678
    assert kq.keeloq_encrypt(data, 1) != kq.keeloq_encrypt(data, 2)


def test_cipher_64bit_keys():
    enc = kq.keeloq_encrypt(0x1, 0xFFFFFFFFFFFFFFFF)
    assert 0 <= enc <= 0xFFFFFFFF
    assert kq.keeloq_decrypt(enc, 0xFFFFFFFFFFFFFFFF) == 0x1


def test_normal_learning_stable_64bit():
    man = kq.normal_learning(0x12C5B1F, DEMO_KEY)
    assert man == kq.normal_learning(0x12C5B1F, DEMO_KEY)
    assert 0 <= man <= 0xFFFFFFFFFFFFFFFF


def test_secure_learning_stable_64bit():
    man = kq.secure_learning(0x12C5B1F, 0xDEADBEEF, DEMO_KEY)
    assert man == kq.secure_learning(0x12C5B1F, 0xDEADBEEF, DEMO_KEY)
    assert 0 <= man <= 0xFFFFFFFFFFFFFFFF


def test_learnings_differ():
    seed = 0x12C5B1F
    assert (kq.normal_learning(seed, DEMO_KEY)
            != kq.secure_learning(seed, 0xDEADBEEF, DEMO_KEY))


def test_split_join_inverse():
    frame = kq.join_frame(0x12C5B1F, 0x89ABCDEF)
    fix, hop = kq.split_frame(frame)
    assert (fix, hop) == (0x12C5B1F, 0x89ABCDEF)


def test_parse_fix_button_serial():
    btn, serial = kq.parse_fix(0x2C5B1F1)
    assert btn == 0x1
    assert serial == 0x2C5B1F


def test_parse_build_decrypt_inverse():
    dec = kq.build_decrypt(0xA, 0x3AB, 0x1234)
    btn, serial10, cnt = kq.parse_decrypt(dec)
    assert (btn, serial10, cnt) == (0xA, 0x3AB, 0x1234)


def test_build_fix_inverse():
    assert kq.build_fix(0x2C5B1F, 0x1) == 0x2C5B1F1
    btn, serial = kq.parse_fix(kq.build_fix(0x1234567, 0xC))
    assert (btn, serial) == (0xC, 0x1234567)
