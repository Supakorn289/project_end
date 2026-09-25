#!/usr/bin/env python3

import time

from camera import (
    LatestFrameCamera,
)

from detection import (
    FireDetector,
)

from ptz import (
    PTZController,
)

from test_ptz_repeatability_v1 import (
    move_to_stable,
)


ROUTE = [
    1, 2, 3, 4, 5,
    6, 7, 8, 9,
]


def main():

    camera = (
        LatestFrameCamera()
        .start()
    )

    try:

        deadline = (
            time.monotonic()
            + 10.0
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
                    "Camera startup timeout"
                )

            time.sleep(
                0.1
            )


        detector = (
            FireDetector()
        )

        ptz = (
            PTZController()
        )


        print(
            "=" * 90
        )

        print(
            "LIVE DYNAMIC BEARING RUNTIME TEST"
        )

        print(
            "GPS=False | North=False | "
            "Notifications=NONE"
        )

        print(
            "=" * 90
        )


        for preset in ROUTE:

            print()
            print(
                f"=== P{preset} ==="
            )

            packet = (
                move_to_stable(
                    camera,
                    ptz,
                    preset,
                )
            )

            if packet is None:
                print(
                    "STABLE_FRAME=FAILED"
                )
                continue


            detections = (
                detector.detect(
                    packet.frame,
                    preset,

                    apply_north_offset=False,
                    allow_gps=False,
                )
            )


            print(
                f"DETECTIONS={len(detections)}"
            )


            for index, d in enumerate(
                detections,
                start=1,
            ):

                print(
                    f"  #{index} "
                    f"{d.canonical_class} "
                    f"conf={d.confidence:.3f} "
                    f"bearing={d.bearing_deg:.3f}° "
                    f"distance={d.distance_m} "
                    f"gps={d.gps}"
                )


        print()
        print(
            "LIVE_DYNAMIC_BEARING_TEST=COMPLETE"
        )

    finally:

        try:
            camera.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
