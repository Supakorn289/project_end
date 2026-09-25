#!/usr/bin/env python3

import json
import time
from datetime import datetime
from pathlib import Path

import cv2

from camera import LatestFrameCamera
from ptz import PTZController
from test_ptz_repeatability_v1 import move_to_stable


ROUTE = [1, 6, 7, 8, 9, 5]


def main():

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    root = Path(
        f"/home/fire/"
        f"negative_side_final_{stamp}"
    )

    image_dir = (
        root
        / "captures"
    )

    image_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pointer = Path(
        "/home/fire/"
        "current_negative_side_final_path.txt"
    )

    pointer.write_text(
        str(root),
        encoding="utf-8",
    )

    camera = LatestFrameCamera().start()

    metadata = {
        "format": (
            "smart-fire-cross-preset-"
            "validation-capture-v1"
        ),
        "route": ROUTE,
        "captures": [],
    }

    try:

        deadline = (
            time.monotonic()
            + 15.0
        )

        while (
            camera.latest(
                copy=False
            )
            is None
        ):

            if (
                time.monotonic()
                >= deadline
            ):
                raise RuntimeError(
                    "RTSP timeout"
                )

            time.sleep(
                0.1
            )

        ptz = PTZController()

        first = True

        for step, preset in enumerate(
            ROUTE,
            start=1,
        ):

            print()
            print(
                f"=== STEP {step:02d} "
                f"/ {len(ROUTE)} "
                f"| P{preset} ==="
            )

            packet = move_to_stable(
                camera,
                ptz,
                preset,
                first_move=first,
            )

            first = False

            filename = (
                f"step_{step:02d}_"
                f"p{preset}.jpg"
            )

            path = (
                image_dir
                / filename
            )

            ok = cv2.imwrite(
                str(path),
                packet.frame,
            )

            if not ok:
                raise RuntimeError(
                    f"Cannot save {path}"
                )

            metadata[
                "captures"
            ].append(
                {
                    "step": step,
                    "preset": preset,
                    "filename": filename,
                    "seq": int(
                        packet.seq
                    ),
                    "timestamp": float(
                        packet.timestamp
                    ),
                }
            )

            print(
                f"SAVED {path}"
            )

    finally:
        camera.stop()

    metadata_path = (
        root
        / "capture_metadata.json"
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "=" * 72
    )
    print(
        "NEGATIVE-SIDE FINAL CAPTURE COMPLETE"
    )
    print(
        f"ROOT  : {root}"
    )
    print(
        f"COUNT : {len(metadata['captures'])}"
    )
    print(
        "=" * 72
    )


if __name__ == "__main__":
    main()
