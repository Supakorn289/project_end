#!/usr/bin/env python3

import time

from camera import LatestFrameCamera
from detection import FireDetector
from ptz import PTZController

from cross_preset_fusion import (
    CrossPresetObjectFusion,
)

from main import (
    AlertDeduplicator,
)

from test_ptz_repeatability_v1 import (
    move_to_stable,
)


ROUTE = [1, 2]


def main():

    camera = LatestFrameCamera().start()

    try:

        deadline = time.monotonic() + 10.0

        while camera.latest(copy=False) is None:

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Camera startup timeout"
                )

            time.sleep(0.1)


        detector = FireDetector()
        ptz = PTZController()

        fusion = CrossPresetObjectFusion()

        dedup = AlertDeduplicator(
            cooldown_sec=30.0,
            iou_threshold=0.50,
        )


        print("=" * 90)
        print(
            "LIVE CROSS-PRESET CENTER/EDGE TEST"
        )
        print(
            "North=False | GPS=False | "
            "Telegram=OFF"
        )
        print("=" * 90)


        for preset in ROUTE:

            print()
            print(
                f"========== P{preset} =========="
            )

            packet = move_to_stable(
                camera,
                ptz,
                preset,
            )

            if packet is None:
                print("STABLE_FRAME=FAILED")
                continue


            detections = detector.detect(
                packet.frame,
                preset,
                apply_north_offset=False,
                allow_gps=False,
            )


            print(
                f"RAW_DETECTIONS={len(detections)}"
            )


            now = time.monotonic()

            fused = fusion.fuse_batch(
                detections,
                preset,
                now,
            )


            for index, d in enumerate(
                fused,
                start=1,
            ):

                should_alert, reason = (
                    dedup.should_alert(
                        d,
                        preset,
                        now,
                    )
                )

                if should_alert:

                    dedup.record_alert(
                        d,
                        preset,
                        now,
                    )


                print(
                    f"#{index} "
                    f"class={d.canonical_class} "
                    f"id={getattr(d, 'object_id', None)} "
                    f"zone={getattr(d, 'bearing_zone', None)} "
                    f"raw_bearing="
                    f"{getattr(d, 'raw_bearing_deg', d.bearing_deg):.3f}° "
                    f"bearing={d.bearing_deg:.3f}° "
                    f"raw_distance="
                    f"{getattr(d, 'raw_distance_m', None)} "
                    f"distance={d.distance_m} "
                    f"fused="
                    f"{getattr(d, 'measurement_fused', False)} "
                    f"source=P"
                    f"{getattr(d, 'measurement_source_preset', preset)} "
                    f"alert={should_alert} "
                    f"reason={reason}"
                )


        print()
        print(
            "LIVE_CROSS_PRESET_TEST=COMPLETE"
        )

    finally:

        try:
            camera.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
