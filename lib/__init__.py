"""Unleashed-Pi — Private Unleashed 2.0 attack stack for Raspberry Pi 3/4/5.

Pure-Python sub-GHz toolkit that ports the Flipper Zero "Private Unleashed /
Quantum" firmware stack to a Raspberry Pi with a $3 CC1101 module on the SPI
header (the same radio chip the Flipper uses).

Runs on:
  * Raspberry Pi 3 / 4  — pigpio (DMA-timed TX) or lgpio
  * Raspberry Pi 5     — lgpio (kernel waves / RP1 gpiochip4)
  * any PC             — demo mode (in-memory radio + mock GPIO)

Requires Python 3.9+ (Pi OS Bullseye/Bookworm) and no compiled packages.
"""

__version__ = "2.1.0"
