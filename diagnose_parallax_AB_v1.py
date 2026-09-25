#!/usr/bin/env python3

import json
import math
from pathlib import Path

import cv2
import numpy as np

import solve_preset_rotation_v1 as core


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
    / "parallax_diagnostic_AB_v1.json"
)

PAIR_LIST = list(
    core.PAIR_LIST
)

FOCUS_PAIRS = {
    "6-7",
    "7-8",
    "8-9",
    "5-9",
}

ESSENTIAL_THRESHOLD = 0.010


def percentile(values, q):

    values = np.asarray(
        values,
        dtype=float,
    )

    if len(values) == 0:
        return float("nan")

    return float(
        np.percentile(
            values,
            q,
        )
    )


def median(values):

    values = np.asarray(
        values,
        dtype=float,
    )

    if len(values) == 0:
        return float("nan")

    return float(
        np.median(
            values
        )
    )


def normalized_points(
    observations,
):

    points_a = []
    points_b = []

    for obs in observations:

        ra = np.asarray(
            obs["ray_a"],
            dtype=float,
        )

        rb = np.asarray(
            obs["ray_b"],
            dtype=float,
        )

        points_a.append(
            [
                ra[0] / ra[2],
                ra[1] / ra[2],
            ]
        )

        points_b.append(
            [
                rb[0] / rb[2],
                rb[1] / rb[2],
            ]
        )

    return (
        np.asarray(
            points_a,
            dtype=np.float64,
        ),
        np.asarray(
            points_b,
            dtype=np.float64,
        ),
    )


def split_essential_candidates(
    E,
):

    if E is None:
        return []

    E = np.asarray(
        E,
        dtype=np.float64,
    )

    if E.shape == (3, 3):
        return [E]

    if (
        E.ndim == 2
        and
        E.shape[1] == 3
        and
        E.shape[0] % 3 == 0
    ):

        return [
            E[i:i + 3, :]
            for i in range(
                0,
                E.shape[0],
                3,
            )
        ]

    return []


def sampson_proxy_deg(
    E,
    points_b,
    points_a,
):

    x1 = np.column_stack(
        [
            points_b,
            np.ones(
                len(points_b)
            ),
        ]
    )

    x2 = np.column_stack(
        [
            points_a,
            np.ones(
                len(points_a)
            ),
        ]
    )

    Ex1 = (
        E
        @ x1.T
    ).T

    Etx2 = (
        E.T
        @ x2.T
    ).T

    numerator = np.sum(
        x2
        * Ex1,
        axis=1,
    )

    denominator = (
        Ex1[:, 0] ** 2
        + Ex1[:, 1] ** 2
        + Etx2[:, 0] ** 2
        + Etx2[:, 1] ** 2
    )

    denominator = np.maximum(
        denominator,
        1e-15,
    )

    sampson = (
        numerator ** 2
        / denominator
    )

    distance = np.sqrt(
        sampson
    )

    #
    # Approximate angular proxy in calibrated
    # normalized-image coordinates.
    #
    return np.degrees(
        np.arctan(
            distance
        )
    )


def triangulation_reprojection(
    R,
    t,
    points_b,
    points_a,
):

    P_b = np.hstack(
        [
            np.eye(
                3,
                dtype=np.float64,
            ),
            np.zeros(
                (3, 1),
                dtype=np.float64,
            ),
        ]
    )

    P_a = np.hstack(
        [
            R,
            t.reshape(3, 1),
        ]
    )

    X4 = cv2.triangulatePoints(
        P_b,
        P_a,
        points_b.T,
        points_a.T,
    )

    errors = []
    positive = 0
    valid = 0

    for i in range(
        X4.shape[1]
    ):

        w = float(
            X4[3, i]
        )

        if abs(w) < 1e-12:
            continue

        Xb = (
            X4[:3, i]
            / w
        )

        Xa = (
            R
            @ Xb
            + t.reshape(3)
        )

        if (
            not np.all(
                np.isfinite(Xb)
            )
            or
            not np.all(
                np.isfinite(Xa)
            )
        ):
            continue

        valid += 1

        if (
            Xb[2] > 0.0
            and
            Xa[2] > 0.0
        ):
            positive += 1

        observed_b = np.array(
            [
                points_b[i, 0],
                points_b[i, 1],
                1.0,
            ],
            dtype=float,
        )

        observed_b /= np.linalg.norm(
            observed_b
        )

        observed_a = np.array(
            [
                points_a[i, 0],
                points_a[i, 1],
                1.0,
            ],
            dtype=float,
        )

        observed_a /= np.linalg.norm(
            observed_a
        )

        predicted_b = (
            Xb
            / np.linalg.norm(
                Xb
            )
        )

        predicted_a = (
            Xa
            / np.linalg.norm(
                Xa
            )
        )

        error_b = (
            core.angle_between_deg(
                observed_b,
                predicted_b,
            )
        )

        error_a = (
            core.angle_between_deg(
                observed_a,
                predicted_a,
            )
        )

        errors.append(
            0.5
            * (
                error_a
                + error_b
            )
        )

    positive_fraction = (
        float(
            positive
            / valid
        )
        if valid > 0
        else 0.0
    )

    return {
        "valid_count": int(
            valid
        ),

        "positive_depth_count": int(
            positive
        ),

        "positive_depth_fraction":
            positive_fraction,

        "median_reprojection_deg":
            median(errors),

        "p90_reprojection_deg":
            percentile(
                errors,
                90,
            ),

        "max_reprojection_deg":
            float(
                max(errors)
            )
            if errors
            else float("nan"),
    }


def fit_pure_rotation(
    observations,
    seed,
):

    fit = (
        core.robust_relative_rotation(
            observations,
            seed=seed,
        )
    )

    R = fit[
        "R_b_to_a"
    ]

    A = np.asarray(
        [
            obs["ray_a"]
            for obs in observations
        ],
        dtype=float,
    )

    B = np.asarray(
        [
            obs["ray_b"]
            for obs in observations
        ],
        dtype=float,
    )

    errors = (
        core.residual_angles_deg(
            R,
            A,
            B,
        )
    )

    return {
        "R": R,

        "median_deg":
            float(
                np.median(
                    errors
                )
            ),

        "p90_deg":
            float(
                np.percentile(
                    errors,
                    90,
                )
            ),

        "max_deg":
            float(
                np.max(
                    errors
                )
            ),

        "inlier_count":
            int(
                fit[
                    "inlier_count"
                ]
            ),

        "total_count":
            int(
                fit[
                    "total_count"
                ]
            ),

        "inlier_fraction":
            float(
                fit[
                    "inlier_fraction"
                ]
            ),
    }


def fit_essential(
    observations,
):

    points_a, points_b = (
        normalized_points(
            observations
        )
    )

    I = np.eye(
        3,
        dtype=np.float64,
    )

    E_all, mask = (
        cv2.findEssentialMat(
            points_b,
            points_a,
            I,
            method=cv2.RANSAC,
            prob=0.9999,
            threshold=(
                ESSENTIAL_THRESHOLD
            ),
        )
    )

    candidates = (
        split_essential_candidates(
            E_all
        )
    )

    if not candidates:

        return None

    if mask is None:

        mask = np.ones(
            (
                len(points_a),
                1,
            ),
            dtype=np.uint8,
        )

    best = None

    for E in candidates:

        pose_mask = (
            mask.copy()
        )

        try:

            count, R, t, recovered_mask = (
                cv2.recoverPose(
                    E,
                    points_b,
                    points_a,
                    I,
                    mask=pose_mask,
                )
            )

        except cv2.error:
            continue

        t = t.reshape(3)

        t_norm = float(
            np.linalg.norm(
                t
            )
        )

        if t_norm <= 0.0:
            continue

        t = (
            t
            / t_norm
        )

        sampson = (
            sampson_proxy_deg(
                E,
                points_b,
                points_a,
            )
        )

        tri = (
            triangulation_reprojection(
                R,
                t,
                points_b,
                points_a,
            )
        )

        essential_inlier_fraction = (
            float(
                np.count_nonzero(
                    mask
                )
                / len(points_a)
            )
        )

        recovered_fraction = (
            float(
                np.count_nonzero(
                    recovered_mask
                )
                / len(points_a)
            )
            if recovered_mask
            is not None
            else 0.0
        )

        candidate = {
            "E": E,
            "R": R,
            "t": t,

            "recover_pose_count":
                int(count),

            "essential_inlier_fraction":
                essential_inlier_fraction,

            "recover_pose_fraction":
                recovered_fraction,

            "sampson_median_deg":
                float(
                    np.median(
                        sampson
                    )
                ),

            "sampson_p90_deg":
                float(
                    np.percentile(
                        sampson,
                        90,
                    )
                ),

            "sampson_max_deg":
                float(
                    np.max(
                        sampson
                    )
                ),

            **tri,
        }

        score = (
            candidate[
                "recover_pose_count"
            ],

            -candidate[
                "sampson_median_deg"
            ],

            -candidate[
                "median_reprojection_deg"
            ],
        )

        if (
            best is None
            or
            score > best[
                "_score"
            ]
        ):

            candidate[
                "_score"
            ] = score

            best = candidate

    if best is None:
        return None

    best.pop(
        "_score",
        None,
    )

    return best


def classify(
    pure,
    essential,
):

    #
    # Rotation model already sufficient.
    #
    if (
        pure["median_deg"] <= 1.50
        and
        pure["p90_deg"] <= 2.50
    ):

        return (
            "PURE_ROTATION_SUFFICIENT"
        )

    if essential is None:

        return (
            "ESSENTIAL_MODEL_FAILED"
        )

    #
    # Strong R+t evidence:
    # rotation-only is poor, but epipolar/
    # triangulation geometry explains the
    # same correspondences substantially better.
    #
    if (
        (
            pure["median_deg"] > 2.0
            or
            pure["p90_deg"] > 3.5
        )
        and
        essential[
            "essential_inlier_fraction"
        ] >= 0.70
        and
        essential[
            "sampson_median_deg"
        ] <= 0.50
        and
        essential[
            "sampson_p90_deg"
        ] <= 1.50
        and
        essential[
            "median_reprojection_deg"
        ] <= 1.00
    ):

        return (
            "R_PLUS_T_SUPPORTED"
        )

    return (
        "GEOMETRY_REVIEW"
    )


def analyse_pair(
    observations,
    seed,
):

    pure = fit_pure_rotation(
        observations,
        seed,
    )

    essential = fit_essential(
        observations
    )

    status = classify(
        pure,
        essential,
    )

    return {
        "count": int(
            len(observations)
        ),

        "pure_rotation": pure,

        "essential": essential,

        "status": status,
    }


def translation_axis_angle_deg(
    ta,
    tb,
):

    ta = np.asarray(
        ta,
        dtype=float,
    )

    tb = np.asarray(
        tb,
        dtype=float,
    )

    ta /= np.linalg.norm(
        ta
    )

    tb /= np.linalg.norm(
        tb
    )

    #
    # Essential translation sign can be
    # ambiguous near degenerate cases.
    # Compare axis rather than directed sign.
    #
    dot = abs(
        float(
            np.dot(
                ta,
                tb,
            )
        )
    )

    dot = np.clip(
        dot,
        -1.0,
        1.0,
    )

    return math.degrees(
        math.acos(
            dot
        )
    )


def json_safe_result(
    result,
):

    output = {
        "count":
            result[
                "count"
            ],

        "status":
            result[
                "status"
            ],

        "pure_rotation": {
            key: value
            for key, value
            in result[
                "pure_rotation"
            ].items()
            if key != "R"
        },
    }

    essential = (
        result[
            "essential"
        ]
    )

    if essential is None:

        output[
            "essential"
        ] = None

    else:

        output[
            "essential"
        ] = {
            key: (
                value.tolist()
                if isinstance(
                    value,
                    np.ndarray,
                )
                else value
            )
            for key, value
            in essential.items()
        }

    return output


def main():

    print("=" * 118)

    print(
        "SMART FIRE PARALLAX / R+t "
        "DIAGNOSTIC — FINAL A/B v1"
    )

    print("=" * 118)

    print(
        f"A : {A_ROOT}"
    )

    print(
        f"B : {B_ROOT}"
    )

    print(
        "OLD DATA : NOT USED"
    )

    print(
        f"Essential threshold "
        f"(normalized) : "
        f"{ESSENTIAL_THRESHOLD}"
    )

    print("=" * 118)


    for path in (
        A_MARKS,
        B_MARKS,
    ):

        if not path.exists():

            raise RuntimeError(
                f"Missing {path}"
            )


    K, D = (
        core.load_intrinsics()
    )


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


    sessions = {
        "A": A,
        "B": B,
    }


    results = {
        "A": {},
        "B": {},
    }


    for session_index, (
        session_name,
        dataset,
    ) in enumerate(
        sessions.items(),
        start=1,
    ):

        print()
        print("=" * 118)

        print(
            f"SESSION {session_name}"
        )

        print("=" * 118)


        for a, b in PAIR_LIST:

            key = f"{a}-{b}"

            result = analyse_pair(
                dataset[key],
                seed=(
                    50000
                    + session_index
                    * 1000
                    + a * 100
                    + b
                ),
            )

            results[
                session_name
            ][key] = result


            pure = (
                result[
                    "pure_rotation"
                ]
            )

            essential = (
                result[
                    "essential"
                ]
            )


            print()
            print(
                f"PAIR {key}"
                + (
                    "  <<< FOCUS"
                    if key
                    in FOCUS_PAIRS
                    else ""
                )
            )

            print(
                f"  MARKs               : "
                f"{result['count']}"
            )

            print(
                f"  Pure-R median       : "
                f"{pure['median_deg']:.3f}°"
            )

            print(
                f"  Pure-R P90          : "
                f"{pure['p90_deg']:.3f}°"
            )

            print(
                f"  Pure-R max          : "
                f"{pure['max_deg']:.3f}°"
            )


            if essential is None:

                print(
                    "  Essential           : "
                    "FAILED"
                )

            else:

                print(
                    f"  E inliers           : "
                    f"{essential['essential_inlier_fraction']*100:.1f}%"
                )

                print(
                    f"  E Sampson med       : "
                    f"{essential['sampson_median_deg']:.3f}°"
                )

                print(
                    f"  E Sampson P90       : "
                    f"{essential['sampson_p90_deg']:.3f}°"
                )

                print(
                    f"  R+t reproj median   : "
                    f"{essential['median_reprojection_deg']:.3f}°"
                )

                print(
                    f"  R+t reproj P90      : "
                    f"{essential['p90_reprojection_deg']:.3f}°"
                )

                print(
                    f"  Positive depth      : "
                    f"{essential['positive_depth_fraction']*100:.1f}%"
                )

                print(
                    "  t direction         : "
                    f"["
                    f"{essential['t'][0]:+.3f}, "
                    f"{essential['t'][1]:+.3f}, "
                    f"{essential['t'][2]:+.3f}"
                    f"]"
                )


            print(
                f"  RESULT              : "
                f"{result['status']}"
            )


    #
    # Cross-session translation-axis check.
    #
    consistency = {}


    print()
    print("=" * 118)

    print(
        "CROSS-SESSION TRANSLATION AXIS"
    )

    print("=" * 118)


    for a, b in PAIR_LIST:

        key = f"{a}-{b}"

        ea = (
            results[
                "A"
            ][key][
                "essential"
            ]
        )

        eb = (
            results[
                "B"
            ][key][
                "essential"
            ]
        )


        if (
            ea is None
            or
            eb is None
        ):

            consistency[
                key
            ] = None

            print(
                f"{key:>5} | unavailable"
            )

            continue


        angle = (
            translation_axis_angle_deg(
                ea["t"],
                eb["t"],
            )
        )


        if angle <= 15.0:
            state = "STRONG"

        elif angle <= 30.0:
            state = "MODERATE"

        else:
            state = "UNSTABLE"


        consistency[
            key
        ] = {
            "axis_difference_deg":
                float(angle),

            "state":
                state,
        }


        print(
            f"{key:>5} "
            f"| t-axis A/B Δ="
            f"{angle:7.3f}° "
            f"| {state}"
        )


    print()
    print("=" * 118)

    print(
        "FOCUS SUMMARY"
    )

    print("=" * 118)


    for key in [
        "6-7",
        "7-8",
        "8-9",
        "5-9",
    ]:

        ra = results[
            "A"
        ][key]

        rb = results[
            "B"
        ][key]

        c = consistency[
            key
        ]


        axis_text = (
            "N/A"
            if c is None
            else
            (
                f"{c['axis_difference_deg']:.2f}° "
                f"{c['state']}"
            )
        )


        print(
            f"{key:>5} "
            f"| A={ra['status']:<24} "
            f"| B={rb['status']:<24} "
            f"| t-axis={axis_text}"
        )


    #
    # Overall interpretation flag.
    #
    strong_pairs = []

    for key in [
        "6-7",
        "7-8",
        "8-9",
    ]:

        if (
            results[
                "A"
            ][key][
                "status"
            ]
            ==
            "R_PLUS_T_SUPPORTED"

            and

            results[
                "B"
            ][key][
                "status"
            ]
            ==
            "R_PLUS_T_SUPPORTED"

            and

            consistency[
                key
            ]
            is not None

            and

            consistency[
                key
            ][
                "axis_difference_deg"
            ]
            <= 30.0
        ):

            strong_pairs.append(
                key
            )


    print()
    print(
        "R_PLUS_T_REPEATABLE_PAIRS="
        + (
            ",".join(
                strong_pairs
            )
            if strong_pairs
            else "NONE"
        )
    )


    if "8-9" in strong_pairs:

        decision = (
            "PROCEED_TO_R_PLUS_T_MODEL"
        )

    elif strong_pairs:

        decision = (
            "R_PLUS_T_PARTIALLY_SUPPORTED"
        )

    else:

        decision = (
            "DO_NOT_ADD_TRANSLATION_YET"
        )


    print(
        f"DECISION={decision}"
    )


    payload = {
        "format":
            "smart-fire-parallax-diagnostic-AB-v1",

        "session_A":
            str(A_ROOT),

        "session_B":
            str(B_ROOT),

        "old_data_used":
            False,

        "essential_threshold_normalized":
            ESSENTIAL_THRESHOLD,

        "results": {
            session: {
                key:
                    json_safe_result(
                        value
                    )
                for key, value
                in pair_results.items()
            }
            for session, pair_results
            in results.items()
        },

        "translation_axis_consistency":
            consistency,

        "repeatable_R_plus_t_pairs":
            strong_pairs,

        "decision":
            decision,
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
        f"SAVED={OUTPUT}"
    )

    print("=" * 118)


if __name__ == "__main__":
    main()
