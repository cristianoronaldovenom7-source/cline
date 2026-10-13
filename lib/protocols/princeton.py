"""Princeton 24-bit remotes (EV1527-style PT-2260 family).

Frame: 24 data bits + stop HIGH (1T) + guard LOW (GuardTime * te).
te default 390 µs, GuardTime default 30 te units (both from .sub files).
"""

from __future__ import annotations

from typing import List, Optional

from .base import DecoderResult, PwmBlockDecoder


class PrincetonDecoder(PwmBlockDecoder):
    def __init__(self):
        super().__init__("Princeton", bit_count=24, te=390,
                         te_min=250, te_max=620, guard_t=12.0, stop_bit=True)

    def make_result(self, data: int, te: int) -> DecoderResult:
        serial = (data >> 4) & 0xFFFFF
        btn = data & 0xF
        return DecoderResult("Princeton", data, 24, te=te,
                            serial=serial, btn=btn,
                            extra={"guard_time": max(1, round(30))})


class PrincetonEncoder:
    """Builds a Princeton frame: bits + stop + guard (Flipper-exact)."""

    def __init__(self, data: int = 0, data_count_bit: int = 24, te: int = 390,
                 guard_time: Optional[int] = None):
        self.data = int(data)
        self.data_count_bit = int(data_count_bit) if data_count_bit else 24
        self.te = int(te) if te else 390
        self.guard_time = int(guard_time) if guard_time is not None else 30

    def build_upload(self) -> List:
        out = []
        for i in range(self.data_count_bit - 1, -1, -1):
            if (self.data >> i) & 1:
                out.append((True, self.te * 3))
                out.append((False, self.te))
            else:
                out.append((True, self.te))
                out.append((False, self.te * 3))
        out.append((True, self.te))                    # stop bit
        out.append((False, self.te * self.guard_time))  # guard
        return out
