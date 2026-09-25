#!/usr/bin/env python3

import json
import math
from pathlib import Path

import cv2
import numpy as np

from geometry import calibrated_horizontal_offset_deg


ROOT = Path(
    Path(
        "/home/fire/current_cross_validation_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

CAPTURE_DIR = ROOT / "captures"

MARK_FILE = (
    ROOT
    / "same_preset_repeatability_marks.json"
)

OUTPUT_FILE = (
    ROOT
    / "same_preset_repeatability_result.json"
)


PAIRS = {
    "P1_01-09": {
        "preset": 1,
        "step_a": 1,
        "step_b": 9,
    },

    "P1_09-17": {
        "preset": 1,
        "step_a": 9,
        "step_b": 17,
    },

    "P1_01-17": {
        "preset": 1,
        "step_a": 1,
        "step_b": 17,
    },

    "P2_02-08": {
        "preset": 2,
        "step_a": 2,
        "step_b": 8,
    },

    "P3_03-07": {
        "preset": 3,
        "step_a": 3,
        "step_b": 7,
    },

    "P4_04-06": {
        "preset": 4,
        "step_a": 4,
        "step_b": 6,
    },

    "P6_10-16": {
        "preset": 6,
        "step_a": 10,
        "step_b": 16,
    },

    "P7_11-15": {
        "preset": 7,
        "step_a": 11,
        "step_b": 15,
    },

    "P8_12-14": {
        "preset": 8,
        "step_a": 12,
        "step_b": 14,
    },
}


def signed_deg(value):
    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


def image_name(
    step,
    preset,
):
    return (
        f"step_{step:02d}_"
        f"p{preset}.jpg"
    )


def classify_target(
    absolute_shift,
):

    if absolute_shift <= 1.0:
        return "PASS"

    if absolute_shift <= 2.0:
        return "REVIEW"

    return "FAIL"


def main():

    if not MARK_FILE.exists():
        raise RuntimeError(
            f"Marks not found: "
            f"{MARK_FILE}"
        )

    marks = json.loads(
        MARK_FILE.read_text(
            encoding="utf-8"
        )
    )

    reference_image = cv2.imread(
        str(
            CAPTURE_DIR
            / "step_01_p1.jpg"
        )
    )

    if reference_image is None:
        raise RuntimeError(
            "Cannot read step_01_p1.jpg"
        )

    height, width = (
        reference_image.shape[:2]
    )

    print("=" * 104)
    print(
        "SAME-PRESET PTZ OPTICAL "
        "REPEATABILITY VALIDATION"
    )
    print("=" * 104)

    print(
        f"Root       : {ROOT}"
    )

    print(
        f"Resolution : "
        f"{width}x{height}"
    )

    print()
    print(
        "Definition:"
    )

    print(
        "  shift = calibrated_ray(arrival A)"
        " - calibrated_ray(arrival B)"
    )

    print(
        "  Same preset => optical-center "
        "term cancels completely."
    )

    print()

    results = {}

    pair_statuses = []

    median_shifts = {}

    all_abs_shifts = []


    for key, info in PAIRS.items():

        preset = int(
            info["preset"]
        )

        step_a = int(
            info["step_a"]
        )

        step_b = int(
            info["step_b"]
        )

        pair_marks = (
            marks
            .get("pairs", {})
            .get(key, [])
        )

        if len(pair_marks) < 3:
            raise RuntimeError(
                f"{key}: need >=3 marks; "
                f"found {len(pair_marks)}"
            )


        shifts = []

        target_results = []


        print("-" * 104)

        print(
            f"{key} "
            f"| P{preset} "
            f"| step {step_a:02d} "
            f"vs {step_b:02d}"
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


            shift = signed_deg(
                ray_a
                - ray_b
            )

            abs_shift = abs(
                shift
            )

            target_status = (
                classify_target(
                    abs_shift
                )
            )


            shifts.append(
                shift
            )

            all_abs_shifts.append(
                abs_shift
            )


            target_results.append(
                {
                    "index": index,

                    "ray_a_deg": float(
                        ray_a
                    ),

                    "ray_b_deg": float(
                        ray_b
                    ),

                    "signed_shift_deg": (
                        float(
                            shift
                        )
                    ),

                    "absolute_shift_deg": (
                        float(
                            abs_shift
                        )
                    ),

                    "status": (
                        target_status
                    ),
                }
            )


            print(
                f"  Target {index:02d} "
                f"| rayA="
                f"{ray_a:+8.3f}° "
                f"| rayB="
                f"{ray_b:+8.3f}° "
                f"| shift="
                f"{shift:+7.3f}° "
                f"| {target_status}"
            )


        shifts = np.asarray(
            shifts,
            dtype=float,
        )

        absolute = np.abs(
            shifts
        )


        median_signed = float(
            np.median(
                shifts
            )
        )


        median_abs = float(
            np.median(
                absolute
            )
        )


        mean_abs = float(
            np.mean(
                absolute
            )
        )


        rmse = float(
            math.sqrt(
                np.mean(
                    shifts ** 2
                )
            )
        )


        max_abs = float(
            np.max(
                absolute
            )
        )


        deviations = np.abs(
            shifts
            - median_signed
        )


        mad = float(
            np.median(
                deviations
            )
        )


        robust_sigma = float(
            1.4826
            * mad
        )


        fraction_le_1 = float(
            np.mean(
                absolute
                <= 1.0
            )
        )


        fraction_le_2 = float(
            np.mean(
                absolute
                <= 2.0
            )
        )


        #
        # PASS:
        # robust optical arrival shift <= 1 degree
        # and the target measurements agree well.
        #
        pass_condition = (
            abs(
                median_signed
            )
            <= 1.0
            and
            robust_sigma
            <= 0.75
            and
            fraction_le_2
            >= 0.80
        )


        review_condition = (
            abs(
                median_signed
            )
            <= 2.0
            and
            robust_sigma
            <= 1.25
            and
            fraction_le_2
            >= 0.60
        )


        if pass_condition:
            pair_status = "PASS"

        elif review_condition:
            pair_status = "REVIEW"

        else:
            pair_status = "FAIL"


        pair_statuses.append(
            pair_status
        )

        median_shifts[
            key
        ] = median_signed


        results[
            key
        ] = {
            "preset": preset,

            "step_a": step_a,

            "step_b": step_b,

            "target_count": int(
                len(shifts)
            ),

            "median_signed_shift_deg": (
                median_signed
            ),

            "median_absolute_shift_deg": (
                median_abs
            ),

            "mean_absolute_shift_deg": (
                mean_abs
            ),

            "rmse_deg": rmse,

            "max_absolute_shift_deg": (
                max_abs
            ),

            "mad_deg": mad,

            "robust_sigma_deg": (
                robust_sigma
            ),

            "fraction_le_1_deg": (
                fraction_le_1
            ),

            "fraction_le_2_deg": (
                fraction_le_2
            ),

            "status": (
                pair_status
            ),

            "targets": (
                target_results
            ),
        }


        print(
            f"  => median signed="
            f"{median_signed:+.3f}° "
            f"| median abs="
            f"{median_abs:.3f}° "
            f"| robust σ="
            f"{robust_sigma:.3f}°"
        )

        print(
            f"     mean abs="
            f"{mean_abs:.3f}° "
            f"| RMSE="
            f"{rmse:.3f}° "
            f"| max="
            f"{max_abs:.3f}°"
        )

        print(
            f"     <=1°="
            f"{fraction_le_1*100:.1f}% "
            f"| <=2°="
            f"{fraction_le_2*100:.1f}% "
            f"| {pair_status}"
        )


    #
    # P1 three-arrival internal closure.
    #
    # d(01,17) should equal:
    # d(01,09) + d(09,17)
    #
    p1_closure = float(
        median_shifts[
            "P1_01-09"
        ]
        + median_shifts[
            "P1_09-17"
        ]
        - median_shifts[
            "P1_01-17"
        ]
    )


    all_abs_shifts = np.asarray(
        all_abs_shifts,
        dtype=float,
    )


    global_median_abs = float(
        np.median(
            all_abs_shifts
        )
    )


    global_mean_abs = float(
        np.mean(
            all_abs_shifts
        )
    )


    global_p90_abs = float(
        np.percentile(
            all_abs_shifts,
            90,
        )
    )


    global_max_abs = float(
        np.max(
            all_abs_shifts
        )
    )


    max_pair_median_shift = float(
        max(
            abs(
                value
            )
            for value
            in median_shifts.values()
        )
    )


    pass_pairs = sum(
        status == "PASS"
        for status
        in pair_statuses
    )


    review_pairs = sum(
        status == "REVIEW"
        for status
        in pair_statuses
    )


    fail_pairs = sum(
        status == "FAIL"
        for status
        in pair_statuses
    )


    if (
        fail_pairs == 0
        and
        review_pairs == 0
        and
        abs(
            p1_closure
        )
        <= 0.75
        and
        max_pair_median_shift
        <= 1.0
    ):

        final_result = (
            "PASS_FOR_STATIC_PRESET_GEOMETRY"
        )

    elif (
        fail_pairs == 0
        and
        abs(
            p1_closure
        )
        <= 1.50
        and
        max_pair_median_shift
        <= 2.0
    ):

        final_result = (
            "REPEATABILITY_REVIEW"
        )

    else:

        final_result = (
            "STATIC_PRESET_REPEATABILITY_FAILED"
        )


    payload = {
        "format": (
            "smart-fire-same-preset-"
            "repeatability-result-v1"
        ),

        "root": str(
            ROOT
        ),

        "resolution": {
            "width": int(
                width
            ),

            "height": int(
                height
            ),
        },

        "pairs": results,

        "p1_three_arrival_closure_deg": (
            p1_closure
        ),

        "global_metrics": {
            "pair_count": int(
                len(PAIRS)
            ),

            "pass_pairs": int(
                pass_pairs
            ),

            "review_pairs": int(
                review_pairs
            ),

            "fail_pairs": int(
                fail_pairs
            ),

            "median_absolute_shift_deg": (
                global_median_abs
            ),

            "mean_absolute_shift_deg": (
                global_mean_abs
            ),

            "p90_absolute_shift_deg": (
                global_p90_abs
            ),

            "max_absolute_shift_deg": (
                global_max_abs
            ),

            "max_pair_median_shift_deg": (
                max_pair_median_shift
            ),
        },

        "result": (
            final_result
        ),
    }


    OUTPUT_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print("=" * 104)
    print("REPEATABILITY SUMMARY")
    print("=" * 104)

    print(
        f"Pairs PASS/REVIEW/FAIL : "
        f"{pass_pairs}/"
        f"{review_pairs}/"
        f"{fail_pairs}"
    )

    print(
        f"P1 closure             : "
        f"{p1_closure:+.4f}°"
    )

    print(
        f"Max pair median shift  : "
        f"{max_pair_median_shift:.4f}°"
    )

    print(
        f"Global median abs      : "
        f"{global_median_abs:.4f}°"
    )

    print(
        f"Global mean abs        : "
        f"{global_mean_abs:.4f}°"
    )

    print(
        f"Global P90 abs         : "
        f"{global_p90_abs:.4f}°"
    )

    print(
        f"Global max abs         : "
        f"{global_max_abs:.4f}°"
    )

    print(
        f"RESULT                 : "
        f"{final_result}"
    )

    print(
        f"SAVED                  : "
        f"{OUTPUT_FILE}"
    )

    print("=" * 104)


if __name__ == "__main__":
    main()
