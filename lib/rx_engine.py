"""Async RX engine: radio + GPIO edges -> protocol decoders / RAW recorder."""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from .cc1101 import CC1101
from .gpio_backend import GpioBackend
from .keystore import Keystore
from .presets import Preset
from .protocols import (CameDecoder, HoltekDecoder, KeeLoqDecoder,
                         NiceFloDecoder, PrincetonDecoder)


class RxEngine:
    """Starts the radio in RX and feeds every GPIO edge to all decoders."""

    def __init__(self, radio: CC1101, gpio: GpioBackend, gdo0_gpio: int,
                 keystore: Optional[Keystore] = None):
        self.radio = radio
        self.gpio = gpio
        self.gdo0_gpio = int(gdo0_gpio)
        self.keystore = keystore
        self._decoders = []
        self._callbacks: List[Callable] = []
        self._recorder: Optional[List] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # -- lifecycle -----------------------------------------------------------
    def start(self, preset: Preset, freq: int, on_found: Optional[Callable] = None):
        if on_found is not None:
            self.on_found(on_found)
        self._decoders = [
            PrincetonDecoder(),
            CameDecoder(),
            NiceFloDecoder(),
            HoltekDecoder(),
            KeeLoqDecoder(keystore=self.keystore),
        ]
        for decoder in self._decoders:
            decoder.on_found(self._dispatch)

        self.radio.idle()
        self.radio.load_preset(preset)
        self.radio.set_frequency(freq)
        self.radio.start_rx()
        self.gpio.start_input(self.gdo0_gpio)

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._running = False
            self._thread.join(timeout=2.0)
            self._thread = None
            # drain anything still queued so callbacks are complete
            for level, duration in self.gpio.poll_edges():
                self._feed(level, duration)
        try:
            self.gpio.stop_input()
        except Exception:  # pragma: no cover
            pass
        try:
            self.radio.idle()
        except Exception:  # pragma: no cover
            pass
        self._decoders = []

    # -- callbacks -------------------------------------------------------------
    def on_found(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def _dispatch(self, result) -> None:
        for callback in self._callbacks:
            try:
                callback(result)
            except Exception:  # pragma: no cover - user code must not kill RX
                pass

    # -- edge pump ----------------------------------------------------------------
    def _loop(self) -> None:
        while self._running:
            events = self.gpio.poll_edges()
            if not events:
                time.sleep(0.001)
                continue
            for level, duration in events:
                self._feed(level, duration)

    def _feed(self, level: bool, duration: int) -> None:
        if self._recorder is not None:
            self._recorder.append((bool(level), int(duration)))
        for decoder in self._decoders:
            decoder.feed(level, duration)

    # -- RAW capture ------------------------------------------------------------
    def start_recording(self) -> None:
        self._recorder = []

    def stop_recording(self) -> List:
        # let the reader thread drain any queued edges into the recorder
        # before we detach it (keeps short captures complete)
        time.sleep(0.02)
        levels = self._recorder or []
        self._recorder = None
        return levels

    # -- helpers -------------------------------------------------------------------
    def rssi_dbm(self) -> float:
        return self.radio.get_rssi_dbm()
