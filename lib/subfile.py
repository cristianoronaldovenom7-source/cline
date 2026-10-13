"""Flipper Zero `.sub` file reader/writer (decoded keys, RAW, custom presets).

Writes files a real Flipper reads, and reads files a real Flipper (or the
Private Unleashed signal packs) writes:

    Filetype: Flipper SubGhz Key File
    Version: 1
    Frequency: 433920000
    Preset: FuriHalSubGhzPresetOok650Async
    Protocol: KeeLoq (64bit)
    Bit: 64
    Key: 5A B5 09 2B E1 82 0C 5B
    Te: 400
    Manufacture: SomeBrand
    Seed: 12345678
    CounterMode: 2
    Repeat: 3

Internal canonical protocol names: "KeeLoq", "CAME", "Nice FLO", "Princeton",
"Holtek". On save, KeeLoq is written as "KeeLoq (64bit)" (Flipper style);
on load both spellings (and Flipper's historical "Holltek") are accepted.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .presets import (CUSTOM_PRESET_NAME, Preset, custom_preset_from_bytes,
                      preset_by_name)
from .util import format_freq

KEY_FILE = "Flipper SubGhz Key File"
RAW_FILE = "Flipper SubGhz RAW File"

# canonical name -> name written to the file
_WRITE_PROTOCOL = {
    "KeeLoq": "KeeLoq (64bit)",
}

# name in the file -> canonical name
_READ_PROTOCOL = {
    "KeeLoq (64bit)": "KeeLoq",
    "KeeLoq 64bit": "KeeLoq",
    "Holltek": "Holtek",
    "Nice Flo": "Nice FLO",
    "Princeton (example)": "Princeton",
}


class SubFile:
    """One sub-GHz signal — decoded key or RAW capture."""

    def __init__(self):
        self.filetype = KEY_FILE
        self.version = 1
        self.frequency = 433_920_000
        self.preset_name = "FuriHalSubGhzPresetOok650Async"
        self.protocol = ""
        self.bit = 0
        self.key = 0
        self.te = 0
        self.repeat = 3
        self.manufacture = ""
        self.seed: Optional[int] = None
        self.counter_mode: Optional[int] = None
        self.guard_time: Optional[int] = None
        self.raw_data: Optional[List[int]] = None
        self.custom_preset_bytes: Optional[List[int]] = None

    # -- classification -----------------------------------------------------
    @property
    def is_raw(self) -> bool:
        if self.raw_data:
            return True
        return "RAW" in (self.filetype or "")

    def preset(self) -> Preset:
        if (self.custom_preset_bytes
                and str(self.preset_name).endswith("Custom")):
            return custom_preset_from_bytes(self.custom_preset_bytes)
        return preset_by_name(self.preset_name)

    def preset_short(self) -> str:
        return self.preset().short

    # -- persistence -----------------------------------------------------------
    def save(self, path: str) -> None:
        lines = [
            f"Filetype: {self.filetype}",
            f"Version: {int(self.version) if self.version else 1}",
            f"Frequency: {int(self.frequency)}",
            f"Preset: {self.preset_name}",
        ]
        if (self.custom_preset_bytes
                and str(self.preset_name).endswith("Custom")):
            lines.append("Custom_Preset: " + " ".join(
                f"{b & 0xFF:02X}" for b in self.custom_preset_bytes))

        if self.is_raw:
            lines.append("RAW_Data: " + " ".join(str(int(d)) for d in self.raw_data))
        else:
            proto = _WRITE_PROTOCOL.get(self.protocol, self.protocol)
            lines.append(f"Protocol: {proto}")
            lines.append(f"Bit: {int(self.bit)}")
            lines.append(f"Key: {self._key_string()}")
            if self.te:
                lines.append(f"Te: {int(self.te)}")
            if self.guard_time is not None:
                lines.append(f"GuardTime: {int(self.guard_time)}")
            if self.manufacture:
                lines.append(f"Manufacture: {self.manufacture}")
            if self.seed is not None:
                lines.append(f"Seed: {self.seed:X}")
            if self.counter_mode is not None:
                lines.append(f"CounterMode: {int(self.counter_mode)}")
            lines.append(f"Repeat: {int(self.repeat) if self.repeat else 1}")
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")

    def _key_string(self) -> str:
        bit = int(self.bit) if self.bit else 64
        nbytes = (bit + 7) // 8
        value = int(self.key) << (nbytes * 8 - bit)  # right-justify in nbytes
        return " ".join(f"{(value >> (8 * i)) & 0xFF:02X}"
                       for i in range(nbytes - 1, -1, -1))

    @classmethod
    def load(cls, path: str) -> "SubFile":
        sub = cls()
        values = {}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                values[key.strip().lower()] = value.strip()
        if not values:
            raise ValueError(f"{path}: not a Flipper .sub file")

        filetype = values.get("filetype", KEY_FILE)
        sub.filetype = filetype if "RAW" in filetype else KEY_FILE
        sub.version = int(values.get("version", 1) or 1)
        sub.frequency = int(values.get("frequency", 433920000) or 433920000)
        sub.preset_name = values.get("preset", "FuriHalSubGhzPresetOok650Async")

        if "custom_preset" in values:
            sub.custom_preset_bytes = [int(tok, 16) for tok in
                                       values["custom_preset"].split()]

        if "raw_data" in values:
            sub.filetype = RAW_FILE
            sub.raw_data = [int(tok) for tok in values["raw_data"].split()]
            sub.repeat = int(values.get("repeat", 1) or 1)
            return sub

        proto = values.get("protocol", "")
        sub.protocol = _READ_PROTOCOL.get(proto, proto)
        sub.bit = int(values.get("bit", 0) or 0)
        if "key" in values:
            sub.key = cls._parse_key(values["key"], sub.bit)
        sub.te = int(values.get("te", 0) or 0)
        if "guardtime" in values and values["guardtime"]:
            sub.guard_time = int(values["guardtime"])
        else:
            sub.guard_time = None
        sub.manufacture = values.get("manufacture", "")
        if "seed" in values and values["seed"]:
            sub.seed = int(values["seed"], 16)
        if "countermode" in values and values["countermode"]:
            sub.counter_mode = int(values["countermode"])
        sub.repeat = int(values.get("repeat", 3) or 3)
        return sub

    @staticmethod
    def _parse_key(text: str, bit: int) -> int:
        tokens = text.replace(",", " ").split()
        if not tokens:
            return 0
        if len(tokens) == 1 and len(tokens[0]) % 2:  # odd hex nibble string
            value = int(tokens[0], 16)
        else:
            value = int("".join(tok.zfill(2) for tok in tokens), 16)
        if bit:
            nbytes = (bit + 7) // 8
            pad = nbytes * 8 - bit
            if pad > 0:
                value >>= pad
        return value

    # -- presentation -----------------------------------------------------------
    def info_lines(self) -> List[str]:
        if self.is_raw:
            total_ms = sum(abs(int(d)) for d in self.raw_data) / 1000.0
            return [
                f"RAW capture @ {format_freq(self.frequency)} "
                f"preset {self.preset_short()}",
                f"samples: {len(self.raw_data)}  ({total_ms:.1f} ms)",
                f"repeat: {self.repeat}",
            ]
        lines = [
            f"{self.protocol or '?'} {self.bit}bit @ {format_freq(self.frequency)} "
            f"preset {self.preset_short()}",
            f"Key: {self.key:0{max(1, (self.bit + 3) // 4)}X}",
        ]
        if self.te:
            lines.append(f"Te: {self.te}")
        if self.guard_time is not None:
            lines.append(f"GuardTime: {self.guard_time}")
        if self.manufacture:
            lines.append(f"Manufacture: {self.manufacture}")
        if self.seed is not None:
            lines.append(f"Seed: 0x{self.seed:08X}")
        if self.counter_mode is not None:
            lines.append(f"CounterMode: {self.counter_mode}")
        lines.append(f"Repeat: {self.repeat}")
        return lines


def raw_durations_to_levels(durations) -> List:
    """[400, -800, ...] -> [(True, 400), (False, 800), ...] (µs)."""
    return [((int(d) > 0), abs(int(d))) for d in durations]


def levels_to_raw_durations(levels) -> List[int]:
    """[(True, 400), ...] -> [400, -800, ...] (signed Flipper RAW format)."""
    return [int(d) if lvl else -int(d) for lvl, d in levels]
