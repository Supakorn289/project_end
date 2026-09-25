#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np

from geometry import calibrated_horizontal_offset_deg


SITE_DIR = Path(
    Path("/home/fire/current_site_setup_path.txt")
    .read_text(encoding="utf-8")
    .strip()
)

VALIDATION_DIR = Path(
    Path("/home/fire/current_cross_validation_path.txt")
    .read_text(encoding="utf-8")
    .strip()
)

GEOMETRY_FILE = (
    SITE_DIR
    / "results"
    / "preset_geometry_candidate_v3.json"
)

MARK_FILE = (
    VALIDATION_DIR
    / "cross_preset_marks.json"
)

PAIRS = {
    "1-2": (1, 2),
    "2-3": (2, 3),
    "3-4": (3, 4),
    "4-5": (4, 5),
    "1-6": (1, 6),
    "6-7": (6, 7),
    "7-8": (7, 8),
    "8-9": (8, 9),
    "5-9": (5, 9),
}


def signed_deg(value):
    return ((float(value) + 180.0) % 360.0) - 180.0


def main():

    if not GEOMETRY_FILE.exists():
        raise RuntimeError(
            f"Geometry not found: {GEOMETRY_FILE}"
        )

    if not MARK_FILE.exists():
        raise RuntimeError(
            f"Validation marks not found: {MARK_FILE}"
        )

    geometry = json.loads(
        GEOMETRY_FILE.read_text(encoding="utf-8")
    )

    marks = json.loads(
        MARK_FILE.read_text(encoding="utf-8")
    )

    if geometry.get("status") != \
            "PASS_FOR_CROSS_PRESET_VALIDATION":
        raise RuntimeError(
            "Geometry v3 is not approved "
            "for cross-preset validation"
        )

    width = int(geometry["frame_width"])
    height = int(geometry["frame_height"])

    centers = {
        int(preset): float(
            item["center_relative_deg"]
        )
        for preset, item
        in geometry["presets"].items()
    }

    print("=" * 100)
    print(
        "INDEPENDENT SAME-TARGET "
        "CROSS-PRESET BEARING VALIDATION"
    )
    print("=" * 100)
    print(f"Geometry   : {GEOMETRY_FILE}")
    print(f"Validation : {VALIDATION_DIR}")
    print(f"Resolution : {width}x{height}")
    print()

    pair_results = {}
    global_errors = []
    every_pair_pass = True

    for key, (preset_a, preset_b) in PAIRS.items():

        pair_marks = (
            marks
            .get("pairs", {})
            .get(key, [])
        )

        if len(pair_marks) < 3:
            raise RuntimeError(
                f"{key}: need >=3 targets, "
                f"found {len(pair_marks)}"
            )

        signed_errors = []
        target_results = []

        print("-" * 100)
        print(
            f"PAIR {key} "
            f"| P{preset_a} center="
            f"{centers[preset_a]:.3f}° "
            f"| P{preset_b} center="
            f"{centers[preset_b]:.3f}°"
        )

        for index, mark in enumerate(
            pair_marks,
            start=1,
        ):
            xa, ya = mark["a"]
            xb, yb = mark["b"]

            ray_a = (
                calibrated_horizontal_offset_deg(
                    float(xa),
                    float(ya),
                    width,
                    height,
                )
            )

            ray_b = (
                calibrated_horizontal_offset_deg(
                    float(xb),
                    float(yb),
                    width,
                    height,
                )
            )

            bearing_a = (
                centers[preset_a]
                + ray_a
            ) % 360.0

            bearing_b = (
                centers[preset_b]
                + ray_b
            ) % 360.0

            error = signed_deg(
                bearing_a - bearing_b
            )

            abs_error = abs(error)

            signed_errors.append(error)
            global_errors.append(abs_error)

            if abs_error <= 2.0:
                status = "PASS"
            elif abs_error <= 3.0:
                status = "REVIEW"
            else:
                status = "FAIL"

            target_results.append({
                "index": index,
                "ray_a_deg": float(ray_a),
                "ray_b_deg": float(ray_b),
                "bearing_a_deg": float(bearing_a),
                "bearing_b_deg": float(bearing_b),
                "signed_error_deg": float(error),
                "absolute_error_deg": float(abs_error),
                "status": status,
            })

            print(
                f"  Target {index:02d} "
                f"| P{preset_a}="
                f"{bearing_a:8.3f}° "
                f"| P{preset_b}="
                f"{bearing_b:8.3f}° "
                f"| Δ={error:+7.3f}° "
                f"| {status}"
            )

        errors = np.asarray(
            signed_errors,
            dtype=float,
        )

        absolute = np.abs(errors)

        median_abs = float(
            np.median(absolute)
        )

        mean_abs = float(
            np.mean(absolute)
        )

        rmse = float(
            math.sqrt(
                np.mean(errors ** 2)
            )
        )

        max_abs = float(
            np.max(absolute)
        )

        pair_pass = (
            median_abs <= 1.50
            and
            max_abs <= 2.50
        )

        if not pair_pass:
            every_pair_pass = False

        pair_status = (
            "PASS"
            if pair_pass
            else "REVIEW"
        )

        pair_results[key] = {
            "preset_a": preset_a,
            "preset_b": preset_b,
            "target_count": len(pair_marks),
            "median_absolute_error_deg": median_abs,
            "mean_absolute_error_deg": mean_abs,
            "rmse_deg": rmse,
            "max_absolute_error_deg": max_abs,
            "status": pair_status,
            "targets": target_results,
        }

        print(
            f"  => median={median_abs:.3f}° "
            f"| mean={mean_abs:.3f}° "
            f"| RMSE={rmse:.3f}° "
            f"| max={max_abs:.3f}° "
            f"| {pair_status}"
        )

    global_errors = np.asarray(
        global_errors,
        dtype=float,
    )

    global_median = float(
        np.median(global_errors)
    )

    global_mean = float(
        np.mean(global_errors)
    )

    global_p90 = float(
        np.percentile(
            global_errors,
            90,
        )
    )

    global_max = float(
        np.max(global_errors)
    )

    global_pass = (
        every_pair_pass
        and
        global_median <= 1.25
        and
        global_p90 <= 2.00
        and
        global_max <= 2.50
    )

    result = (
        "PASS_FOR_STATIC_GEOMETRY_RUNTIME"
        if global_pass
        else
        "STATIC_GEOMETRY_REVIEW_REQUIRED"
    )

    output = {
        "format":
            "smart-fire-cross-preset-validation-result-v1",
        "geometry_file": str(GEOMETRY_FILE),
        "validation_dir": str(VALIDATION_DIR),
        "pair_results": pair_results,
        "global_metrics": {
            "target_count": int(
                len(global_errors)
            ),
            "median_absolute_error_deg":
                global_median,
            "mean_absolute_error_deg":
                global_mean,
            "p90_absolute_error_deg":
                global_p90,
            "max_absolute_error_deg":
                global_max,
        },
        "result": result,
    }

    output_path = (
        VALIDATION_DIR
        / "cross_preset_validation_result.json"
    )

    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 100)
    print("GLOBAL RESULT")
    print("=" * 100)
    print(
        f"Targets        : "
        f"{len(global_errors)}"
    )
    print(
        f"Median abs err : "
        f"{global_median:.4f}°"
    )
    print(
        f"Mean abs err   : "
        f"{global_mean:.4f}°"
    )
    print(
        f"P90 abs err    : "
        f"{global_p90:.4f}°"
    )
    print(
        f"Max abs err    : "
        f"{global_max:.4f}°"
    )
    print(
        f"RESULT         : "
        f"{result}"
    )
    print(
        f"SAVED          : "
        f"{output_path}"
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
