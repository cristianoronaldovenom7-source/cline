"""Holtek 40-bit remotes (HT640 family, te 400 µs, 1T/3T PWM)."""

from __future__ import annotations

from typing import List

from .base import DecoderResult, PwmBlockDecoder

TE = 400
BITS = 40
GUARD_T = 24


class HoltekDecoder(PwmBlockDecoder):
    def __init__(self):
        super().__init__("Holtek", bit_count=BITS, te=TE,
                         te_min=300, te_max=520, guard_t=12.0,
                         stop_bit=False)

    def make_result(self, data: int, te: int) -> DecoderResult:
        return DecoderResult("Holtek", data, BITS, te=te)


class HoltekEncoder:
    def __init__(self, data: int = 0, data_count_bit: int = BITS,
                 te: int = TE):
        self.data = int(data)
        self.data_count_bit = int(data_count_bit) if data_count_bit else BITS
        self.te = int(te) if te else TE

    def build_upload(self) -> List:
        out = [(False, self.te * GUARD_T)]
        for i in range(self.data_count_bit - 1, -1, -1):
            if (self.data >> i) & 1:
                out.append((True, self.te * 3))
                out.append((False, self.te))
            else:
                out.append((True, self.te))
                out.append((False, self.te * 3))
        return out
