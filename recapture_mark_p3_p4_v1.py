#!/usr/bin/env python3

import os
import time
from pathlib import Path

import cv2

from camera import LatestFrameCamera
from ptz import PTZController
from test_ptz_repeatability_v1 import (
    move_to_stable,
)


site_dir = os.environ.get(
    "MARK_SITE_DIR"
)

if not site_dir:
    raise RuntimeError(
        "MARK_SITE_DIR is required"
    )

capture_dir = (
    Path(site_dir)
    / "captures"
)


def main():

    camera = LatestFrameCamera().start()

    try:

        deadline = (
            time.monotonic()
            + 15.0
        )

        while (
            camera.latest(copy=False)
            is None
        ):

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "RTSP timeout"
                )

            time.sleep(0.1)

        ptz = PTZController()

        first = True

        for preset in (3, 4):

            print()
            print(
                f"=== RECAPTURE P{preset} ==="
            )

            packet = move_to_stable(
                camera,
                ptz,
                preset,
                first_move=first,
            )

            first = False

            path = (
                capture_dir
                / f"preset_{preset}.jpg"
            )

            ok = cv2.imwrite(
                str(path),
                packet.frame,
            )

            if not ok:
                raise RuntimeError(
                    f"Cannot write {path}"
                )

            print(
                f"SAVED {path}"
            )

    finally:
        camera.stop()


if __name__ == "__main__":
    main()
