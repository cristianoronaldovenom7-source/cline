"""Small shared helpers: CC1101 frequency math, TX-range policing, console."""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# CC1101 frequency synthesizer math (firmware-exact, truncated integer math)
#
#   FREQ register value = freq_Hz * 0x10000 / 26_000_000   (truncated)
#   freq_Hz             = value * 26_000_000 / 0x10000
#
# Identical to the firmware's furi_hal_subghz frequency routines, so .sub
# files and our transmissions land on exactly the same channels.
# ---------------------------------------------------------------------------

_XTAL = 26_000_000  # CC1101 crystal


def frequency_to_registers(freq_hz: int):
    """Return the (FREQ2, FREQ1, FREQ0) triple for a frequency in Hz."""
    value = (int(freq_hz) * 0x10000) // _XTAL  # firmware-exact truncation
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def registers_to_frequency(f2: int, f1: int, f0: int) -> int:
    """Return the real frequency (Hz) encoded by a FREQ2/FREQ1/FREQ0 triple."""
    value = ((f2 & 0xFF) << 16) | ((f1 & 0xFF) << 8) | (f0 & 0xFF)
    return (value * _XTAL) // 0x10000


# ---------------------------------------------------------------------------
# TX range policing (same philosophy as the Flipper's region lock)
# ---------------------------------------------------------------------------

# frequencies a Pi may legally radiate with the default (EU-ish) profile
DEFAULT_TX_RANGES = [
    (300_000_000, 348_000_000),
    (387_000_000, 464_000_000),
    (779_000_000, 928_000_000),
]

# the firmware's extended range (281-361 / 378-481 / 749-962 MHz)
EXTENDED_RANGES = [
    (281_000_000, 361_000_000),
    (378_000_000, 481_000_000),
    (749_000_000, 962_000_000),
]


def is_tx_allowed(freq_hz: int, extended: bool = False) -> bool:
    """True if a frequency is inside an allowed transmit band."""
    freq_hz = int(freq_hz)
    ranges = EXTENDED_RANGES if extended else DEFAULT_TX_RANGES
    return any(lo <= freq_hz <= hi for lo, hi in ranges)


# Frequencies offered by the menu / `read` defaults (Hz, label)
COMMON_FREQUENCIES = [
    (300_000_000, "US remotes (300 MHz)"),
    (303_875_000, "US/ASIA (303.875)"),
    (304_250_000, "US/ASIA (304.25)"),
    (310_000_000, "US (310)"),
    (315_000_000, "US/JP (315)"),
    (345_000_000, "US (345)"),
    (390_000_000, "US/JP (390)"),
    (418_000_000, "EU (418)"),
    (433_420_000, "EU (433.42 HCS)"),
    (433_920_000, "EU/ASIA (433.92 common)"),
    (434_070_000, "EU (434.07)"),
    (434_420_000, "EU (434.42)"),
    (434_775_000, "AU/NZ (434.775)"),
    (868_350_000, "EU SRD (868.35)"),
    (915_000_000, "US ISM (915)"),
    (925_000_000, "US (925)"),
    (928_000_000, "US (928)"),
]


def format_freq(freq_hz: int) -> str:
    """433920000 -> '433.92 MHz' (trailing zeros trimmed)."""
    mhz = int(freq_hz) / 1_000_000.0
    text = f"{mhz:.3f}".rstrip("0").rstrip(".")
    return f"{text} MHz"


def reverse_key(data: int, nbits: int) -> int:
    """Bit-reverse the low `nbits` of `data` (some remotes send LSB-first)."""
    out = 0
    for _ in range(nbits):
        out = (out << 1) | (data & 1)
        data >>= 1
    return out


def pi_model() -> str:
    """'' on a PC, else the board name e.g. 'Raspberry Pi 5 Model B Rev 1.0'."""
    try:
        with open("/proc/device-tree/model", "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read().rstrip("\x00").strip()
    except OSError:
        return ""


def is_pi5() -> bool:
    return "Pi 5" in pi_model()


def clamp(value, lo, hi):
    return max(lo, min(hi, value))
