#!/usr/bin/env python3
"""Regenerate the shipped sample .sub files (assets/subghz/*.sub).

Run from the project root:  python tools/make_samples.py

The KeeLoq sample is the "verified demo key": serial 0x2C5B1F, button 1,
counter 0x1234, manufacturer key 0x1122334455667788 (simple learning) — the
same key `tests_selftest.py` and the pytest suite verify end-to-end.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from lib import keeloq_crypto as kq                      # noqa: E402
from lib.presets import AM650                            # noqa: E402
from lib.protocols.keeloq import build_upload            # noqa: E402
from lib.subfile import SubFile                          # noqa: E402

OUTDIR = os.path.join(HERE, "assets", "subghz")

DEMO_MF = "Unleashed-Pi Demo"
DEMO_KEY = 0x1122334455667788
SERIAL = 0x2C5B1F
BTN = 0x1
CNT = 0x1234


def save_came() -> None:
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "CAME"
    sub.bit = 12
    sub.key = 0x6A3
    sub.te = 320
    sub.repeat = 5
    sub.save(os.path.join(OUTDIR, "SAMPLE_CAME.sub"))


def save_nice() -> None:
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "Nice FLO"
    sub.bit = 12
    sub.key = 0x345
    sub.te = 500
    sub.repeat = 5
    sub.save(os.path.join(OUTDIR, "SAMPLE_Nice_FLO.sub"))


def save_princeton() -> None:
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "Princeton"
    sub.bit = 24
    sub.key = 0x1A2B3C
    sub.te = 390
    sub.guard_time = 30
    sub.repeat = 5
    sub.save(os.path.join(OUTDIR, "SAMPLE_Princeton.sub"))


def save_holtek() -> None:
    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "Holtek"
    sub.bit = 40
    sub.key = 0x5123456789
    sub.te = 400
    sub.repeat = 5
    sub.save(os.path.join(OUTDIR, "SAMPLE_Holtek.sub"))


def save_raw() -> None:
    sub = SubFile()
    sub.filetype = "Flipper SubGhz RAW File"
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    # 2 x CAME frame 0x6A3 as raw durations (te 320)
    from lib.protocols import CameEncoder
    upload = CameEncoder(data=0x6A3, data_count_bit=12, te=320).build_upload()
    sub.raw_data = [d if lvl else -d for lvl, d in upload]
    sub.repeat = 1
    sub.save(os.path.join(OUTDIR, "SAMPLE_RAW.sub"))


def save_keeloq() -> None:
    man_key = DEMO_KEY  # simple learning: hop key == manufacturer key
    hop = kq.keeloq_encrypt(kq.build_decrypt(BTN, SERIAL, CNT), man_key)
    key = kq.join_frame(kq.build_fix(SERIAL, BTN), hop)

    sub = SubFile()
    sub.frequency = 433_920_000
    sub.preset_name = AM650.name
    sub.protocol = "KeeLoq"
    sub.bit = 64
    sub.key = key
    sub.te = 400
    sub.manufacture = DEMO_MF
    sub.counter_mode = 2
    sub.repeat = 3
    sub.save(os.path.join(OUTDIR, "SAMPLE_KeeLoq.sub"))

    # sanity: round-trip through the air-frame builder + decoder
    from lib.keystore import Keystore
    from lib.protocols import KeeLoqDecoder
    ks = Keystore()
    ks.add(DEMO_MF, DEMO_KEY, "simple")
    result = KeeLoqDecoder(keystore=ks).make_result_from_data(key)
    assert result.manufacture_name == DEMO_MF, result.manufacture_name
    assert result.cnt == CNT, hex(result.cnt or 0)
    assert result.serial == SERIAL and result.btn == BTN
    print(f"  KeeLoq sample verified: mf={result.manufacture_name} "
          f"cnt=0x{result.cnt:04X}")


def main() -> int:
    os.makedirs(OUTDIR, exist_ok=True)
    save_came()
    save_nice()
    save_princeton()
    save_holtek()
    save_raw()
    save_keeloq()
    for name in sorted(os.listdir(OUTDIR)):
        print(f"  wrote {os.path.join('assets', 'subghz', name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
