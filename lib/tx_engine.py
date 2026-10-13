"""Async TX engine: protocol uploads -> radio (via GPIO waves)."""

from __future__ import annotations

from typing import Optional

from .cc1101 import CC1101
from .gpio_backend import GpioBackend
from .keystore import Keystore
from .presets import Preset
from .protocols import (CameEncoder, HoltekEncoder, NiceFloEncoder,
                         PrincetonEncoder)
from .subfile import SubFile, raw_durations_to_levels
from .util import format_freq, is_tx_allowed


def decoded_upload(sub: SubFile) -> list:
    """Rebuild a decoded .sub's waveform with its protocol encoder."""
    proto = (sub.protocol or "").strip()
    bit = int(sub.bit or 0)
    te = int(sub.te or 0)
    if proto == "Princeton":
        return PrincetonEncoder(data=sub.key, data_count_bit=bit or 24,
                               te=te or 390,
                               guard_time=sub.guard_time or 30).build_upload()
    if proto == "CAME":
        return CameEncoder(data=sub.key, data_count_bit=bit or 12,
                           te=te or 320).build_upload()
    if proto == "Nice FLO":
        return NiceFloEncoder(data=sub.key, data_count_bit=bit or 12,
                             te=te or 500).build_upload()
    if proto == "Holtek":
        return HoltekEncoder(data=sub.key, data_count_bit=bit or 40,
                            te=te or 400).build_upload()
    raise ValueError(f"don't know how to replay protocol {proto!r} "
                     "(RAW captures and KeeLoq/CAME/Nice/Princeton/Holtek "
                     "keys are supported)")


class TxEngine:
    """Sends presets/frequencies/protocol frames through the radio."""

    def __init__(self, radio: CC1101, gpio: GpioBackend, gdo0_gpio: int,
                 allow_extended: bool = True, keystore: Optional[Keystore] = None,
                 tx_power_dbm: Optional[int] = None):
        self.radio = radio
        self.gpio = gpio
        self.gdo0_gpio = int(gdo0_gpio)
        self.allow_extended = bool(allow_extended)
        self.keystore = keystore
        self.tx_power_dbm = tx_power_dbm

    # -- core -------------------------------------------------------------
    def send(self, preset: Preset, freq: int, upload: list,
             repeat: int = 1) -> int:
        """Transmit one upload `repeat` times; returns frames sent."""
        if not is_tx_allowed(freq, self.allow_extended):
            raise ValueError(
                f"{format_freq(freq)} is outside the allowed TX bands — "
                "set allow_extended_freq in config.json for the full range")
        repeat = max(1, int(repeat))
        self.radio.idle()
        self.radio.load_preset(preset)
        self.radio.set_frequency(freq)
        if self.tx_power_dbm is not None:
            try:
                self.radio.set_power_dbm(self.tx_power_dbm)
            except Exception:  # pragma: no cover
                pass
        self.radio.start_tx()
        sent = 0
        try:
            for _ in range(repeat):
                self.gpio.wave_send(self.gdo0_gpio, upload)
                sent += 1
        finally:
            self.radio.idle()
        return sent

    # -- .sub files ---------------------------------------------------------
    def send_subfile(self, sub: SubFile) -> int:
        preset = sub.preset()
        freq = int(sub.frequency)
        repeat = int(sub.repeat) if sub.repeat else 1
        if sub.is_raw:
            levels = raw_durations_to_levels(sub.raw_data)
            return self.send(preset, freq, levels, repeat=repeat)

        if (sub.protocol or "").strip() == "KeeLoq":
            from .keeloq_tx import next_code_upload
            upload, rep = next_code_upload(sub, keystore=self.keystore,
                                           counter_mode=sub.counter_mode)
            return self.send(preset, freq, upload, repeat=rep)

        return self.send(preset, freq, decoded_upload(sub), repeat=repeat)
