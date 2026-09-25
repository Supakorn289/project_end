#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from camera import LatestFrameCamera
from config import SWEEP_SEQUENCE
from ptz import PTZController

from test_ptz_repeatability_v1 import (
    compare_images,
    load_intrinsics,
    move_to_stable,
    save_match_debug,
    wait_camera_ready,
)


DEFAULT_REF_DIR = Path(
    "/home/fire/bearing_reference_20260908_141707"
)

OUTPUT_ROOT = Path(
    "/home/fire/dynamic_bearing_validation"
)


def normalize_360(value):
    return float(value) % 360.0


def clean_comparison(data):
    return {
        key: value
        for key, value in data.items()
        if key != "_debug"
    }


def classify(comparison):
    if not comparison.get("ok", False):
        return "FAIL"

    inliers = int(
        comparison.get(
            "ransac_inliers",
            0,
        )
    )

    stats = comparison.get("angle_stats") or {}

    std = float(
        stats.get(
            "std",
            999.0,
        )
    )

    # Project diagnostic criteria.
    # Not manufacturer specifications.
    if inliers >= 50 and std <= 0.35:
        return "GOOD"

    if inliers >= 20 and std <= 0.75:
        return "REVIEW"

    return "FAIL"

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Validate dynamic PTZ bearing shift "
            "against frozen reference images"
        )
    )

    parser.add_argument(
        "--reference-dir",
        default=str(DEFAULT_REF_DIR),
        help="Frozen bearing reference directory",
    )

    parser.add_argument(
        "--sweeps",
        type=int,
        default=1,
        help="Number of complete production sweeps",
    )

    parser.add_argument(
        "--ratio-threshold",
        type=float,
        default=0.75,
        help="ORB KNN Lowe ratio threshold",
    )

    parser.add_argument(
        "--min-matches",
        type=int,
        default=20,
        help="Minimum RANSAC inlier matches",
    )

    args = parser.parse_args()

    ref_dir = Path(
        args.reference_dir
    )

    graph_file = (
        ref_dir
        / "bearing_azimuth_graph_candidate.json"
    )

    if not graph_file.exists():
        raise SystemExit(
            f"Missing graph:\n{graph_file}"
        )

    graph = json.loads(
        graph_file.read_text(
            encoding="utf-8"
        )
    )

    reference_azimuth = {
        int(p not graph_file.exists():
        raise SystemExit(
            f"Missing graph:\n{graph_file}"
        )

    graph = json.loads(
        graph_file.read_text(
            encoding="utf-8"
        )
    )

    reference_azimuth = {
        int(preset):
        float(
            values[
                "reference_relative_azimuth_deg"
            ]
        )

        for preset, values
        in graph["presets"].items()
    }

    (
        intrinsics,
        camera_matrix,
        distortion,
    ) = load_intrinsics()

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    run_dir = (
        OUTPUT_ROOT
        / f"run_{timestamp}"
    )

    image_dir = (
        run_dir
        / "images"
    )

    debug_dir = (
        run_dir
        / "matches"
    )

    image_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    debug_dir.mkdir(
        run_dir
        / "matches"
    )

    image_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 100)
    print(
        "DYNAMIC FROZEN-REFERENCE "
        "BEARING VALIDATION v1"
    )
    print("=" * 100)

    print(
        f"Reference : {ref_dir}"
    )

    print(
        f"Sweeps    : {args.sweeps}"
    )

    print(
        f"Route     : "
        f"{list(SWEEP_SEQUENCE)}"
    )

    print(
        f"fx        : "
        f"{intrinsics['fx_px)}"
    )

    print(
        f"fx        : "
        f"{intrinsics['fx_px']:.3f}px"
    )

    print(
        "NOTE      : "
        "relative azimuth only; "
        "absolute north not applied"
    )

    print("=" * 100)

    camera = (
        LatestFrameCamera()
        .start()
    )

    ptz = PTZController()

    records = []

    first_move = True

    try:

        print(
            "\nWaiting for RTSP..."
        )

        wait_camera_ready(
            camera
        )

        print(
            "RTSP ready"
        )

        for sweep_index in range(
            1,
            args.sweeps + 1,
        ):

            print()
            print("#" * 100)
            print(
                f"SWEEP {sweep_index}"
            )
            print("#" * 100 1,
        ):

            print()
            print("#" * 100)
            print(
                f"SWEEP {sweep_index}"
            )
            print("#" * 100)

            for step_index, preset in enumerate(
                SWEEP_SEQUENCE,
                start=1,
            ):

                preset = int(
                    preset
                )

                print()
                print("-" * 100)

                print(
                    f"Sweep {sweep_index} "
                    f"| Step {step_index:02d} "
                    f"| P{preset}"
                )

                print("-" * 100)

                stable = move_to_stable(
                    camera,
                    ptz,
                    preset,
                    first_move=first_move,
                )

                first_move = False

                current = (
                    stable.frame.copy()
                )

                ref_path = (
                    ref_dir
                    / "images"
                    / f"preset_{preset}.jpg"
                )

                reference = cv2.imread(
                    str(ref_path)
                )

                if reference is None:
                    raise RuntimeError(
                        f"Cannot read "
                        f"{ref_path}"
                    )

                current_path = (
                    image_dir
                    / (
                        f"s{sweep_index:02d}_ref_path}"
                    )

                current_path = (
                    image_dir
                    / (
                        f"s{sweep_index:02d}_"
                        f"step{step_index:02d}_"
                        f"p{preset}.jpg"
                    )
                )

                cv2.imwrite(
                    str(current_path),
                    current,
                )

                comparison = compare_images(
                    reference,
                    current,
                    camera_matrix,
                    distortion,
                    ratio_threshold=(
                        args.ratio_threshold
                    ),
                    min_matches=(
                        args.min_matches
                    ),
                )

                record = {
                    "sweep": sweep_index,
                    "step": step_index,
                    "preset": preset,
                    "reference_image": str(
                        ref_path
                    ),
                    "current_image": str(
                        current_path
                    ),
                    "comparison": (
                        clean_comparison(
                            comparison
                        )
                    ),
                }

                if not comparison.get(
                    "ok",
                    False,
                ):

                    quality = "FAIL"

                    record[
                        "quality"
                    ] = quality

                    print(
                        "MATCH = FAIL "
                        f"| reason = FAIL "
                        f"| reason="
                        f"{comparison.get('reason')}"
                    )

                    records.append(
                        record
                    )

                    continue

                stats = comparison[
                    "angle_stats"
                ]

                # IMPORTANT:
                #
                # compare_images(reference, current)
                #
                # delta =
                # optical_offset_reference
                # -
                # optical_offset_current
                #
                # therefore:
                #
                # center_current - center_reference
                # = delta
                #
                dynamic_shift = float(
                    stats["median"]
                )

                ref_az = float(
                    reference_azimuth[
                        preset
                    ]
                )

                current_relative_az = (
                    normalize_360(
                        ref_az
                        + dynamic_shift
                    )
                )

                quality = classify(
                    comparison
                )

                record.update({
                    "quality": quality,

                    "reference_relative_azimuth_deg": (
                        ref_az
                    ),

                    "dynamic_shift_deg": (
                        dynamic_shift
                    ),

                    "current_relative_azimuth_deg": (
                        current_relative_az
                    ),
                })

                debug_path = (
                    debug_dir
                    / (
                        f"s{sweep_index:02d}_"
                        f"step{step_index:02d}_"
                        f"p{preset}_matches.jpg"
                    )
                )

               02d}_"
                        f"p{preset}_matches.jpg"
                    )
                )

                save_match_debug(
                    debug_path,
                    reference,
                    current,
                    comparison,
                )

                print(
                    f"RANSAC inliers : "
                    f"{comparison['ransac_inliers']}"
                )

                print(
                    f"Feature median : "
                    f"{stats['median']:+.4f}°"
                )

                print(
                    f"Feature std    : "
                    f"{stats['std']:.4f}°"
                )

                print(
                    f"Feature range  : "
                    f"{stats['range']:.4f}°"
                )

                print(
                    f"Reference az   : "
                    f"{ref_az:.4f}°"
                )

                print(
                    f"Dynamic shift  : "
                    f"{dynamic_shift:+.4f}°"
                )

                print(
                    f"Current rel az : "
                    f"{current_relative_az:.4f}°"
                )

                print(
                    f"MATCH QUALITY  : "
                    f"{quality}"
                )

                records.append(
                    record
                )

    finally:

        camera.stop()

    good = sum(
        r.get("quality") == "GOOD"
        for r in records
    )

    review = sum(
        r.get("quality") == "REVIEW"
        for r in records
    )

    failed = sum(
        r.get("quality") == "FAIL"
        for r in records
    )

    successful = [
        r
        for r in records
        if "dynamic_shift_deg" in r
    ]

    printdynamic_shift_deg" in r
    ]

    print()
    print("=" * 100)
    print(
        "DYNAMIC MATCH SUMMARY"
    )
    print("=" * 100)

    print(
        f"Total steps : "
        f"{len(records)}"
    )

    print(
        f"GOOD        : {good}"
    )

    print(
        f"REVIEW      : {review}"
    )

    print(
        f"FAIL        : {failed}"
    )

    if successful:

        shifts = [
            float(
                r[
                    "dynamic_shift_deg"
                ]
            )
            for r in successful
        ]

        print(
            f"Shift min   : "
            f"{min(shifts):+.4f}°"
        )

        print(
            f"Shift max   : "
            f"{max(shifts):+.4f}°"
        )

        print(
            f"Max |shift| : "
            f"{max(abs(x) for x in shifts):.4f}°"
        )

    if failed == 0:

        overall = (
            "PASS_FOR_MULTI_SWEEP_VALIDATION"
        )

    else:

        overall = (
            "NOT_READY"
        )

    print(
        f"RESULT      : {overall}"
    )

    output = {
        "version": 1 f"RESULT      : {overall}"
    )

    output = {
        "version": 1,

        "reference_dir": str(
            ref_dir
        ),

        "method": (
            "frozen_reference_to_current_"
            "orb_ransac_calibrated_horizontal_shift"
        ),

        "absolute_north_applied": False,

        "sweeps": args.sweeps,

        "route": [
            int(x)
            for x in SWEEP_SEQUENCE
        ],

        "criteria": {
            "good": (
                "ransac_inliers >= 50 "
                "and robust_std_deg <= 0.35"
            ),

            "review": (
                "ransac_inliers >= 20 "
                "and robust_std_deg <= 0.75"
            ),

            "note": (
                "Project diagnostic criteria, "
                "not manufacturer specifications."
            ),
        },

        "summary": {
            "total_steps": len(
                recor:contentReference[oaicite:3]{index=3}ood": good,
            "review": review,
            "fail": failed,
            "result": overall,
        },

        "records": records,
    }

    report_file = (
        run_dir
        / "dynamic_reference_validation.json"
    )

    report_file.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Report      : "
        f"{report_file}"
    )

    print(
        f"Debug       : "
        f"{debug_dir}"
    )

    print("=" * 100)


if __name__ == "__main__":
    main()
