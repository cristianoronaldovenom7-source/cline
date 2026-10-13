"""Nice FLO 12-bit gates/barriers (te 500 µs, 1T/3T PWM, guard LOW)."""

from __future__ import annotations

from typing import List

from .base import DecoderResult, PwmBlockDecoder

TE = 500
BITS = 12
GUARD_T = 24


class NiceFloDecoder(PwmBlockDecoder):
    def __init__(self):
        super().__init__("Nice FLO", bit_count=BITS, te=TE,
                         te_min=430, te_max=650, guard_t=12.0,
                         stop_bit=False)

    def make_result(self, data: int, te: int) -> DecoderResult:
        return DecoderResult("Nice FLO", data, BITS, te=te)


class NiceFloEncoder:
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
