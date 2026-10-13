"""KeeLoq crypto — a 1:1 port of the firmware's `keeloq_common.c`.

* 32-bit NLFSR block cipher, 528 rounds, NLF 0x3A5C742E
* simple / normal / secure manufacturer-key learning
* frame helpers (FIX/HOP split, parse, build)
* rolling-counter modes 0-7 live in lib/protocols/keeloq.py (next_counter)

Frame layout on air (66 bits, MSB first):

    HOP(32)  FIX(32 = serial28|btn4)  VLOW(2)

The stored 64-bit "Key" of a Flipper .sub file is  FIX<<32 | HOP.
"""

from __future__ import annotations

from typing import Tuple

NLF = 0x3A5C742E
ROUNDS = 528


# ---------------------------------------------------------------------------
# the cipher
# ---------------------------------------------------------------------------

def _nlf_index(x: int) -> int:
    """NLF tap bits of the shift register: 31, 26, 20, 15, 10, 8."""
    return ((((x >> 31) & 1) << 5)
            | (((x >> 26) & 1) << 4)
            | (((x >> 20) & 1) << 3)
            | (((x >> 15) & 1) << 2)
            | (((x >> 10) & 1) << 1)
            | ((x >> 8) & 1))


def keeloq_encrypt(data: int, key: int) -> int:
    """Encrypt a 32-bit block with a 64-bit manufacturer key."""
    x = data & 0xFFFFFFFF
    for i in range(ROUNDS):
        key_bit = (int(key) >> (i & 0x3F)) & 1
        feedback = (((NLF >> _nlf_index(x)) & 1)
                   ^ (x & 1)
                   ^ ((x >> 16) & 1)
                   ^ key_bit)
        x = (x >> 1) | (feedback << 31)
    return x & 0xFFFFFFFF


def keeloq_decrypt(data: int, key: int) -> int:
    """Decrypt a 32-bit block (inverse NLFSR rounds, key bits unwound)."""
    x = data & 0xFFFFFFFF
    for i in range(ROUNDS - 1, -1, -1):
        msb = (x >> 31) & 1                    # the feedback bit that was inserted
        rest = x & 0x7FFFFFFF                  # previous state bits 1..31
        key_bit = (int(key) >> (i & 0x3F)) & 1
        # previous state's bit 0 = msb ^ NLF(prev) ^ prev[16] ^ key bit;
        # prev bits 31,26,20,15,10,8 == rest bits 30,25,19,14,9,7
        idx = ((((rest >> 30) & 1) << 5)
               | (((rest >> 25) & 1) << 4)
               | (((rest >> 19) & 1) << 3)
               | (((rest >> 14) & 1) << 2)
               | (((rest >> 9) & 1) << 1)
               | ((rest >> 7) & 1))
        nlf = (NLF >> idx) & 1
        x0 = msb ^ nlf ^ ((rest >> 15) & 1) ^ key_bit
        x = ((rest << 1) | x0) & 0xFFFFFFFF
    return x & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# learning (how a remote derives its hop key from the manufacturer key)
# ---------------------------------------------------------------------------

def simple_learning(key: int) -> int:
    """Simple learning: hop key == manufacturer key."""
    return int(key) & 0xFFFFFFFFFFFFFFFF


def normal_learning(seed: int, key: int) -> int:
    """Normal learning (seed = serial number of the remote)."""
    key = int(key)
    hi = keeloq_encrypt(int(seed) & 0xFFFFFFFF, key & 0xFFFFFFFF)
    lo = keeloq_decrypt(int(seed) & 0xFFFFFFFF, (key >> 32) & 0xFFFFFFFF)
    return ((hi & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


def secure_learning(fix: int, seed: int, key: int) -> int:
    """Secure learning (uses both the fix word and the transmitted seed)."""
    key = int(key)
    hi = keeloq_encrypt(int(seed) & 0xFFFFFFFF, key & 0xFFFFFFFF)
    lo = keeloq_decrypt(int(fix) & 0xFFFFFFFF, (key >> 32) & 0xFFFFFFFF)
    return ((hi & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# frame helpers
# ---------------------------------------------------------------------------

def split_frame(frame: int) -> Tuple[int, int]:
    """64-bit frame -> (FIX, HOP)."""
    frame = int(frame) & 0xFFFFFFFFFFFFFFFF
    return (frame >> 32) & 0xFFFFFFFF, frame & 0xFFFFFFFF


def join_frame(fix: int, hop: int) -> int:
    return (((int(fix) & 0xFFFFFFFF) << 32)
            | (int(hop) & 0xFFFFFFFF))


def parse_fix(fix: int) -> Tuple[int, int]:
    """FIX word -> (button, serial28)."""
    fix = int(fix) & 0xFFFFFFFF
    return fix & 0xF, (fix >> 4) & 0x0FFFFFFF


def build_fix(serial: int, btn: int) -> int:
    return (((int(serial) & 0x0FFFFFFF) << 4) | (int(btn) & 0xF)) & 0xFFFFFFFF


def parse_decrypt(decrypted: int) -> Tuple[int, int, int]:
    """Decrypted HOP word -> (button, serial10/discriminator, counter16)."""
    dec = int(decrypted) & 0xFFFFFFFF
    return (dec >> 28) & 0xF, (dec >> 16) & 0x3FF, dec & 0xFFFF


def build_decrypt(btn: int, serial: int, cnt: int) -> int:
    """Inverse of parse_decrypt (button, discriminator, counter)."""
    return ((((int(btn) & 0xF) << 28)
             | ((int(serial) & 0x3FF) << 16)
             | (int(cnt) & 0xFFFF)) & 0xFFFFFFFF)
