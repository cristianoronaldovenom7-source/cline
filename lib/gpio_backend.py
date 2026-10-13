"""GPIO timing backends — the Pi-model-dependent part of the port.

The Flipper drives sub-GHz frames with a Cortex-M timer + DMA. On a Pi we
need µs-timed level sequences on GDO0; the right way to do that depends on
the board:

  * Pi 3 / Pi 4  -> `pigpio` (pigpiod DMA waves; the most precise) or lgpio
  * Pi 5        -> `lgpio` (RP1 gpiochip, kernel `tx_wave` support)
  * any PC      -> `MockBackend` (demo mode)

`detect_backend()` picks the best available backend automatically:

    prefer pigpiod on Pi 3/4 (DMA-timed TX waves, µs-accurate),
    fall back to lgpio (works everywhere incl. Pi 5),
    finally fall back to the mock so the whole stack still runs.

Every backend exposes:

    poll_edges() -> [(level, duration_us), ...]   samples of the RX stream
    wave_send(gpio, [(level, duration_us), ...])   transmit one frame
    is_mock                                       demo-mode flag
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from typing import List, Optional, Tuple

from .util import is_pi5

# (level, duration_us) pairs make up a wave / an RX sample batch
LevelDuration = Tuple[bool, int]


class GpioBackend:
    """Interface shared by all backends."""

    name = "base"
    is_mock = False

    def start_input(self, gpio: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop_input(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def poll_edges(self) -> List[LevelDuration]:  # pragma: no cover
        raise NotImplementedError

    def wave_send(self, gpio: int, levels) -> None:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# mock (demo mode / tests / no Pi)
# ---------------------------------------------------------------------------

class MockBackend(GpioBackend):
    """Virtual GPIO: feeds recorded levels to RxEngine, logs transmitted waves."""

    name = "mock"
    is_mock = True

    def __init__(self):
        self.sent_waves = []  # every transmitted wave, for loopback testing
        self._events = deque()
        self._lock = threading.Lock()
        self._clock = 0  # virtual µs clock

    def start_input(self, gpio: int) -> None:
        pass

    def stop_input(self) -> None:
        pass

    def feed_levels(self, gpio: int, levels):
        """Queue a (level, duration) stream as if it arrived over the air."""
        with self._lock:
            for level, duration in levels:
                self._events.append((bool(level), int(duration)))
                self._clock += int(duration)

    def poll_edges(self) -> List[LevelDuration]:
        with self._lock:
            batch = list(self._events)
            self._events.clear()
        return batch

    def wave_send(self, gpio: int, levels) -> int:
        self.sent_waves.append([(bool(level), int(duration))
                                for level, duration in levels])
        return 0

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
        self.sent_waves.clear()

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# lgpio (Pi 3/4/5 — the universal one; required on Pi 5)
# ---------------------------------------------------------------------------

class LgpioBackend(GpioBackend):
    """lgpio backend: kernel edge timestamps for RX, tx_wave for TX.

    Works on Pi 3/4 and Pi 5 (RP1). If the installed lgpio is too old for
    `tx_wave`, transmission falls back to a busy-wait bit-bang loop.
    """

    name = "lgpio"

    def __init__(self, chip: int = 0, gpios=()):
        import lgpio  # lazy import

        self._lgpio = lgpio
        self.chip = chip
        self._handle = lgpio.gpiochip_open(chip)
        self._claimed_out: List[int] = []
        self._claimed_alert: List[int] = []
        self._cb = None
        self._events = deque()
        self._lock = threading.Lock()
        self._last_ts = None
        self._last_level = None

    # -- RX ---------------------------------------------------------------
    def start_input(self, gpio: int) -> None:
        lgpio = self._lgpio
        if gpio not in self._claimed_alert:
            lgpio.gpio_claim_alert(self._handle, gpio, lgpio.BOTH_EDGES)
            self._claimed_alert.append(gpio)
        self._cb = lgpio.callback(self._handle, gpio, lgpio.BOTH_EDGES,
                                  self._on_edge)
        self._last_ts = None
        self._last_level = None

    def _on_edge(self, chip, gpio, level, timestamp):
        # lgpio: level is the NEW level, timestamp in seconds (float)
        try:
            with self._lock:
                if self._last_ts is not None:
                    duration = int(round((timestamp - self._last_ts) * 1e6))
                    prev = not bool(level)  # the line held the opposite level
                    self._events.append((prev, duration))
                self._last_ts = timestamp
                self._last_level = bool(level)
        except Exception:  # pragma: no cover
            pass

    def poll_edges(self) -> List[LevelDuration]:
        with self._lock:
            batch = list(self._events)
            self._events.clear()
        return batch

    def stop_input(self) -> None:
        if self._cb is not None:
            try:
                self._cb.cancel()
            except Exception:  # pragma: no cover
                pass
            self._cb = None
        self._last_ts = None

    # -- TX ---------------------------------------------------------------
    def wave_send(self, gpio: int, levels) -> int:
        lgpio = self._lgpio
        if gpio not in self._claimed_out and gpio not in self._claimed_alert:
            lgpio.gpio_claim_output(self._handle, gpio, 0)
            self._claimed_out.append(gpio)

        if hasattr(lgpio, "tx_wave"):
            pulses = []
            mask = 1 << gpio
            for level, duration in levels:
                duration = int(duration)
                if duration <= 0:
                    continue
                if level:
                    pulses.append([duration, mask, 0])
                else:
                    pulses.append([duration, 0, mask])
            try:
                lgpio.tx_wave(self._handle, pulses)
                lgpio.gpio_write(self._handle, gpio, 0)
                return 0
            except TypeError:  # pragma: no cover - older lgpio signature
                pass
            except Exception:  # pragma: no cover
                raise
        # fallback: busy-wait software wave (works, ~10-50 µs jitter)
        for level, duration in levels:
            lgpio.gpio_write(self._handle, gpio, 1 if level else 0)
            self._busy_wait_us(int(duration))
        lgpio.gpio_write(self._handle, gpio, 0)
        return 0

    @staticmethod
    def _busy_wait_us(duration: int):
        end = time.perf_counter() + duration / 1_000_000.0
        while time.perf_counter() < end:
            pass

    def close(self) -> None:
        try:
            self.stop_input()
        except Exception:  # pragma: no cover
            pass
        try:
            self._lgpio.gpiochip_close(self._handle)
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# pigpio (Pi 3/4 — DMA wave timing, needs the pigpiod daemon)
# ---------------------------------------------------------------------------

class PigpioBackend(GpioBackend):
    """pigpio backend (Pi 3/4 only — pigpiod has no Pi 5 support).

    RX: pigpio alerts with µs timestamps. TX: hardware DMA waves.
    """

    name = "pigpio"

    def __init__(self, host="localhost", port=8888):
        import pigpio  # lazy import

        self._pigpio = pigpio
        self._pi = pigpio.pi(host, port)
        if self._pi is None or not self._pi.connected:
            raise ConnectionError("pigpiod not reachable on %s:%s" % (host, port))
        self._cb = None
        self._events = deque()
        self._lock = threading.Lock()
        self._last_tick = None

    # -- RX ---------------------------------------------------------------
    def start_input(self, gpio: int) -> None:
        pigpio = self._pigpio
        self._pi.set_mode(gpio, pigpio.INPUT)
        self._cb = self._pi.callback(gpio, pigpio.EITHER_EDGE, self._on_edge)
        self._last_tick = None

    def _on_edge(self, gpio, level, tick):
        # pigpio: level = new level, tick = 32-bit µs counter
        try:
            with self._lock:
                if self._last_tick is not None:
                    duration = (tick - self._last_tick) & 0xFFFFFFFF
                    prev = not bool(level)
                    self._events.append((prev, duration))
                self._last_tick = tick
        except Exception:  # pragma: no cover
            pass

    def poll_edges(self) -> List[LevelDuration]:
        with self._lock:
            batch = list(self._events)
            self._events.clear()
        return batch

    def stop_input(self) -> None:
        if self._cb is not None:
            try:
                self._cb.cancel()
            except Exception:  # pragma: no cover
                pass
            self._cb = None
        self._last_tick = None

    # -- TX ---------------------------------------------------------------
    def wave_send(self, gpio: int, levels) -> int:
        pigpio = self._pigpio
        self._pi.set_mode(gpio, pigpio.OUTPUT)
        self._pi.wave_clear()
        pulses = []
        mask = 1 << gpio
        for level, duration in levels:
            duration = int(duration)
            if duration <= 0:
                continue
            if level:
                pulses.append(pigpio.pulse(mask, 0, duration))
            else:
                pulses.append(pigpio.pulse(0, mask, duration))
        self._pi.wave_add_generic(pulses)
        wave_id = self._pi.wave_create()
        try:
            self._pi.wave_send_once(wave_id)
            while self._pi.wave_tx_busy():
                time.sleep(0.001)
        finally:
            self._pi.wave_delete(wave_id)
        self._pi.write(gpio, 0)
        return 0

    def close(self) -> None:
        try:
            self.stop_input()
        except Exception:  # pragma: no cover
            pass
        try:
            self._pi.stop()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

def _pigpiod_running(timeout: float = 0.3) -> bool:
    """Quick socket probe so we never hang on a missing daemon."""
    try:
        sock = socket.create_connection(("127.0.0.1", 8888), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _open_lgpio(chip_hint) -> Optional[LgpioBackend]:
    try:
        import lgpio  # noqa: F401
    except ImportError:
        return None
    candidates = []
    if chip_hint is not None:
        candidates.append(int(chip_hint))
    # Pi 5 (RP1) is usually gpiochip4; Pi 3/4 are gpiochip0
    candidates.extend([4, 0, 1, 2, 3])
    seen = set()
    for chip in candidates:
        if chip in seen:
            continue
        seen.add(chip)
        try:
            return LgpioBackend(chip)
        except Exception:
            continue
    return None


def detect_backend(gpios, prefer=None, chip_hint=None) -> GpioBackend:
    """Pick the best backend for this board.

    Order: explicit `prefer` (config) -> pigpiod on Pi 3/4 -> lgpio -> mock.
    """
    gpios = list(gpios)

    if prefer:
        prefer = str(prefer).strip().lower()
        if prefer == "mock":
            return MockBackend()
        if prefer == "pigpio":
            try:
                if _pigpiod_running():
                    return PigpioBackend()
            except Exception:
                pass
        if prefer == "lgpio":
            backend = _open_lgpio(chip_hint)
            if backend is not None:
                return backend

    # Pi 3/4: pigpiod gives DMA-precise TX waves. Pi 5: pigpiod unsupported.
    if not is_pi5() and _pigpiod_running():
        try:
            return PigpioBackend()
        except Exception:
            pass

    backend = _open_lgpio(chip_hint)
    if backend is not None:
        return backend

    return MockBackend()
