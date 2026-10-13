"""Shadow-clone rolling-counter mirror (persistent, per remote).

`signals/clone_state.json` remembers the highest counter seen per
(manufacturer, serial). It only ever moves forward (wrapping past 0xFFFF
counts as forward), re-syncs automatically on every capture, and `clone`
uses it to pre-compute future rolling codes that stay inside the receiver's
acceptance window indefinitely.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

_WRAP_THRESHOLD = 0x8000


def _is_forward(old: int, new: int) -> bool:
    """True when `new` is ahead of `old` (16-bit wrap aware)."""
    if new > old:
        return True
    # small numbers after big ones = the counter wrapped 0xFFFF -> 0x0000
    return (old - new) > _WRAP_THRESHOLD


class CloneState:
    """Persistent {manufacture: {serial: {cnt, btn, seen, ts}}} store."""

    def __init__(self, path: str):
        self.path = path
        self._state: Dict[str, Dict[str, Dict]] = {}
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._state = data
        except (OSError, ValueError):
            self._state = {}

    def _save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh, indent=2)
        os.replace(tmp, self.path)

    # -- API -----------------------------------------------------------------
    def _bucket(self, manufacture: str, serial: int) -> Dict:
        mf = str(manufacture or "Unknown")
        return self._state.setdefault(mf, {}).setdefault(
            f"{int(serial) & 0x0FFFFFFF:07X}", {})

    def observe(self, manufacture: str, serial: int, btn: int,
               cnt: int) -> int:
        """Record a captured frame; returns the (possibly unchanged) mirror."""
        bucket = self._bucket(manufacture, serial)
        cnt = int(cnt) & 0xFFFF
        if "cnt" in bucket and not _is_forward(bucket["cnt"], cnt):
            # stale/replayed frame — keep the newer knowledge
            bucket["seen"] = int(bucket.get("seen", 0)) + 1
            bucket["ts"] = time.time()
            self._save()
            return bucket["cnt"]
        bucket["cnt"] = cnt
        bucket["btn"] = int(btn or 0) & 0xF
        bucket["seen"] = int(bucket.get("seen", 0)) + 1
        bucket["ts"] = time.time()
        self._save()
        return cnt

    def advance(self, manufacture: str, serial: int, cnt: int) -> int:
        """Force the mirror forward (after generating clone codes)."""
        bucket = self._bucket(manufacture, serial)
        cnt = int(cnt) & 0xFFFF
        if "cnt" not in bucket or _is_forward(bucket["cnt"], cnt):
            bucket["cnt"] = cnt
        bucket["btn"] = bucket.get("btn", 0)
        bucket["seen"] = int(bucket.get("seen", 0))
        bucket["ts"] = time.time()
        self._save()
        return bucket["cnt"]

    def get(self, manufacture: str, serial: int) -> Optional[Dict]:
        return self._bucket(manufacture, serial) if (
            str(manufacture or "Unknown") in self._state
            and f"{int(serial) & 0x0FFFFFFF:07X}"
            in self._state[str(manufacture or "Unknown")]) else None
