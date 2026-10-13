"""Rolling-counter manipulation modes 0-7 + counter chains."""

import pytest

from lib.protocols.keeloq import counter_chain, next_counter


def test_mode0_standard_increment():
    assert next_counter(0x0000, 0) == 1
    assert next_counter(0x0001, 0) == 2


def test_mode0_counter_mult():
    assert next_counter(0x1000, 0, counter_mult=5) == 0x1005
    assert next_counter(0x0002, 0, counter_mult=-1) == 0x0001


def test_mode0_ofex_overflow_pattern():
    mult = -0x7FFFFFFF
    assert next_counter(0x0000, 0, counter_mult=mult) == 0x0001
    assert next_counter(0x0001, 0, counter_mult=mult) == 0xFFFE
    assert next_counter(0xFFFE, 0, counter_mult=mult) == 0xFFFF
    assert next_counter(0xFFFF, 0, counter_mult=mult) == 0x0000


def test_mode1_ofex():
    assert next_counter(0x0000, 1) == 0x0001
    assert next_counter(0x0001, 1) == 0xFFFE
    assert next_counter(0xFFFE, 1) == 0xFFFF
    assert next_counter(0xFFFF, 1) == 0x0000


def test_mode2_plus_0x3333():
    assert next_counter(0x1234, 2) == 0x4567
    assert next_counter(0x4567, 2) == 0x789A
    assert next_counter(0x789A, 2) == 0xABCD


def test_mode2_wraps_to_zero():
    assert next_counter(0xE000, 2) == 0x0000  # firmware rule


def test_mode3_pattern():
    assert next_counter(0x8006, 3) == 0x8007
    assert next_counter(0x8007, 3) == 0x0006
    assert next_counter(0x0006, 3) == 0x0007
    assert next_counter(0x0007, 3) == 0x8006


def test_mode4_pattern():
    assert next_counter(0x807B, 4) == 0x807C
    assert next_counter(0x807C, 4) == 0x007B
    assert next_counter(0x007B, 4) == 0x007C
    assert next_counter(0x007C, 4) == 0x807B


def test_mode5_toggle():
    assert next_counter(0x0000, 5) == 0xFFFF
    assert next_counter(0xFFFF, 5) == 0x0000


def test_mode6_freeze():
    assert next_counter(0x1234, 6) == 0x1234
    assert next_counter(0xABCD, 6) == 0xABCD


def test_mode7_and_chain():
    assert next_counter(0x0000, 7) == 0x0001
    chain = list(counter_chain(0x1234, 7, 7))
    assert chain == [0x0000, 0x1234, 0x1235, 0x4567, 0x789A, 0xABCD, 0xDF00]


def test_counter_chain_lengths():
    assert len(list(counter_chain(0, 0, 10))) == 10
    assert list(counter_chain(0x1234, 2, 3)) == [0x4567, 0x789A, 0xABCD]


def test_counter_mode_invalid():
    with pytest.raises(ValueError):
        next_counter(0, 8)
