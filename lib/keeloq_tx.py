"""KeeLoq transmit helpers: .sub -> re-encrypted frames, clones, sweeps."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import keeloq_crypto as kq
from .keystore import Keystore
from .protocols.keeloq import (TE, build_upload, counter_chain,
                                frame_key, next_counter)
from .subfile import SubFile


class KeeLoqInfo:
    """Everything we can learn from one captured KeeLoq .sub."""

    __slots__ = ("fix", "hop", "serial", "btn", "cnt", "manufacture",
                 "matched", "man_key", "te")

    def __init__(self, fix: int, hop: int, serial: int, btn: int,
                 cnt: Optional[int], manufacture: str, matched: bool,
                 man_key: Optional[int], te: int):
        self.fix = fix
        self.hop = hop
        self.serial = serial
        self.btn = btn
        self.cnt = cnt
        self.manufacture = manufacture
        self.matched = matched
        self.man_key = man_key
        self.te = te


def analyze(sub: SubFile, keystore: Optional[Keystore] = None) -> KeeLoqInfo:
    """Decode a KeeLoq .sub: split FIX/HOP, identify manufacturer, counter."""
    key = int(sub.key) & 0xFFFFFFFFFFFFFFFF
    fix, hop = kq.split_frame(key)
    btn, serial = kq.parse_fix(fix)
    te = int(sub.te or TE)
    manufacture = (sub.manufacture or "").strip() or "Unknown"
    matched = False
    man_key: Optional[int] = None
    cnt: Optional[int] = None

    if keystore is not None and manufacture != "Unknown":
        entry = keystore.find(manufacture)
        if entry is not None:
            ltype = getattr(entry, "type", "simple")
            if ltype == "secure" and sub.seed is not None:
                man_key = keystore.man_key_for(entry, fix, serial, sub.seed)
            elif ltype == "secure":
                man_key = None  # seed required but not stored
            else:
                man_key = keystore.man_key_for(entry, fix, serial, None)
            if man_key is not None:
                dec = kq.keeloq_decrypt(hop, man_key)
                d_btn, d_serial10, d_cnt = kq.parse_decrypt(dec)
                if d_btn == btn and d_serial10 == (serial & 0x3FF):
                    matched = True
                    cnt = d_cnt
                else:
                    man_key = None
    return KeeLoqInfo(fix, hop, serial, btn, cnt, manufacture, matched,
                      man_key, te)


def _clone_sub(sub: SubFile, key: int, counter_mode) -> SubFile:
    clone = SubFile()
    clone.filetype = sub.filetype
    clone.version = sub.version
    clone.frequency = sub.frequency
    clone.preset_name = sub.preset_name
    clone.protocol = sub.protocol
    clone.bit = sub.bit
    clone.key = key
    clone.te = sub.te
    clone.repeat = sub.repeat
    clone.manufacture = sub.manufacture
    clone.seed = sub.seed
    clone.counter_mode = counter_mode
    clone.guard_time = sub.guard_time
    clone.custom_preset_bytes = (list(sub.custom_preset_bytes)
                                 if sub.custom_preset_bytes else None)
    return clone


def next_code_upload(sub: SubFile, keystore: Optional[Keystore] = None,
                     counter_mode: Optional[int] = None,
                     repeat: Optional[int] = None) -> Tuple[List, int]:
    """Build the next transmitted frame for a KeeLoq .sub.

    With a manufacturer key the hopping code is re-encrypted with the counter
    advanced by the file's CounterMode (default mode 2). Without one, the
    captured frame is replayed 1:1 — like sending it with Manufacture Unknown.
    """
    info = analyze(sub, keystore)
    rep = int(repeat if repeat is not None else
              (sub.repeat if sub.repeat else 3))
    if not info.matched:
        return build_upload(int(sub.key), info.te), rep
    mode = int(counter_mode if counter_mode is not None
               else (sub.counter_mode if sub.counter_mode is not None else 2))
    cnt = next_counter(info.cnt, mode)
    key = frame_key(info.man_key, info.serial, info.btn, cnt)
    return build_upload(key, info.te), rep


def clone_next_subs(sub: SubFile, keystore: Optional[Keystore] = None,
                    steps: int = 4, counter_mode: Optional[int] = None,
                    start_cnt: Optional[int] = None
                    ) -> Tuple[List[SubFile], List[int]]:
    """Pre-compute the next `steps` rolling codes as ready-to-send .subs."""
    info = analyze(sub, keystore)
    mode = int(counter_mode if counter_mode is not None
               else (sub.counter_mode if sub.counter_mode is not None else 2))

    if not info.matched:
        # unknown manufacturer — clones replay the captured hop unchanged
        clones = [_clone_sub(sub, int(sub.key), mode) for _ in range(steps)]
        return clones, []

    base = info.cnt if start_cnt is None else int(start_cnt) & 0xFFFF
    counters = list(counter_chain(base, mode, steps))
    clones = []
    for cnt in counters:
        key = frame_key(info.man_key, info.serial, info.btn, cnt)
        clones.append(_clone_sub(sub, key, mode))
    return clones, counters


def predicted_counters(sub: SubFile, keystore: Optional[Keystore] = None,
                        count: int = 4,
                        counter_mode: Optional[int] = None
                        ) -> Tuple[str, List[int]]:
    """(manufacture, [next counters]) for a captured KeeLoq .sub."""
    info = analyze(sub, keystore)
    if not info.matched:
        return (info.manufacture or "Unknown"), []
    mode = int(counter_mode if counter_mode is not None
               else (sub.counter_mode if sub.counter_mode is not None else 2))
    return info.manufacture, list(counter_chain(info.cnt, mode, count))
