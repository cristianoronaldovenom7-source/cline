"""KeeLoq 64-bit rolling-code protocol (HCS-style, 66-bit air frames).

Air frame (all timings in te, default 400 µs):

    [header LOW 10T] [66 bits] [next header ...]

bit '1' = HIGH 1T + LOW 2T      bit '0' = HIGH 2T + LOW 1T

Bit order (MSB first): HOP(32) then FIX(32) then 2 VLOW/status bits. The
decoder fires on every complete frame (a real HCS press repeats ~10-25 frames).

`next_counter`/`counter_chain` implement the firmware's rolling-counter
manipulation modes 0-7 (mode 2 is the classic +0x3333 desync attack).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .. import keeloq_crypto as kq
from ..keystore import Keystore
from .base import BaseDecoder, DecoderResult

TE = 400
FRAME_BITS = 66          # HOP(32) + FIX(32) + VLOW(2)
HEADER_T = 10             # header LOW length in te
GUARD_T = 8               # min LOW (in te) that (re)synchronizes a frame

# rolling-counter modes ----------------------------------------------------
_OFEX = {0x0000: 0x0001, 0x0001: 0xFFFE, 0xFFFE: 0xFFFF, 0xFFFF: 0x0000}
_MODE3 = {0x8006: 0x8007, 0x8007: 0x0006, 0x0006: 0x0007, 0x0007: 0x8006}
_MODE4 = {0x807B: 0x807C, 0x807C: 0x007B, 0x007B: 0x007C, 0x007C: 0x807B}


def next_counter(cnt: int, mode: int = 0, counter_mult: int = 1) -> int:
    """The firmware's counter modes 0-7 (README table).

    mode 0 standard +counter_mult (mult -0x7FFFFFFF = OFEX pattern)
    mode 1 OFEX 0000/0001/FFFE/FFFF
    mode 2 +0x3333 jump (wraps to 0x0000 past 0xFFFF)
    mode 3 0x8006/0x8007/0x0006/0x0007
    mode 4 0x807B/0x807C/0x007B/0x007C
    mode 5 0x0000/0xFFFF toggle
    mode 6 freeze
    mode 7 insane burst (0 / original / +1 / +0x3333 chain)
    """
    cnt &= 0xFFFF
    if mode == 0:
        if counter_mult == -0x7FFFFFFF:
            return _OFEX.get(cnt, (cnt + 1) & 0xFFFF)
        return (cnt + counter_mult) & 0xFFFF
    if mode == 1:
        return _OFEX.get(cnt, (cnt + 1) & 0xFFFF)
    if mode == 2:
        nxt = cnt + 0x3333
        return 0x0000 if nxt > 0xFFFF else nxt
    if mode == 3:
        return _MODE3.get(cnt, (cnt + 1) & 0xFFFF)
    if mode == 4:
        return _MODE4.get(cnt, (cnt + 1) & 0xFFFF)
    if mode == 5:
        if cnt == 0x0000:
            return 0xFFFF
        if cnt == 0xFFFF:
            return 0x0000
        return (cnt + 1) & 0xFFFF
    if mode == 6:
        return cnt
    if mode == 7:
        if cnt == 0x0000:
            return 0x0001
        nxt = cnt + 0x3333
        return 0x0000 if nxt > 0xFFFF else nxt
    raise ValueError(f"unknown counter mode {mode} (0-7)")


def counter_chain(start: int, mode: int = 0, count: int = 1,
                 counter_mult: int = 1):
    """Yield `count` successive counters from `start` using a mode.

    Mode 7 yields the firmware's 7-frame insane burst:
    0 / original / +1 / +0x3333 / +0x6666 / +0x9999 / +0xCCCC (cyclically).
    """
    count = max(0, int(count))
    if mode == 7:
        base = start & 0xFFFF
        pattern = [0x0000, base, (base + 1) & 0xFFFF, (base + 0x3333) & 0xFFFF,
                   (base + 0x6666) & 0xFFFF, (base + 0x9999) & 0xFFFF,
                   (base + 0xCCCC) & 0xFFFF]
        for i in range(count):
            yield pattern[i % len(pattern)]
        return
    cnt = start & 0xFFFF
    for _ in range(count):
        cnt = next_counter(cnt, mode, counter_mult)
        yield cnt


# ---------------------------------------------------------------------------
# air-frame helpers
# ---------------------------------------------------------------------------

def build_upload(key: int, te: int = TE) -> List:
    """64-bit key (FIX<<32|HOP) -> level/duration wave (single frame)."""
    te = int(te) if te else TE
    fix, hop = kq.split_frame(key)
    out: List = [(False, te * HEADER_T)]

    def add(bit: int) -> None:
        if bit:
            out.append((True, te))
            out.append((False, te * 2))
        else:
            out.append((True, te * 2))
            out.append((False, te))

    for i in range(31, -1, -1):  # HOP first on air, MSB first
        add((hop >> i) & 1)
    for i in range(31, -1, -1):  # then FIX (serial + button)
        add((fix >> i) & 1)
    add(0)  # 2 trailing status/VLOW bits
    add(0)
    return out


def frame_key(man_key: int, serial: int, btn: int, cnt: int) -> int:
    """Re-encrypt a hopping code for a known manufacturer key + counter."""
    decrypted = kq.build_decrypt(btn, serial, cnt)
    hop = kq.keeloq_encrypt(decrypted, man_key)
    return kq.join_frame(kq.build_fix(serial, btn), hop)


# ---------------------------------------------------------------------------
# decoder
# ---------------------------------------------------------------------------

class KeeLoqDecoder(BaseDecoder):
    """Live KeeLoq frame decoder + manufacturer identification."""

    two_frame_rule = False  # every complete frame is a valid observation

    SYNC, HIGH_WAIT, LOW_WAIT = range(3)

    def __init__(self, keystore: Optional[Keystore] = None,
                 te: float = TE):
        super().__init__()
        self.keystore = keystore
        self.te = float(te)
        self.te_min, self.te_max = 250.0, 650.0
        self._state = self.SYNC
        self._bits = 0
        self._count = 0
        self._h = 0.0

    # -- identification -------------------------------------------------------
    def _identify(self, fix: int, hop: int):
        """Try every keystore key; return (manufacture, cnt) or Unknown."""
        btn, serial = kq.parse_fix(fix)
        if self.keystore is not None:
            for entry in self.keystore:
                ltype = getattr(entry, "type", "simple")
                if ltype == "secure":
                    continue  # needs the transmitted Seed, see keeloq lab
                man_key = self.keystore.man_key_for(entry, fix, serial, None)
                dec = kq.keeloq_decrypt(hop, man_key)
                d_btn, d_serial10, d_cnt = kq.parse_decrypt(dec)
                if d_btn == btn and d_serial10 == (serial & 0x3FF):
                    return entry.name, d_cnt
        return "Unknown", None

    def make_result_from_data(self, key: int) -> DecoderResult:
        """Analyze a stored 64-bit key (offline — no radio needed)."""
        fix, hop = kq.split_frame(key)
        btn, serial = kq.parse_fix(fix)
        manufacture, cnt = self._identify(fix, hop)
        return DecoderResult("KeeLoq", int(key), 64, te=int(round(self.te)),
                             manufacture_name=manufacture, serial=serial,
                             btn=btn, cnt=cnt)

    # -- state machine ----------------------------------------------------------
    def feed(self, level: bool, duration: int) -> None:
        d = int(duration)
        if d <= 0:
            return
        state = self._state

        if state == self.SYNC:
            if (not level) and d >= GUARD_T * self.te:
                self._state = self.HIGH_WAIT

        elif state == self.HIGH_WAIT:
            if level:
                self._h = float(d)
                self._state = self.LOW_WAIT
            elif d >= GUARD_T * self.te:
                pass  # merged header, keep waiting
            else:
                self._state = self.SYNC

        elif state == self.LOW_WAIT:
            if level:
                self._state = self.SYNC
                return
            h = self._h
            te = self.te
            if d >= GUARD_T * te:
                # last bit's LOW merged with the next frame's header —
                # classify by the HIGH alone (1T -> '1', 2T -> '0')
                if abs(h - te) < 0.45 * te:
                    bit, short = 1, h
                elif abs(h - 2 * te) < 0.9 * te:
                    bit, short = 0, te
                else:
                    self._state = self.SYNC
                    return
            elif abs(h - te) < 0.45 * te and abs(d - 2 * te) < 0.9 * te:
                bit, short = 1, h
            elif abs(h - 2 * te) < 0.9 * te and abs(d - te) < 0.45 * te:
                bit, short = 0, d
            else:
                self._state = self.SYNC
                return
            if not (self.te_min <= short <= self.te_max):
                self._state = self.SYNC
                return
            self.te = min(max(0.9 * te + 0.1 * short, self.te_min), self.te_max)
            self._bits = (self._bits << 1) | bit
            self._count += 1
            if self._count >= FRAME_BITS:
                self._finish(d)
            else:
                self._state = self.HIGH_WAIT  # ready for the next bit's HIGH

    def _finish(self, trailing_low: float) -> None:
        bits = self._bits
        hop = (bits >> 34) & 0xFFFFFFFF          # first 32 bits
        fix = (bits >> 2) & 0xFFFFFFFF           # next 32 bits
        # (2 trailing VLOW bits dropped)
        te = int(round(self.te))
        self._bits = 0
        self._count = 0
        if trailing_low >= GUARD_T * self.te:
            self._state = self.HIGH_WAIT  # merged into next header
        else:
            self._state = self.SYNC
        if fix == 0 and hop == 0:
            return  # all-zero frame: idle carrier, not a signal
        btn, serial = kq.parse_fix(fix)
        manufacture, cnt = self._identify(fix, hop)
        result = DecoderResult("KeeLoq",
                              kq.join_frame(fix, hop), 64, te=te,
                              manufacture_name=manufacture, serial=serial,
                              btn=btn, cnt=cnt)
        self._emit(result)


# ---------------------------------------------------------------------------
# encoder
# ---------------------------------------------------------------------------

class KeeLoqEncoder:
    """Builds re-encrypted KeeLoq frames with the firmware's counter modes.

    `set_frame()` records an observation (serial/button/counter as seen on a
    real remote); every `get_upload()` then advances the counter with the
    configured mode *before* building the frame — exactly like the firmware
    replaying a captured key.
    """

    def __init__(self, keystore: Optional[Keystore] = None, te: int = TE,
                 repeat: int = 3):
        self.keystore = keystore
        self.te = int(te) if te else TE
        self.repeat = int(repeat)
        self.serial = 0
        self.btn = 0
        self.cnt = 0
        self.manufacture_name = "Unknown"
        self.counter_mode = 0
        self.seed = None
        self.data = 0

    def set_frame(self, serial: int, btn: int, cnt: int,
                 manufacture_name: str, counter_mode: int = 0,
                 seed: Optional[int] = None) -> None:
        self.serial = int(serial) & 0x0FFFFFFF
        self.btn = int(btn) & 0xF
        self.cnt = int(cnt) & 0xFFFF
        self.manufacture_name = manufacture_name or "Unknown"
        self.counter_mode = int(counter_mode or 0)
        self.seed = seed

    def _man_key(self) -> Optional[int]:
        if self.keystore is None:
            return None
        entry = self.keystore.find(self.manufacture_name)
        if entry is None:
            return None
        if getattr(entry, "type", "simple") == "secure":
            return self.keystore.man_key_for(
                entry, kq.build_fix(self.serial, self.btn), self.serial,
                self.seed)
        return self.keystore.man_key_for(
            entry, kq.build_fix(self.serial, self.btn), self.serial, None)

    def get_upload(self) -> Tuple[List, int]:
        """Advance the counter (counter mode) and build one frame."""
        self.cnt = next_counter(self.cnt, self.counter_mode)
        man_key = self._man_key()
        if man_key is None:
            raise ValueError(
                f"manufacturer {self.manufacture_name!r} not in keystore — "
                "add its key to assets/keeloq_keys.txt")
        self.data = frame_key(man_key, self.serial, self.btn, self.cnt)
        return build_upload(self.data, self.te), self.repeat
