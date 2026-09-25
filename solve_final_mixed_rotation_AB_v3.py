#!/usr/bin/env python3

import copy
import json
from pathlib import Path

import numpy as np

import solve_preset_rotation_v1 as core
import solve_final_rotation_bundle_AB_v2 as bundle


# ============================================================
# SOURCE DATA
# ============================================================

POS_A_ROOT = Path(
    Path(
        "/home/fire/final_session_A_path.txt"
    ).read_text().strip()
)

POS_B_ROOT = Path(
    Path(
        "/home/fire/final_session_B_path.txt"
    ).read_text().strip()
)

NEG_A_ROOT = Path(
    Path(
        "/home/fire/final_negative_A2_path.txt"
    ).read_text().strip()
)

NEG_B_ROOT = Path(
    Path(
        "/home/fire/final_negative_B2_path.txt"
    ).read_text().strip()
)


POS_A_MARKS = (
    POS_A_ROOT
    / "cross_preset_marks_FINAL_A.json"
)

POS_B_MARKS = (
    POS_B_ROOT
    / "cross_preset_marks_FINAL_B.json"
)

NEG_A_MARKS = (
    NEG_A_ROOT
    / "negative_side_marks_FINAL_A2.json"
)

NEG_B_MARKS = (
    NEG_B_ROOT
    / "negative_side_marks_FINAL_B2.json"
)


TRAIN_MIXED_FILE = Path(
    "/home/fire/final_mixed_train_marks_v3.json"
)

HOLDOUT_MIXED_FILE = Path(
    "/home/fire/final_mixed_holdout_marks_v3.json"
)

RESULT_FILE = (
    NEG_B_ROOT
    / "final_mixed_rotation_AB_v3_result.json"
)

FINAL_CANDIDATE = Path(
    "/opt/smart-fire-detection-v2/"
    "calibration/"
    "preset_rotation_candidate_MIXED_AB_v3.json"
)


POSITIVE_PAIRS = [
    "1-2",
    "2-3",
    "3-4",
    "4-5",
]

NEGATIVE_PAIRS = [
    "1-6",
    "6-7",
    "7-8",
    "8-9",
    "5-9",
]

ALL_PAIRS = [
    "1-2",
    "2-3",
    "3-4",
    "4-5",
    "1-6",
    "6-7",
    "7-8",
    "8-9",
    "5-9",
]


# ============================================================
# Helpers
# ============================================================

def read_json(path):

    if not path.exists():
        raise RuntimeError(
            f"Missing file: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def build_mixed_file(
    positive_file,
    negative_file,
    output_file,
    label,
):

    pos = read_json(
        positive_file
    )

    neg = read_json(
        negative_file
    )

    pairs = {}


    for key in POSITIVE_PAIRS:

        items = (
            pos.get(
                "pairs",
                {}
            ).get(
                key
            )
        )

        if not items:
            raise RuntimeError(
                f"{label}: "
                f"missing positive pair {key}"
            )

        pairs[key] = copy.deepcopy(
            items
        )


    for key in NEGATIVE_PAIRS:

        items = (
            neg.get(
                "pairs",
                {}
            ).get(
                key
            )
        )

        if not items:
            raise RuntimeError(
                f"{label}: "
                f"missing negative pair {key}"
            )

        pairs[key] = copy.deepcopy(
            items
        )


    payload = {
        "format":
            "smart-fire-final-mixed-marks-v3",

        "label":
            label,

        "positive_source":
            str(
                positive_file
            ),

        "negative_source":
            str(
                negative_file
            ),

        "near_field_negative_marks_used":
            False,

        "pairs":
            pairs,
    }


    output_file.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print(
        f"{label}_MIXED_FILE="
        f"{output_file}"
    )


    for key in ALL_PAIRS:

        print(
            f"  {key}: "
            f"{len(pairs[key])} marks"
        )


def evaluate_relative_rotation(
    train,
    holdout,
):

    print()
    print("=" * 118)
    print(
        "PAIRWISE A -> B TRANSFER DIAGNOSTIC"
    )
    print("=" * 118)

    results = {}


    for index, (a, b) in enumerate(
        core.PAIR_LIST,
        start=1,
    ):

        key = f"{a}-{b}"


        fit = (
            core.robust_relative_rotation(
                train[key],
                seed=(
                    81000
                    + index
                ),
            )
        )


        R = fit[
            "R_b_to_a"
        ]


        rays_a = np.asarray(
            [
                obs["ray_a"]
                for obs
                in holdout[key]
            ],
            dtype=float,
        )

        rays_b = np.asarray(
            [
                obs["ray_b"]
                for obs
                in holdout[key]
            ],
            dtype=float,
        )


        errors = (
            core.residual_angles_deg(
                R,
                rays_a,
                rays_b,
            )
        )


        median = float(
            np.median(
                errors
            )
        )

        p90 = float(
            np.percentile(
                errors,
                90,
            )
        )

        maximum = float(
            np.max(
                errors
            )
        )


        passed = (
            median <= 2.0
            and
            p90 <= 3.5
        )


        results[key] = {
            "median_deg":
                median,

            "p90_deg":
                p90,

            "max_deg":
                maximum,

            "passed":
                bool(
                    passed
                ),
        }


        print(
            f"{key:>5} "
            f"| train="
            f"{len(train[key]):3d} "
            f"| holdout="
            f"{len(holdout[key]):3d} "
            f"| median="
            f"{median:7.3f}° "
            f"| p90="
            f"{p90:7.3f}° "
            f"| max="
            f"{maximum:7.3f}° "
            f"| "
            f"{'PASS' if passed else 'REVIEW'}"
        )


    return results


def compact_global(
    evaluation,
):

    m = (
        evaluation[
            "global_metrics"
        ]
    )

    return {
        key: value
        for key, value
        in m.items()
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 118)
    print(
        "SMART FIRE FINAL MIXED "
        "GLOBAL RAW-RAY ROTATION v3"
    )
    print("=" * 118)

    print(
        f"POSITIVE TRAIN   : "
        f"{POS_A_ROOT}"
    )

    print(
        f"POSITIVE HOLDOUT : "
        f"{POS_B_ROOT}"
    )

    print(
        f"NEGATIVE TRAIN   : "
        f"{NEG_A_ROOT}"
    )

    print(
        f"NEGATIVE HOLDOUT : "
        f"{NEG_B_ROOT}"
    )

    print()
    print(
        "Positive pairs use original "
        "FINAL-A/B."
    )

    print(
        "Negative pairs use far-target "
        "FINAL-A2/B2 only."
    )

    print(
        "Old near-field negative marks "
        "are NOT used."
    )

    print()
    print(
        "Measured camera offset:"
    )

    print(
        "  horizontal PAN -> lens "
        "= 0.033 m"
    )

    print(
        "  vertical axis -> lens "
        "= 0.057 m"
    )

    print(
        "Offsets are recorded only; "
        "not injected into this pure-rotation "
        "far-target model."
    )

    print("=" * 118)


    #
    # Construct completely explicit
    # mixed datasets.
    #
    build_mixed_file(
        POS_A_MARKS,
        NEG_A_MARKS,
        TRAIN_MIXED_FILE,
        "TRAIN",
    )

    print()

    build_mixed_file(
        POS_B_MARKS,
        NEG_B_MARKS,
        HOLDOUT_MIXED_FILE,
        "HOLDOUT",
    )


    #
    # Calibrated camera rays.
    #
    K, D = (
        core.load_intrinsics()
    )


    train = (
        core.load_mark_file(
            TRAIN_MIXED_FILE,
            "FINAL_MIXED_TRAIN",
            K,
            D,
        )
    )

    holdout = (
        core.load_mark_file(
            HOLDOUT_MIXED_FILE,
            "FINAL_MIXED_HOLDOUT",
            K,
            D,
        )
    )


    #
    # --------------------------------------------------------
    # PHASE 1:
    # Before global solve, verify that a relative
    # rotation learned from A/A2 transfers to B/B2.
    # --------------------------------------------------------
    #
    pair_transfer = (
        evaluate_relative_rotation(
            train,
            holdout,
        )
    )


    #
    # --------------------------------------------------------
    # PHASE 2:
    # Global raw-ray bundle TRAIN ONLY.
    # --------------------------------------------------------
    #
    edges = (
        bundle.fit_edges(
            train
        )
    )


    Q_initial = (
        bundle.make_initial_Q(
            edges
        )
    )


    solution = (
        bundle.solve_bundle(
            train,
            Q_initial,
        )
    )


    Q_train = (
        solution[
            "Q"
        ]
    )


    print()
    print("=" * 118)
    print(
        "GLOBAL BUNDLE OPTIMIZER"
    )
    print("=" * 118)

    print(
        f"success    : "
        f"{solution['success']}"
    )

    print(
        f"message    : "
        f"{solution['message']}"
    )

    print(
        f"nfev       : "
        f"{solution['nfev']}"
    )

    print(
        f"cost       : "
        f"{solution['cost']:.8f}"
    )

    print(
        f"optimality : "
        f"{solution['optimality']:.8e}"
    )


    print()
    print(
        "SOLVED RELATIVE OPTICAL AXES"
    )


    for preset in range(
        1,
        10,
    ):

        m = (
            core.optical_axis_metrics(
                Q_train[
                    preset
                ]
            )
        )

        print(
            f"P{preset} "
            f"| az="
            f"{m['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{m['elevation_deg']:+8.3f}°"
        )


    #
    # TRAIN evaluation.
    #
    train_eval = (
        core.evaluate_dataset(
            train,
            Q_train,
        )
    )


    bundle.print_evaluation(
        "MIXED TRAIN — A + A2",
        train_eval,
    )


    #
    # Independent holdout evaluation.
    #
    holdout_eval = (
        core.evaluate_dataset(
            holdout,
            Q_train,
        )
    )


    bundle.print_evaluation(
        "MIXED INDEPENDENT HOLDOUT — B + B2",
        holdout_eval,
    )


    passed, pair_checks = (
        bundle.production_gate(
            holdout_eval
        )
    )


    print()
    print("=" * 118)
    print(
        "FINAL MIXED PRODUCTION GATE"
    )
    print("=" * 118)


    for key in ALL_PAIRS:

        print(
            f"{key:>5}: "
            f"{'PASS' if pair_checks[key] else 'FAIL'}"
        )


    print()
    print(
        "Global median <= 1.50°"
    )

    print(
        "Global P90    <= 2.50°"
    )

    print(
        "Pair median   <= 2.00°"
    )

    print(
        "Pair P90      <= 3.50°"
    )

    print()


    if passed:

        print(
            "MIXED_HOLDOUT=PASS"
        )

    else:

        print(
            "MIXED_HOLDOUT=FAIL"
        )


    #
    # Save holdout result regardless of pass/fail.
    #
    payload = {
        "format":
            "smart-fire-final-mixed-rotation-AB-v3",

        "positive_train":
            str(
                POS_A_MARKS
            ),

        "positive_holdout":
            str(
                POS_B_MARKS
            ),

        "negative_train":
            str(
                NEG_A_MARKS
            ),

        "negative_holdout":
            str(
                NEG_B_MARKS
            ),

        "near_field_negative_data_used":
            False,

        "physical_lens_offsets_m": {
            "horizontal_from_pan_axis":
                0.033,

            "vertical_from_axis":
                0.057,

            "used_in_solver":
                False,
        },

        "pair_transfer":
            pair_transfer,

        "optimizer": {
            "success":
                solution[
                    "success"
                ],

            "message":
                solution[
                    "message"
                ],

            "cost":
                solution[
                    "cost"
                ],

            "optimality":
                solution[
                    "optimality"
                ],

            "nfev":
                solution[
                    "nfev"
                ],
        },

        "train_evaluation":
            train_eval,

        "holdout_evaluation":
            holdout_eval,

        "production_pair_checks":
            pair_checks,

        "production_holdout_pass":
            bool(
                passed
            ),
    }


    RESULT_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print(
        f"RESULT_SAVED={RESULT_FILE}"
    )


    #
    # --------------------------------------------------------
    # HOLDOUT must pass before A+B refit.
    # --------------------------------------------------------
    #
    if not passed:

        print()
        print(
            "FINAL_MIXED_RESULT="
            "HOLDOUT_FAILED"
        )

        print(
            "Runtime geometry remains unchanged."
        )

        return


    #
    # --------------------------------------------------------
    # PHASE 3:
    # Refit TRAIN + HOLDOUT only after independent
    # holdout has passed.
    # --------------------------------------------------------
    #
    combined = (
        core.merge_observations(
            [
                train,
                holdout,
            ]
        )
    )


    final_solution = (
        bundle.solve_bundle(
            combined,
            Q_train,
        )
    )


    Q_final = (
        final_solution[
            "Q"
        ]
    )


    final_train_eval = (
        core.evaluate_dataset(
            train,
            Q_final,
        )
    )

    final_holdout_eval = (
        core.evaluate_dataset(
            holdout,
            Q_final,
        )
    )


    print()
    print("=" * 118)
    print(
        "FINAL A+A2+B+B2 REFIT"
    )
    print("=" * 118)


    for preset in range(
        1,
        10,
    ):

        m = (
            core.optical_axis_metrics(
                Q_final[
                    preset
                ]
            )
        )

        print(
            f"P{preset} "
            f"| az="
            f"{m['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{m['elevation_deg']:+8.3f}°"
        )


    bundle.print_evaluation(
        "POST-REFIT TRAIN",
        final_train_eval,
    )

    bundle.print_evaluation(
        "POST-REFIT HOLDOUT",
        final_holdout_eval,
    )


    final_payload = {
        "format":
            "smart-fire-preset-rotation-MIXED-AB-v3",

        "status":
            "PASS_CANDIDATE_NOT_INSTALLED",

        "model":
            "calibrated-global-raw-ray-rotation",

        "reference_preset":
            1,

        "runtime_image_matching":
            False,

        "near_field_negative_marks_used":
            False,

        "physical_lens_offsets_m": {
            "horizontal_from_pan_axis":
                0.033,

            "vertical_from_axis":
                0.057,

            "used_in_solver":
                False,
        },

        "presets":
            bundle.serialize_Q(
                Q_final
            ),

        "independent_holdout_gate":
            {
                "passed":
                    True,

                "pairs":
                    pair_checks,
            },

        "post_refit_train":
            final_train_eval,

        "post_refit_holdout":
            final_holdout_eval,

        "note":
            (
                "Relative geometry only. "
                "True North offset is not "
                "included yet."
            ),
    }


    FINAL_CANDIDATE.write_text(
        json.dumps(
            final_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print("=" * 118)

    print(
        "FINAL_MIXED_RESULT="
        "PASS_CANDIDATE_NOT_INSTALLED"
    )

    print(
        f"CANDIDATE="
        f"{FINAL_CANDIDATE}"
    )

    print("=" * 118)


if __name__ == "__main__":
    main()
