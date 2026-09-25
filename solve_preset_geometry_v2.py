#!/usr/bin/env python3

import json
import os
from pathlib import Path

import cv2
import numpy as np

from config import PRESET_BEARING_DEG
from geometry import calibrated_horizontal_offset_deg


PAIRS = [
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),

    (1, 6),
    (6, 7),
    (7, 8),
    (8, 9),

    # Closure edge connecting both branches.
    (5, 9),
]


# ============================================================
# Angle helpers
# ============================================================

def normalize_deg(value):
    return float(value) % 360.0


def normalize_signed_deg(value):
    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


def unwrap_near(
    value,
    reference,
):
    """
    Add/subtract 360 degrees so value is on the
    branch nearest to reference.

    Example:
        value     = +5
        reference = -355
        result    = -355
    """

    value = float(value)
    reference = float(reference)

    turns = round(
        (
            reference
            - value
        )
        / 360.0
    )

    return (
        value
        + 360.0 * turns
    )


# ============================================================
# Site
# ============================================================

def get_site_dir():

    value = os.environ.get(
        "MARK_SITE_DIR"
    )

    if value:
        return Path(value)

    pointer = Path(
        "/home/fire/"
        "current_site_setup_path.txt"
    )

    if not pointer.exists():
        raise RuntimeError(
            "Site pointer not found"
        )

    return Path(
        pointer.read_text(
            encoding="utf-8"
        ).strip()
    )


# ============================================================
# Robust per-pair statistics
# ============================================================

def robust_pair(
    values,
):

    values = np.asarray(
        values,
        dtype=float,
    )

    if len(values) < 3:
        raise RuntimeError(
            "Need at least 3 marks"
        )

    initial_center = float(
        np.median(
            values
        )
    )

    initial_errors = (
        values
        - initial_center
    )

    mad = float(
        np.median(
            np.abs(
                initial_errors
            )
        )
    )

    robust_sigma = (
        1.4826
        * mad
    )

    # Manual marking:
    #
    # - minimum 0.35 deg prevents excessive rejection
    # - maximum 1.50 deg prevents bad marks from
    #   widening the gate indefinitely
    threshold = max(
        0.35,
        min(
            1.50,
            3.5 * robust_sigma,
        ),
    )

    keep = (
        np.abs(
            initial_errors
        )
        <= threshold
    )

    filtered = values[
        keep
    ]

    if len(filtered) < 3:
        raise RuntimeError(
            "Less than 3 inlier marks "
            "after outlier rejection"
        )

    center = float(
        np.median(
            filtered
        )
    )

    residuals = (
        filtered
        - center
    )

    return {
        "center_unwrapped_deg": center,

        "raw_count": int(
            len(values)
        ),

        "inlier_count": int(
            len(filtered)
        ),

        "inlier_fraction": float(
            len(filtered)
            / len(values)
        ),

        "std_deg": float(
            np.std(
                residuals
            )
        ),

        "max_deviation_deg": float(
            np.max(
                np.abs(
                    residuals
                )
            )
        ),

        "mad_deg": float(
            mad
        ),

        "rejection_threshold_deg": float(
            threshold
        ),

        "inlier_mask": [
            bool(value)
            for value in keep
        ],
    }


# ============================================================
# Main
# ============================================================

def main():

    site_dir = get_site_dir()

    capture_dir = (
        site_dir
        / "captures"
    )

    marks_file = (
        site_dir
        / "marks"
        / "marks.json"
    )

    result_dir = (
        site_dir
        / "results"
    )

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ========================================================
    # Inputs
    # ========================================================

    if not marks_file.exists():

        raise RuntimeError(
            f"Marks not found: "
            f"{marks_file}"
        )

    marks_data = json.loads(
        marks_file.read_text(
            encoding="utf-8"
        )
    )


    # ========================================================
    # Validate all capture resolutions
    # ========================================================

    image_shapes = {}

    for preset in range(
        1,
        10,
    ):

        image_path = (
            capture_dir
            / f"preset_{preset}.jpg"
        )

        image = cv2.imread(
            str(image_path)
        )

        if image is None:

            raise RuntimeError(
                f"Cannot read "
                f"{image_path}"
            )

        height, width = (
            image.shape[:2]
        )

        image_shapes[
            preset
        ] = (
            width,
            height,
        )


    unique_shapes = set(
        image_shapes.values()
    )

    if len(unique_shapes) != 1:

        raise RuntimeError(
            "Preset images have "
            f"different resolutions: "
            f"{image_shapes}"
        )

    width, height = next(
        iter(
            unique_shapes
        )
    )


    # ========================================================
    # Physical preset values are used ONLY for choosing
    # the correct +/-360 degree unwrap branch.
    #
    # They are NOT the solved optical centers.
    # ========================================================

    p1_physical = float(
        PRESET_BEARING_DEG[1]
    )

    expected_unwrapped = {}

    for preset in range(
        1,
        10,
    ):

        expected_unwrapped[
            preset
        ] = normalize_signed_deg(
            float(
                PRESET_BEARING_DEG[
                    preset
                ]
            )
            - p1_physical
        )


    print(
        "=" * 92
    )

    print(
        "MARK-BASED PRESET "
        "GEOMETRY SOLVER v2"
    )

    print(
        "=" * 92
    )

    print(
        f"Site       : {site_dir}"
    )

    print(
        f"Resolution : "
        f"{width}x{height}"
    )

    print(
        "Runtime image matching : "
        "DISABLED"
    )

    print(
        "P1 relative anchor      : "
        "0.000 deg"
    )

    print()


    # ========================================================
    # MARK pixels -> calibrated horizontal rays
    # ========================================================

    measurements = {}

    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )

        marks = (
            marks_data
            .get(
                "pairs",
                {},
            )
            .get(
                key,
                [],
            )
        )

        if len(marks) < 3:

            raise RuntimeError(
                f"{key}: need >=3 marks; "
                f"found {len(marks)}"
            )


        # ----------------------------------------------------
        # Expected physical delta is ONLY an unwrap hint.
        # ----------------------------------------------------

        expected_delta = (
            expected_unwrapped[
                preset_b
            ]
            -
            expected_unwrapped[
                preset_a
            ]
        )


        raw_records = []

        unwrapped_values = []


        for (
            number,
            mark,
        ) in enumerate(
            marks,
            start=1,
        ):

            xa, ya = (
                mark[
                    "a"
                ]
            )

            xb, yb = (
                mark[
                    "b"
                ]
            )


            # ------------------------------------------------
            # Lens distortion correction happens inside
            # calibrated_horizontal_offset_deg().
            # ------------------------------------------------

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


            # ------------------------------------------------
            # Same physical world point:
            #
            # C_a + ray_a
            # =
            # C_b + ray_b
            #
            # Therefore:
            #
            # C_b - C_a
            # =
            # ray_a - ray_b
            # ------------------------------------------------

            delta_signed = (
                normalize_signed_deg(
                    ray_a
                    - ray_b
                )
            )


            # ------------------------------------------------
            # Resolve circular branch.
            #
            # Important for P5 <-> P9:
            # +5 deg modulo 360 may actually represent
            # approximately -355 deg on our unwrapped graph.
            # ------------------------------------------------

            delta_unwrapped = (
                unwrap_near(
                    delta_signed,
                    expected_delta,
                )
            )


            unwrapped_values.append(
                delta_unwrapped
            )


            raw_records.append(
                {
                    "index": int(
                        number
                    ),

                    "pixel_a": [
                        float(xa),
                        float(ya),
                    ],

                    "pixel_b": [
                        float(xb),
                        float(yb),
                    ],

                    "ray_a_deg": float(
                        ray_a
                    ),

                    "ray_b_deg": float(
                        ray_b
                    ),

                    "delta_signed_deg": float(
                        delta_signed
                    ),

                    "delta_unwrapped_deg": float(
                        delta_unwrapped
                    ),
                }
            )


        # ----------------------------------------------------
        # Reject manual click outliers
        # ----------------------------------------------------

        stats = robust_pair(
            unwrapped_values
        )

        inlier_mask = stats.pop(
            "inlier_mask"
        )


        for (
            record,
            keep,
        ) in zip(
            raw_records,
            inlier_mask,
        ):

            record[
                "inlier"
            ] = bool(
                keep
            )


        measured_delta = float(
            stats[
                "center_unwrapped_deg"
            ]
        )


        nominal_error = (
            measured_delta
            - expected_delta
        )


        stats[
            "expected_physical_delta_deg"
        ] = float(
            expected_delta
        )

        stats[
            "difference_from_physical_deg"
        ] = float(
            nominal_error
        )

        stats[
            "marks"
        ] = raw_records


        measurements[
            key
        ] = stats


        print(
            f"{key:>5} "
            f"| delta="
            f"{measured_delta:9.3f}° "
            f"| nominal="
            f"{expected_delta:8.3f}° "
            f"| diff="
            f"{nominal_error:+7.3f}° "
            f"| inliers="
            f"{stats['inlier_count']:2d}/"
            f"{stats['raw_count']:2d} "
            f"| std="
            f"{stats['std_deg']:.3f}° "
            f"| maxdev="
            f"{stats['max_deviation_deg']:.3f}°"
        )


    # ========================================================
    # Raw loop closure BEFORE least squares
    #
    # Cycle:
    #
    # P1 -> P2 -> P3 -> P4 -> P5
    #    -> P9 -> P8 -> P7 -> P6 -> P1
    # ========================================================

    m = {
        key: float(
            value[
                "center_unwrapped_deg"
            ]
        )
        for (
            key,
            value,
        ) in measurements.items()
    }


    raw_loop_closure = (
        m["1-2"]
        + m["2-3"]
        + m["3-4"]
        + m["4-5"]

        + m["5-9"]

        - m["8-9"]
        - m["7-8"]
        - m["6-7"]
        - m["1-6"]
    )


    # ========================================================
    # Least-squares graph solve
    #
    # Anchor:
    #     P1 = 0 degrees
    #
    # Unknowns:
    #     P2 ... P9
    # ========================================================

    variable_presets = list(
        range(
            2,
            10,
        )
    )

    variable_index = {
        preset: index
        for (
            index,
            preset,
        ) in enumerate(
            variable_presets
        )
    }


    rows = []

    targets = []


    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )

        delta = float(
            measurements[
                key
            ][
                "center_unwrapped_deg"
            ]
        )


        row = np.zeros(
            8,
            dtype=float,
        )


        if preset_a != 1:

            row[
                variable_index[
                    preset_a
                ]
            ] -= 1.0


        if preset_b != 1:

            row[
                variable_index[
                    preset_b
                ]
            ] += 1.0


        rows.append(
            row
        )

        targets.append(
            delta
        )


    A = np.asarray(
        rows,
        dtype=float,
    )

    b = np.asarray(
        targets,
        dtype=float,
    )


    (
        solution,
        _residual_array,
        rank,
        _singular_values,
    ) = np.linalg.lstsq(
        A,
        b,
        rcond=None,
    )


    if int(rank) != 8:

        raise RuntimeError(
            f"Geometry graph rank="
            f"{rank}; expected 8"
        )


    raw_centers = {
        1: 0.0
    }


    for preset in (
        variable_presets
    ):

        raw_centers[
            preset
        ] = float(
            solution[
                variable_index[
                    preset
                ]
            ]
        )


    # ========================================================
    # Graph residuals
    #
    # DO NOT wrap these residuals.
    #
    # Since we intentionally solved an unwrapped graph,
    # a +/-360 degree mistake must remain visible.
    # ========================================================

    graph_residuals = {}

    graph_residual_values = []


    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )


        measured = float(
            measurements[
                key
            ][
                "center_unwrapped_deg"
            ]
        )


        predicted = (
            raw_centers[
                preset_b
            ]
            -
            raw_centers[
                preset_a
            ]
        )


        residual = float(
            predicted
            - measured
        )


        graph_residuals[
            key
        ] = {
            "measured_delta_deg": (
                measured
            ),

            "predicted_delta_deg": float(
                predicted
            ),

            "residual_deg": residual,
        }


        graph_residual_values.append(
            residual
        )


    graph_residual_values = (
        np.asarray(
            graph_residual_values,
            dtype=float,
        )
    )


    graph_rmse = float(
        np.sqrt(
            np.mean(
                np.square(
                    graph_residual_values
                )
            )
        )
    )


    graph_max_residual = float(
        np.max(
            np.abs(
                graph_residual_values
            )
        )
    )


    # ========================================================
    # Pair-level quality
    # ========================================================

    min_inlier_fraction = min(
        value[
            "inlier_fraction"
        ]
        for value
        in measurements.values()
    )


    max_pair_std = max(
        value[
            "std_deg"
        ]
        for value
        in measurements.values()
    )


    max_pair_deviation = max(
        value[
            "max_deviation_deg"
        ]
        for value
        in measurements.values()
    )


    max_physical_difference = max(
        abs(
            value[
                "difference_from_physical_deg"
            ]
        )
        for value
        in measurements.values()
    )


    # ========================================================
    # Candidate quality gate
    #
    # This DOES NOT prove final bearing accuracy.
    #
    # It only determines whether this calibration is
    # internally consistent enough to proceed to the
    # independent SAME-TARGET cross-preset validation.
    # ========================================================

    checks = {
        "graph_rank_8": (
            int(rank) == 8
        ),

        "min_pair_inlier_fraction_ge_0_60": (
            min_inlier_fraction
            >= 0.60
        ),

        "max_pair_std_le_1_deg": (
            max_pair_std
            <= 1.0
        ),

        "max_pair_deviation_le_2_deg": (
            max_pair_deviation
            <= 2.0
        ),

        "graph_rmse_le_1_deg": (
            graph_rmse
            <= 1.0
        ),

        "graph_max_residual_le_2_deg": (
            graph_max_residual
            <= 2.0
        ),

        "raw_loop_closure_le_3_deg": (
            abs(
                raw_loop_closure
            )
            <= 3.0
        ),

        # Physical bearings are not the solved result.
        # This is only a gross sanity gate against
        # wrong correspondences / wrong circular branch.
        "pair_delta_within_12_deg_of_nominal": (
            max_physical_difference
            <= 12.0
        ),
    }


    quality_ok = all(
        checks.values()
    )


    if quality_ok:

        status = (
            "PASS_FOR_CROSS_PRESET_VALIDATION"
        )

    else:

        status = (
            "REVIEW_REQUIRED"
        )


    # ========================================================
    # Final relative optical center map
    # ========================================================

    presets = {}


    for preset in range(
        1,
        10,
    ):

        unwrapped = float(
            raw_centers[
                preset
            ]
        )

        presets[
            str(
                preset
            )
        ] = {
            "center_relative_deg": (
                normalize_deg(
                    unwrapped
                )
            ),

            "center_unwrapped_deg": (
                unwrapped
            ),

            "physical_nominal_deg": float(
                PRESET_BEARING_DEG[
                    preset
                ]
            ),
        }


    # ========================================================
    # Output
    # ========================================================

    payload = {
        "format": (
            "smart-fire-preset-geometry-v1"
        ),

        "solver_version": 2,

        "method": (
            "manual-overlap-marks-"
            "calibrated-undistorted-rays-"
            "unwrapped-graph-least-squares"
        ),

        "runtime_image_matching": False,

        "site_dir": str(
            site_dir
        ),

        "anchor_preset": 1,

        "anchor_relative_deg": 0.0,

        "frame_width": int(
            width
        ),

        "frame_height": int(
            height
        ),

        "presets": presets,

        "pair_measurements": (
            measurements
        ),

        "raw_loop_closure_deg": float(
            raw_loop_closure
        ),

        "graph_residuals": (
            graph_residuals
        ),

        "metrics": {
            "rank": int(
                rank
            ),

            "graph_rmse_deg": (
                graph_rmse
            ),

            "graph_max_residual_deg": (
                graph_max_residual
            ),

            "raw_loop_closure_deg": float(
                raw_loop_closure
            ),

            "min_pair_inlier_fraction": float(
                min_inlier_fraction
            ),

            "max_pair_std_deg": float(
                max_pair_std
            ),

            "max_pair_deviation_deg": float(
                max_pair_deviation
            ),

            "max_difference_from_physical_deg": float(
                max_physical_difference
            ),
        },

        "quality_checks": checks,

        "status": status,

        "important_note": (
            "PASS means internal calibration "
            "consistency only. Independent "
            "same-target cross-preset validation "
            "is still required."
        ),
    }


    output = (
        result_dir
        / "preset_geometry_candidate_v2.json"
    )


    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Console report
    # ========================================================

    print()
    print(
        "=" * 92
    )

    print(
        "SOLVED RELATIVE OPTICAL CENTERS"
    )

    print(
        "=" * 92
    )


    for preset in range(
        1,
        10,
    ):

        item = presets[
            str(
                preset
            )
        ]

        print(
            f"P{preset} "
            f"| relative="
            f"{item['center_relative_deg']:9.3f}° "
            f"| unwrapped="
            f"{item['center_unwrapped_deg']:9.3f}° "
            f"| nominal="
            f"{item['physical_nominal_deg']:7.3f}°"
        )


    print()
    print(
        "-" * 92
    )

    print(
        "QUALITY"
    )

    print(
        "-" * 92
    )


    print(
        f"Graph rank             : "
        f"{int(rank)}/8"
    )

    print(
        f"Graph RMSE             : "
        f"{graph_rmse:.4f}°"
    )

    print(
        f"Graph max residual     : "
        f"{graph_max_residual:.4f}°"
    )

    print(
        f"Raw loop closure       : "
        f"{raw_loop_closure:+.4f}°"
    )

    print(
        f"Min inlier fraction    : "
        f"{min_inlier_fraction:.3f}"
    )

    print(
        f"Max pair std           : "
        f"{max_pair_std:.4f}°"
    )

    print(
        f"Max pair deviation     : "
        f"{max_pair_deviation:.4f}°"
    )

    print(
        f"Max nominal difference : "
        f"{max_physical_difference:.4f}°"
    )


    print()
    print(
        "QUALITY CHECKS"
    )


    for (
        name,
        passed,
    ) in checks.items():

        print(
            f"  "
            f"{'PASS' if passed else 'FAIL'} "
            f"{name}"
        )


    print()
    print(
        f"RESULT : {status}"
    )

    print(
        f"SAVED  : {output}"
    )

    print(
        "=" * 92
    )


if __name__ == "__main__":
    main()
