#!/usr/bin/env python3

import time

from camera import LatestFrameCamera
from detection import FireDetector
from ptz import PTZController

from main import (
    scan_preset,
    AlertDeduplicator,
)

from cross_preset_fusion import (
    CrossPresetObjectFusion,
)


ROUTE = [1, 2]


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

        fusion = (
            CrossPresetObjectFusion()
        )

        dedup = (
            AlertDeduplicator(
                cooldown_sec=30.0
            )
        )

        first_move = True


        print(
            "=" * 96
        )

        print(
            "FINAL P1-P2 PRODUCTION-CONSENSUS "
            "FUSION TEST"
        )

        print(
            "North=False | GPS=False | "
            "Telegram=OFF"
        )

        print(
            "=" * 96
        )


        for preset in ROUTE:

            print()
            print(
                f"========== P{preset} =========="
            )


            (
                confirmed,
                packet,
                info,
            ) = scan_preset(
                camera,
                ptz,
                detector,
                preset,

                first_move=(
                    first_move
                ),

                site_bearing_calibrated=False,
            )


            if info.get(
                "ptz_ok"
            ):
                first_move = False


            print(
                "SCAN_STATUS=",
                info.get(
                    "status"
                ),
            )

            print(
                "CONFIRMED_BEFORE_FUSION=",
                len(
                    confirmed
                ),
            )


            if (
                packet is None
                or
                not confirmed
            ):
                continue


            now = (
                time.monotonic()
            )


            confirmed = (
                fusion.fuse_batch(
                    confirmed,
                    preset,
                    now,
                )
            )


            print(
                "CONFIRMED_AFTER_FUSION=",
                len(
                    confirmed
                ),
            )


            for index, d in enumerate(
                confirmed,
                start=1,
            ):

                (
                    should_alert,
                    reason,
                ) = dedup.should_alert(
                    d,
                    preset,
                    now,
                )


                print(
                    f"#{index} "
                    f"class={d.canonical_class} "
                    f"id="
                    f"{getattr(d, 'object_id', None)} "
                    f"zone="
                    f"{getattr(d, 'bearing_zone', None)} "
                    f"raw_bearing="
                    f"{getattr(d, 'raw_bearing_deg', d.bearing_deg):.3f}° "
                    f"bearing="
                    f"{d.bearing_deg:.3f}° "
                    f"raw_distance="
                    f"{getattr(d, 'raw_distance_m', None)} "
                    f"distance="
                    f"{d.distance_m} "
                    f"quality="
                    f"{d.distance_quality} "
                    f"fused="
                    f"{getattr(d, 'measurement_fused', False)} "
                    f"source=P"
                    f"{getattr(d, 'measurement_source_preset', preset)} "
                    f"alert="
                    f"{should_alert} "
                    f"reason="
                    f"{reason}"
                )


                if should_alert:

                    dedup.record_alert(
                        d,
                        preset,
                        now,
                    )


        print()
        print(
            "FINAL_PAIR_CONSENSUS_TEST=COMPLETE"
        )


    finally:

        try:
            camera.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
