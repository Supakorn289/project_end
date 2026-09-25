#!/usr/bin/env python3

import time

from camera import LatestFrameCamera
from config import SWEEP_SEQUENCE
from cross_preset_fusion import (
    CrossPresetObjectFusion,
)
from detection import FireDetector
from main import (
    AlertDeduplicator,
    scan_preset,
)
from ptz import PTZController


def main():

    camera = (
        LatestFrameCamera()
        .start()
    )

    geometry_failures = 0
    total_confirmed = 0
    fused_count = 0
    duplicate_count = 0

    object_ids = set()

    first_move = True

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
                cooldown_sec=30.0,
                iou_threshold=0.50,
            )
        )


        print(
            "=" * 100
        )

        print(
            "SMART FIRE FINAL LAB "
            "REFERENCE SWEEP"
        )

        print(
            "TRUE NORTH=OFF | GPS=OFF | "
            "TELEGRAM=OFF"
        )

        print(
            f"ROUTE={SWEEP_SEQUENCE}"
        )

        print(
            "=" * 100
        )


        for (
            step,
            preset,
        ) in enumerate(
            SWEEP_SEQUENCE,
            start=1,
        ):

            print()
            print(
                "=" * 100
            )

            print(
                f"STEP {step}/"
                f"{len(SWEEP_SEQUENCE)} "
                f"| P{preset}"
            )

            print(
                "=" * 100
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


            if not info.get(
                "geometry_valid",
                False,
            ):
                geometry_failures += 1


            print(
                "GEOMETRY=",
                info.get(
                    "geometry_method"
                ),
                info.get(
                    "geometry_quality"
                ),
            )

            print(
                "STATUS=",
                info.get(
                    "status"
                ),
            )

            print(
                "CONFIRMED_RAW=",
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


            total_confirmed += len(
                confirmed
            )


            for detection in confirmed:

                object_id = getattr(
                    detection,
                    "object_id",
                    None,
                )

                if object_id:
                    object_ids.add(
                        object_id
                    )


                fused = bool(
                    getattr(
                        detection,
                        "measurement_fused",
                        False,
                    )
                )

                if fused:
                    fused_count += 1


                (
                    should_alert,
                    reason,
                ) = dedup.should_alert(
                    detection,
                    preset,
                    now,
                )


                if not should_alert:
                    duplicate_count += 1

                else:
                    dedup.record_alert(
                        detection,
                        preset,
                        now,
                    )


                raw_bearing = getattr(
                    detection,
                    "raw_bearing_deg",
                    detection.bearing_deg,
                )


                raw_distance = getattr(
                    detection,
                    "raw_distance_m",
                    None,
                )


                print(
                    "OBJECT "
                    f"id={object_id} "
                    f"class="
                    f"{detection.canonical_class} "
                    f"zone="
                    f"{getattr(detection, 'bearing_zone', None)} "
                    f"rawBearing="
                    f"{raw_bearing:.3f}° "
                    f"bearing="
                    f"{detection.bearing_deg:.3f}° "
                    f"rawDistance="
                    f"{raw_distance} "
                    f"distance="
                    f"{detection.distance_m} "
                    f"distanceQuality="
                    f"{detection.distance_quality} "
                    f"fused="
                    f"{fused} "
                    f"source=P"
                    f"{getattr(
                        detection,
                        'measurement_source_preset',
                        preset,
                    )} "
                    f"wouldAlert="
                    f"{should_alert} "
                    f"reason="
                    f"{reason}"
                )


        print()
        print(
            "=" * 100
        )

        print(
            "FINAL LAB SWEEP SUMMARY"
        )

        print(
            "=" * 100
        )

        print(
            f"geometry_failures="
            f"{geometry_failures}"
        )

        print(
            f"confirmed_observations="
            f"{total_confirmed}"
        )

        print(
            f"unique_object_ids="
            f"{len(object_ids)}"
        )

        print(
            f"fused_observations="
            f"{fused_count}"
        )

        print(
            f"dedup_suppressed="
            f"{duplicate_count}"
        )

        print(
            "distance_validation="
            "SKIPPED_LAB"
        )

        print(
            "true_north="
            "DISABLED_LAB"
        )

        print(
            "gps="
            "DISABLED_LAB"
        )


        passed = (
            geometry_failures == 0
            and
            total_confirmed >= 1
            and
            fused_count >= 1
            and
            duplicate_count >= 1
        )


        print()

        if passed:

            print(
                "FINAL_LAB_REFERENCE_GATE=PASS"
            )

            return


        print(
            "FINAL_LAB_REFERENCE_GATE=FAIL"
        )

        raise SystemExit(1)


    finally:

        try:
            camera.stop()

        except Exception:
            pass


if __name__ == "__main__":
    main()
