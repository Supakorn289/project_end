#!/usr/bin/env python3

import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

import solve_preset_rotation_v1 as core


# ============================================================
# FINAL-A / FINAL-B ONLY
# ============================================================

A_ROOT = Path(
    Path(
        "/home/fire/final_session_A_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

B_ROOT = Path(
    Path(
        "/home/fire/final_session_B_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

A_MARKS = (
    A_ROOT
    / "cross_preset_marks_FINAL_A.json"
)

B_MARKS = (
    B_ROOT
    / "cross_preset_marks_FINAL_B.json"
)

OUTPUT = (
    B_ROOT
    / "final_AB_bundle_holdout_v2.json"
)


PAIR_LIST = list(
    core.PAIR_LIST
)

VARIABLE_PRESETS = [
    2, 3, 4, 5,
    6, 7, 8, 9,
]


# ============================================================
# SO(3)
# ============================================================

def exp_rotation(v):

    R, _ = cv2.Rodrigues(
        np.asarray(
            v,
            dtype=np.float64,
        ).reshape(3, 1)
    )

    return R


def rotation_angle_deg(R):

    rvec, _ = cv2.Rodrigues(
        np.asarray(
            R,
            dtype=np.float64,
        )
    )

    return math.degrees(
        float(
            np.linalg.norm(
                rvec
            )
        )
    )


# ============================================================
# INITIALIZATION
#
# Important:
# Do NOT initialize through 7-8.
#
# Positive side:
# P1 -> P2 -> P3 -> P4 -> P5 -> P9 -> P8
#
# Negative side:
# P1 -> P6 -> P7
#
# 7-8 becomes closure evidence, not initialization authority.
# ============================================================

def fit_edges(
    observations,
):

    edges = {}

    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        edges[key] = (
            core.robust_relative_rotation(
                observations[key],
                seed=(
                    20000
                    + a * 100
                    + b
                ),
            )
        )

    return edges


def make_initial_Q(
    edges,
):

    Q = {
        1: np.eye(
            3,
            dtype=np.float64,
        )
    }


    #
    # Positive chain
    #
    for a, b in [
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 9),
    ]:

        key = f"{a}-{b}"

        R_b_to_a = (
            edges[key][
                "R_b_to_a"
            ]
        )

        Q[b] = (
            Q[a]
            @ R_b_to_a
        )


    #
    # Edge 8-9 contains:
    #
    # ray_8 ~= R_9_to_8 @ ray_9
    #
    # Q9 = Q8 @ R_9_to_8
    #
    # therefore:
    #
    # Q8 = Q9 @ R_9_to_8.T
    #
    R_9_to_8 = (
        edges["8-9"][
            "R_b_to_a"
        ]
    )

    Q[8] = (
        Q[9]
        @ R_9_to_8.T
    )


    #
    # Negative chain
    #
    for a, b in [
        (1, 6),
        (6, 7),
    ]:

        key = f"{a}-{b}"

        R_b_to_a = (
            edges[key][
                "R_b_to_a"
            ]
        )

        Q[b] = (
            Q[a]
            @ R_b_to_a
        )


    missing = [
        p
        for p in range(1, 10)
        if p not in Q
    ]

    if missing:

        raise RuntimeError(
            f"Initial Q missing: "
            f"{missing}"
        )


    return Q


# ============================================================
# PARAMETERIZATION
#
# Q_i = Q_initial_i @ Exp(delta_i)
# ============================================================

def Q_from_x(
    x,
    Q_initial,
):

    Q = {
        1: np.eye(
            3,
            dtype=np.float64,
        )
    }

    for index, preset in enumerate(
        VARIABLE_PRESETS
    ):

        delta = x[
            3 * index:
            3 * index + 3
        ]

        Q[preset] = (
            Q_initial[preset]
            @ exp_rotation(
                delta
            )
        )

    return Q


# ============================================================
# GLOBAL RAW-RAY RESIDUAL
#
# Every individual MARK enters optimization.
#
# Pair normalization prevents pairs with many marks
# from dominating solely because they have larger N.
# ============================================================

def build_residual_function(
    observations,
    Q_initial,
):

    pair_scales = {}

    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        n = len(
            observations[key]
        )

        if n < 3:

            raise RuntimeError(
                f"{key}: only {n} marks"
            )

        #
        # Each edge receives approximately equal
        # total optimization influence.
        #
        pair_scales[key] = math.sqrt(
            20.0
            / float(n)
        )


    def residual(
        x,
    ):

        Q = Q_from_x(
            x,
            Q_initial,
        )

        values = []


        for a, b in PAIR_LIST:

            key = f"{a}-{b}"

            scale = (
                pair_scales[key]
            )


            for obs in observations[key]:

                wa = (
                    Q[a]
                    @ obs["ray_a"]
                )

                wb = (
                    Q[b]
                    @ obs["ray_b"]
                )


                #
                # Both are unit vectors.
                #
                # Vector difference is approximately
                # angular error in radians for small angles.
                #
                diff = (
                    wa
                    - wb
                )


                values.extend(
                    (
                        scale
                        * diff
                    ).tolist()
                )


        return np.asarray(
            values,
            dtype=np.float64,
        )


    return residual


# ============================================================
# GLOBAL BUNDLE SOLVE
# ============================================================

def solve_bundle(
    observations,
    Q_initial,
):

    x0 = np.zeros(
        3
        * len(
            VARIABLE_PRESETS
        ),
        dtype=np.float64,
    )


    residual_fn = (
        build_residual_function(
            observations,
            Q_initial,
        )
    )


    result = least_squares(
        residual_fn,
        x0,

        method="trf",

        #
        # Robust against occasional MARK outliers.
        #
        loss="soft_l1",

        #
        # ~1 degree angular scale.
        #
        f_scale=math.radians(
            1.0
        ),

        max_nfev=5000,

        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
    )


    Q = Q_from_x(
        result.x,
        Q_initial,
    )


    movements = {}


    for index, preset in enumerate(
        VARIABLE_PRESETS
    ):

        delta = result.x[
            3 * index:
            3 * index + 3
        ]

        movements[
            preset
        ] = math.degrees(
            float(
                np.linalg.norm(
                    delta
                )
            )
        )


    return {
        "Q": Q,

        "success": bool(
            result.success
        ),

        "message": str(
            result.message
        ),

        "cost": float(
            result.cost
        ),

        "optimality": float(
            result.optimality
        ),

        "nfev": int(
            result.nfev
        ),

        "movement_deg": (
            movements
        ),
    }


# ============================================================
# PRINT
# ============================================================

def print_evaluation(
    title,
    evaluation,
):

    print()
    print("=" * 116)
    print(title)
    print("=" * 116)


    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            evaluation[
                "pairs"
            ][key]
        )


        print(
            f"{key:>5} "
            f"| n="
            f"{item['target_count']:3d} "
            f"| median az="
            f"{item['median_abs_azimuth_error_deg']:7.3f}° "
            f"| p90 az="
            f"{item['p90_abs_azimuth_error_deg']:7.3f}° "
            f"| max="
            f"{item['max_abs_azimuth_error_deg']:7.3f}° "
            f"| <=2°="
            f"{item['fraction_le_2deg']*100:5.1f}% "
            f"| median3D="
            f"{item['median_3d_error_deg']:7.3f}° "
            f"| {item['status']}"
        )


    m = evaluation[
        "global_metrics"
    ]


    print()
    print("GLOBAL")

    print(
        f"Targets       : "
        f"{m['target_count']}"
    )

    print(
        f"Pairs P/R/F   : "
        f"{m['pass_pairs']}/"
        f"{m['review_pairs']}/"
        f"{m['fail_pairs']}"
    )

    print(
        f"Median abs az : "
        f"{m['median_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Mean abs az   : "
        f"{m['mean_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"P90 abs az    : "
        f"{m['p90_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Max abs az    : "
        f"{m['max_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Median 3D     : "
        f"{m['median_3d_error_deg']:.4f}°"
    )

    print(
        f"P90 3D        : "
        f"{m['p90_3d_error_deg']:.4f}°"
    )


# ============================================================
# PRODUCTION GATE
# ============================================================

def production_gate(
    evaluation,
):

    metrics = (
        evaluation[
            "global_metrics"
        ]
    )


    pair_checks = {}


    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            evaluation[
                "pairs"
            ][key]
        )


        ok = (
            item[
                "median_abs_azimuth_error_deg"
            ]
            <= 2.0
            and
            item[
                "p90_abs_azimuth_error_deg"
            ]
            <= 3.5
        )


        pair_checks[key] = bool(
            ok
        )


    global_ok = (
        metrics[
            "median_abs_azimuth_error_deg"
        ]
        <= 1.50

        and

        metrics[
            "p90_abs_azimuth_error_deg"
        ]
        <= 2.50

        and

        all(
            pair_checks.values()
        )
    )


    return (
        bool(global_ok),
        pair_checks,
    )


# ============================================================
# SERIALIZE Q
# ============================================================

def serialize_Q(
    Q,
):

    output = {}


    for preset in range(
        1,
        10,
    ):

        metrics = (
            core.optical_axis_metrics(
                Q[preset]
            )
        )


        output[str(preset)] = {
            "camera_to_reference_rotation":
                Q[preset].tolist(),

            **metrics,
        }


    return output


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 116)

    print(
        "SMART FIRE FINAL A/B "
        "GLOBAL RAW-RAY BUNDLE SOLVER v2"
    )

    print("=" * 116)

    print(
        f"TRAIN A   : {A_ROOT}"
    )

    print(
        f"HOLDOUT B : {B_ROOT}"
    )

    print(
        "OLD DATA  : IGNORED COMPLETELY"
    )

    print(
        "MODEL     : calibrated central-camera "
        "3-D rotation bundle"
    )

    print(
        "7-8       : NOT used as initialization authority"
    )

    print("=" * 116)


    if not A_MARKS.exists():
        raise RuntimeError(
            f"Missing A marks: {A_MARKS}"
        )

    if not B_MARKS.exists():
        raise RuntimeError(
            f"Missing B marks: {B_MARKS}"
        )


    K, D = core.load_intrinsics()


    A = core.load_mark_file(
        A_MARKS,
        "FINAL_A",
        K,
        D,
    )

    B = core.load_mark_file(
        B_MARKS,
        "FINAL_B",
        K,
        D,
    )


    #
    # Independent edge rotations are used ONLY
    # to construct a sane starting point.
    #
    A_edges = fit_edges(
        A
    )


    Q_initial = make_initial_Q(
        A_edges
    )


    print()
    print(
        "INITIAL OPTICAL AXES"
    )

    for preset in range(
        1,
        10,
    ):

        m = core.optical_axis_metrics(
            Q_initial[preset]
        )

        print(
            f"P{preset} "
            f"| az="
            f"{m['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{m['elevation_deg']:+8.3f}°"
        )


    #
    # Raw-ray global optimization.
    #
    solution = solve_bundle(
        A,
        Q_initial,
    )


    Q = solution[
        "Q"
    ]


    print()
    print("=" * 116)

    print(
        "BUNDLE OPTIMIZER"
    )

    print("=" * 116)

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
        "ROTATION MOVEMENT FROM INITIALIZATION"
    )


    for preset in VARIABLE_PRESETS:

        print(
            f"P{preset}: "
            f"{solution['movement_deg'][preset]:.4f}°"
        )


    print()
    print(
        "SOLVED OPTICAL AXES"
    )


    for preset in range(
        1,
        10,
    ):

        m = core.optical_axis_metrics(
            Q[preset]
        )

        print(
            f"P{preset} "
            f"| az="
            f"{m['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{m['elevation_deg']:+8.3f}°"
        )


    #
    # Evaluate A itself.
    #
    train_eval = (
        core.evaluate_dataset(
            A,
            Q,
        )
    )


    print_evaluation(
        "FINAL-A — TRAINING RESIDUAL AFTER GLOBAL BUNDLE",
        train_eval,
    )


    #
    # IMPORTANT:
    # B has never been used by optimizer.
    #
    holdout_eval = (
        core.evaluate_dataset(
            B,
            Q,
        )
    )


    print_evaluation(
        "FINAL-B — INDEPENDENT HOLDOUT",
        holdout_eval,
    )


    passed, pair_checks = (
        production_gate(
            holdout_eval
        )
    )


    print()
    print("=" * 116)

    print(
        "PRODUCTION GATE"
    )

    print("=" * 116)


    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        print(
            f"{key:>5}: "
            f"{'PASS' if pair_checks[key] else 'FAIL'}"
        )


    print()

    print(
        "GLOBAL MEDIAN LIMIT : <= 1.50°"
    )

    print(
        "GLOBAL P90 LIMIT    : <= 2.50°"
    )

    print(
        "PAIR MEDIAN LIMIT   : <= 2.00°"
    )

    print(
        "PAIR P90 LIMIT      : <= 3.50°"
    )


    print()

    print(
        "FINAL_BUNDLE_HOLDOUT="
        + (
            "PASS"
            if passed
            else "FAIL"
        )
    )


    payload = {
        "format":
            "smart-fire-final-AB-global-ray-bundle-v2",

        "model":
            "central-camera-global-raw-ray-rotation",

        "train_root":
            str(A_ROOT),

        "holdout_root":
            str(B_ROOT),

        "train_marks":
            str(A_MARKS),

        "holdout_marks":
            str(B_MARKS),

        "old_data_used":
            False,

        "optimizer": {
            "success":
                solution["success"],

            "message":
                solution["message"],

            "nfev":
                solution["nfev"],

            "cost":
                solution["cost"],

            "optimality":
                solution["optimality"],

            "movement_deg":
                solution["movement_deg"],
        },

        "presets":
            serialize_Q(Q),

        "train_evaluation":
            train_eval,

        "holdout_evaluation":
            holdout_eval,

        "production_pair_checks":
            pair_checks,

        "production_holdout_pass":
            passed,
    }


    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print(
        f"SAVED : {OUTPUT}"
    )

    print("=" * 116)


if __name__ == "__main__":
    main()
