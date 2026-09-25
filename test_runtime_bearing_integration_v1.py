#!/usr/bin/env python3

import json
import time
from pathlib import Path

from bearing_localizer import BearingLocalizerCandidate
from camera import LatestFrameCamera
from config import SWEEP_SEQUENCE
from detection import FireDetector
from main import scan_preset
from ptz import PTZController


def main():

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    output = Path(
        "/home/fire"
    ) / (
        "runtime_bearing_integration_"
        f"{timestamp}.json"
    )

    print("=" * 90)
    print(
        "Smart Fire Detection v2 "
        "- LIVE BEARING RUNTIME INTEGRATION"
    )
    print("=" * 90)
    print(
        "Absolute North : LOCKED"
    )
    print(
        "GPS            : SUPPRESSED"
    )
    print(
        f"Route          : "
        f"{SWEEP_SEQUENCE}"
    )
    print("=" * 90)

    camera = LatestFrameCamera().start()

    records = []

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

            time.sleep(0.1)

        print("RTSP=READY")

        detector = FireDetector()

        localizer = (
            BearingLocalizerCandidate()
        )

        ptz = PTZController()

        first_move = True

        for step, preset in enumerate(
            SWEEP_SEQUENCE,
            start=1,
        ):

            print()
            print("=" * 90)
            print(
                f"STEP {step:02d}/"
                f"{len(SWEEP_SEQUENCE)} "
                f"| P{preset}"
            )
            print("=" * 90)

            (
                confirmed,
                packet,
                info,
            ) = scan_preset(
                camera,
                ptz,
                detector,
                preset,
                first_move=first_move,

                # Relative bearing only.
                site_bearing_calibrated=False,

                bearing_localizer=localizer,
            )

            if info.get(
                "ptz_ok",
                False,
            ):
                first_move = False

            record = {
                "step": step,
                "preset": int(preset),

                "status": (
                    info.get(
                        "status"
                    )
                ),

                "geometry_valid": bool(
                    info.get(
                        "geometry_valid",
                        False,
                    )
                ),

                "geometry_method": (
                    info.get(
                        "geometry_method"
                    )
                ),

                "geometry_quality": (
                    info.get(
                        "geometry_quality"
                    )
                ),

                "center_deg": (
                    info.get(
                        "optical_center_bearing_deg"
                    )
                ),

                "frames_processed": (
                    info.get(
                        "frames_processed"
                    )
                ),

                "confirmed_detections": (
                    len(confirmed)
                ),
            }

            records.append(record)

            print(
                "RUNTIME RESULT "
                f"| valid="
                f"{record['geometry_valid']} "
                f"| method="
                f"{record['geometry_method']} "
                f"| quality="
                f"{record['geometry_quality']} "
                f"| center="
                f"{record['center_deg']}"
            )

    finally:
        camera.stop()

    expected = len(
        SWEEP_SEQUENCE
    )

    valid = sum(
        r["geometry_valid"]
        for r in records
    )

    invalid = (
        len(records)
        - valid
    )

    primary = sum(
        r["geometry_method"]
        == "PRIMARY_SAME_PRESET"
        for r in records
    )

    bank = sum(
        r["geometry_method"]
        == "REFERENCE_BANK_FALLBACK"
        for r in records
    )

    degraded = sum(
        r["geometry_method"]
        == "PRIMARY_DEGRADED"
        for r in records
    )

    result = (
        "PASS_FOR_CROSS_PRESET_TEST"
        if (
            len(records)
            == expected
            and
            invalid == 0
        )
        else
        "NOT_READY"
    )

    report = {
        "version": 1,

        "absolute_north_applied": False,
        "gps_allowed": False,

        "records": records,

        "summary": {
            "expected": expected,
            "total": len(records),
            "valid": valid,
            "invalid": invalid,
            "primary": primary,
            "bank": bank,
            "degraded": degraded,
            "result": result,
        },
    }

    output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 90)
    print(
        "RUNTIME BEARING "
        "INTEGRATION SUMMARY"
    )
    print("=" * 90)

    print(
        f"Expected : {expected}"
    )
    print(
        f"Total    : {len(records)}"
    )
    print(
        f"Valid    : {valid}"
    )
    print(
        f"Invalid  : {invalid}"
    )
    print(
        f"Primary  : {primary}"
    )
    print(
        f"Bank     : {bank}"
    )
    print(
        f"Degraded : {degraded}"
    )
    print(
        f"RESULT   : {result}"
    )
    print(
        f"Saved    : {output}"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
