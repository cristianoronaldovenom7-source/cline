"""KeeLoq manufacturer key store.

File format (assets/keeloq_keys.txt — one key per line):

    ManufacturerName:1122334455667788:simple
    OtherBrand:0011223344556677:normal
    BFT:0011223344556677:secure

Learning types: simple, normal, secure, magic_xor_type1, magic_serial_type1,
magic_serial_type2, magic_serial_type3, simple_jcm, jcm_gen2, erreka, pujol,
stagnoli, aerf, telcoma_hi, telcoma_lo, unknown. The exotic types currently
behave like `simple` until their derivations are ported; `simple` keys and the
demo key work fully. Community "mfkey" files from the original firmware are
drop-in compatible.
"""

from __future__ import annotations

from typing import Iterator, Optional

from . import keeloq_crypto as kq

SUPPORTED_TYPES = ("simple", "normal", "secure", "magic_xor_type1",
                   "magic_serial_type1", "magic_serial_type2",
                   "magic_serial_type3", "simple_jcm", "jcm_gen2", "erreka",
                   "pujol", "stagnoli", "aerf", "telcoma_hi", "telcoma_lo",
                   "unknown")


class KeystoreEntry:
    __slots__ = ("name", "key", "type")

    def __init__(self, name: str, key: int, type_: str = "simple"):
        self.name = name
        self.key = int(key) & 0xFFFFFFFFFFFFFFFF
        self.type = (type_ or "simple").strip().lower() or "simple"

    def __repr__(self) -> str:  # pragma: no cover
        return f"KeystoreEntry({self.name!r}, {self.key:016X}, {self.type})"


class Keystore:
    """Manufacturer-key registry (name -> 64-bit key + learning type)."""

    def __init__(self):
        self._entries = {}  # name -> KeystoreEntry (original casing)

    # -- container protocol ------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[KeystoreEntry]:
        return iter(self._entries.values())

    def __contains__(self, name) -> bool:
        return self.find(name) is not None

    # -- management ----------------------------------------------------------
    def add(self, name: str, key: int, type_: str = "simple") -> KeystoreEntry:
        entry = KeystoreEntry(name, key, type_)
        self._entries[name] = entry
        return entry

    def find(self, name) -> Optional[KeystoreEntry]:
        """Case-insensitive lookup; returns None when unknown."""
        if not name:
            return None
        name = str(name).strip()
        if name in self._entries:
            return self._entries[name]
        lowered = name.lower()
        for entry in self._entries.values():
            if entry.name.lower() == lowered:
                return entry
        return None

    # -- key derivation -------------------------------------------------------
    def man_key_for(self, entry, fix: int = 0, serial: int = 0,
                    seed: Optional[int] = None) -> int:
        """Derive the 64-bit hopping-code key for one remote."""
        if entry is None:
            raise ValueError("no keystore entry")
        ltype = getattr(entry, "type", "simple") or "simple"
        if ltype == "normal":
            return kq.normal_learning(int(serial) & 0x0FFFFFFF, entry.key)
        if ltype == "secure":
            return kq.secure_learning(int(fix) & 0xFFFFFFFF,
                                      int(seed or 0), entry.key)
        # simple (and the exotic types, pending their ports) use the raw key
        return entry.key

    # -- persistence ----------------------------------------------------------
    def load(self, path: str) -> int:
        """Load `Name:HEXKEY:type` lines; returns number of keys added."""
        added = 0
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                parts = line.split(":")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                try:
                    key = int(parts[1].strip(), 16)
                except ValueError:
                    continue
                type_ = parts[2].strip().lower() if len(parts) > 2 else "simple"
                if type_ not in SUPPORTED_TYPES:
                    type_ = "simple"
                self.add(name, key, type_)
                added += 1
        return added

    def save(self, path: str) -> None:
        lines = ["# KeeLoq manufacturer keys — Name:HEX64KEY:learning-type"]
        for entry in self._entries.values():
            lines.append(f"{entry.name}:{entry.key:016X}:{entry.type}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
