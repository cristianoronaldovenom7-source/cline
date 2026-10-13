"""Shared decoder/encoder plumbing for the ported protocols."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional


class DecoderResult:
    """A decoded frame (what `read` prints and `--save` stores)."""

    __slots__ = ("protocol_name", "data", "data_count_bit", "te",
                 "manufacture_name", "serial", "btn", "cnt", "seed", "extra")

    def __init__(self, protocol_name: str, data: int, data_count_bit: int,
                 te: int = 0, manufacture_name: str = "", serial: int = None,
                 btn: int = None, cnt: int = None, seed: int = None,
                 extra: Optional[Dict] = None):
        self.protocol_name = protocol_name
        self.data = data
        self.data_count_bit = data_count_bit
        self.te = te
        self.manufacture_name = manufacture_name
        self.serial = serial
        self.btn = btn
        self.cnt = cnt
        self.seed = seed
        self.extra = extra or {}

    def summary(self) -> str:
        lines = [f"{self.protocol_name}  {self.data_count_bit}bit",
                f"Key: {self.data:0{max(1, (self.data_count_bit + 3) // 4)}X}"]
        if self.serial is not None:
            lines.append(f"Sn: 0x{self.serial:07X}  "
                         f"Btn: 0x{self.btn:X}" if self.btn is not None
                         else f"Sn: 0x{self.serial:07X}")
        if self.cnt is not None:
            lines.append(f"Cnt: 0x{self.cnt:04X}")
        if self.te:
            lines.append(f"Te: {self.te}")
        if self.manufacture_name and self.manufacture_name != "Unknown":
            lines.append(f"MF: {self.manufacture_name}")
        for key, value in self.extra.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover
        return (f"DecoderResult({self.protocol_name}, data={self.data:X}, "
                f"te={self.te})")


class BaseDecoder:
    """Common callback plumbing + the "two identical frames" rule.

    Fixed-code remotes repeat the same frame many times per press; the
    firmware only reports a frame once it has seen it twice in a row (and
    not again until a different frame intervenes) — identical behaviour here.
    """

    two_frame_rule = True

    def __init__(self):
        self._callbacks: List[Callable[[DecoderResult], None]] = []
        self._prev_sig = None
        self._prev2_sig = None

    def on_found(self, callback: Callable[[DecoderResult], None]) -> None:
        self._callbacks.append(callback)

    def reset_rule(self) -> None:
        self._prev_sig = None
        self._prev2_sig = None

    def _emit(self, result: DecoderResult) -> None:
        if self.two_frame_rule:
            sig = (result.protocol_name, result.data_count_bit, result.data)
            emit = (self._prev_sig == sig and self._prev2_sig != sig)
            self._prev2_sig = self._prev_sig
            self._prev_sig = sig
            if not emit:
                return
        for callback in self._callbacks:
            callback(result)


class PwmBlockDecoder(BaseDecoder):
    """Shared PWM block decoder: guard-sync + 1T/3T bits + repeat rule.

    Frame on air (all timing in units of te):

        [guard LOW (>= guard_t*te)] [bit0 .. bitN-1] [stop HIGH 1T]? [guard]

    bit '0' = HIGH 1T + LOW 3T      bit '1' = HIGH 3T + LOW 1T

    A frame only counts when its END is confirmed by a guard LOW right after
    the last bit (merged into it on real air, a separate event in mock data);
    if more bits follow instead, the signal belongs to a longer protocol and
    the decoder resynchronizes — that is how 12/24/40-bit remotes sharing
    the same PWM scheme stay apart.
    """

    SYNC, HIGH_WAIT, LOW_WAIT, STOP_WAIT, STOP_LOW, WAIT_END = range(6)

    def __init__(self, protocol_name: str, bit_count: int, te: float,
                 te_min: float, te_max: float, guard_t: float = 12.0,
                 stop_bit: bool = False, data_count_bit: int = None):
        super().__init__()
        self.protocol_name = protocol_name
        self.bit_count = bit_count
        self.te_default = float(te)
        self.te = float(te)
        self.te_min = float(te_min)
        self.te_max = float(te_max)
        self.guard_t = float(guard_t)
        self.stop_bit = stop_bit
        self.data_count_bit = data_count_bit or bit_count
        self._state = self.SYNC
        self._bits = 0
        self._count = 0
        self._h = 0.0

    # -- helpers for subclasses ---------------------------------------------
    def make_result(self, data: int, te: int) -> DecoderResult:
        return DecoderResult(self.protocol_name, data, self.data_count_bit,
                            te=te)

    # -- the state machine ----------------------------------------------------
    def feed(self, level: bool, duration: int) -> None:
        d = int(duration)
        if d <= 0:
            return
        state = self._state

        if state == self.SYNC:
            if (not level) and d >= self.guard_t * self.te:
                self._state = self.HIGH_WAIT

        elif state == self.HIGH_WAIT:
            if level:
                self._h = float(d)
                self._state = self.LOW_WAIT
            elif d >= self.guard_t * self.te:
                pass  # merged guard, keep waiting for the first HIGH
            elif d >= self.te_min:
                self._state = self.SYNC  # stray short low — resync
            else:
                self._state = self.SYNC

        elif state == self.LOW_WAIT:
            if level:
                # consecutive highs shouldn't happen in an edge stream
                self._state = self.SYNC
                return
            self._handle_bit_low(d)

        elif state == self.STOP_WAIT:
            if level:
                if abs(d - self.te) < 0.45 * self.te:
                    self._state = self.STOP_LOW
                else:
                    self._state = self.SYNC
            else:
                self._state = self.SYNC

        elif state == self.STOP_LOW:
            if (not level) and d >= self.guard_t * self.te:
                self._finish(d)
            else:
                self._state = self.SYNC

        elif state == self.WAIT_END:
            # last bit seen; only a guard LOW confirms the frame's end
            if (not level) and d >= self.guard_t * self.te:
                self._finish(d)
            else:
                self._state = self.SYNC

    def _handle_bit_low(self, low: float) -> None:
        h = self._h
        te = self.te
        if low >= self.guard_t * self.te:
            # real air merges the last bit's LOW with the frame guard —
            # classify by the HIGH alone (1T -> '0', 3T -> '1')
            if abs(h - te) < 0.45 * te:
                bit = 0
                short = h
            elif abs(h - 3 * te) < 1.35 * te:
                bit = 1
                short = te
            else:
                self._state = self.SYNC
                return
        elif abs(h - te) < 0.45 * te and abs(low - 3 * te) < 1.35 * te:
            bit = 0
            short = h
        elif abs(h - 3 * te) < 1.35 * te and abs(low - te) < 0.45 * te:
            bit = 1
            short = low
        else:
            self._state = self.SYNC
            return
        if not (self.te_min <= short <= self.te_max):
            self._state = self.SYNC  # wrong band for this protocol
            return
        # refine te toward the measured short level
        self.te = min(max(0.9 * te + 0.1 * short, self.te_min), self.te_max)
        self._bits = (self._bits << 1) | bit
        self._count += 1
        if self._count >= self.bit_count:
            if self.stop_bit:
                self._state = self.STOP_WAIT
            elif low >= self.guard_t * self.te:
                self._finish(low)  # guard already merged with this bit
            else:
                self._state = self.WAIT_END  # confirm the end on the next LOW
        else:
            self._state = self.HIGH_WAIT  # ready for the next bit's HIGH

    def _finish(self, trailing_low: float) -> None:
        data = self._bits
        te = int(round(self.te))
        self._bits = 0
        self._count = 0
        # the trailing LOW may already be the next frame's guard (merged)
        if trailing_low >= self.guard_t * self.te:
            self._state = self.HIGH_WAIT
        else:
            self._state = self.SYNC
        self._emit(self.make_result(data, te))


class BaseEncoder:
    """Shared helpers for the protocol encoders."""

    @staticmethod
    def _pwm_bits(data: int, nbits: int, te: int) -> List:
        """MSB-first PWM: '1' = HIGH 3T + LOW 1T, '0' = HIGH 1T + LOW 3T."""
        out = []
        for i in range(nbits - 1, -1, -1):
            if (data >> i) & 1:
                out.append((True, te * 3))
                out.append((False, te))
            else:
                out.append((True, te))
                out.append((False, te * 3))
        return out
