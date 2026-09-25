#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

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

HOLDOUT_OUTPUT = (
    B_ROOT
    / "final_bearing_bundle_AB_v3_holdout.json"
)

FINAL_OUTPUT = (
    Path("/opt/smart-fire-detection-v2")
    / "calibration"
    / "preset_bearing_candidate_AB_v3.json"
)


PAIR_LIST = list(
    core.PAIR_LIST
)


#
# Physical preset bearings are INITIALIZATION ONLY.
# They are NOT overwritten.
#
PHYSICAL = {
    1: 0.0,
    2: 45.0,
    3: 90.0,
    4: 135.0,
    5: 177.5,
    6: -45.0,
    7: -90.0,
    8: -135.0,
    9: -177.5,
}


VARIABLE_PRESETS = [
    2,3,4,5,6,7,8,9
]


def signed_deg(value):

    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


def ray_azimuth_deg(ray):

    ray = np.asarray(
        ray,
        dtype=float,
    )

    return math.degrees(
        math.atan2(
            float(ray[0]),
            float(ray[2]),
        )
    )


def centers_from_x(x):

    centers = {
        1: 0.0
    }

    for index, preset in enumerate(
        VARIABLE_PRESETS
    ):

        centers[preset] = (
            PHYSICAL[preset]
            + float(
                x[index]
            )
        )

    return centers


def make_residual(
    dataset,
):

    pair_scales = {}

    for a,b in PAIR_LIST:

        key = f"{a}-{b}"

        n = len(
            dataset[key]
        )

        if n < 3:
            raise RuntimeError(
                f"{key}: only {n} marks"
            )

        #
        # Equalize pair influence.
        # A pair with 70 marks must not dominate
        # a pair with 18 marks solely by count.
        #
        pair_scales[key] = math.sqrt(
            20.0
            / float(n)
        )


    def residual(x):

        centers = centers_from_x(
            x
        )

        values = []


        for a,b in PAIR_LIST:

            key = f"{a}-{b}"

            scale = (
                pair_scales[key]
            )


            for obs in dataset[key]:

                az_a = (
                    ray_azimuth_deg(
                        obs["ray_a"]
                    )
                )

                az_b = (
                    ray_azimuth_deg(
                        obs["ray_b"]
                    )
                )


                bearing_a = (
                    centers[a]
                    + az_a
                )

                bearing_b = (
                    centers[b]
                    + az_b
                )


                error = signed_deg(
                    bearing_a
                    - bearing_b
                )


                values.append(
                    scale
                    * error
                )


        return np.asarray(
            values,
            dtype=float,
        )


    return residual


def solve(
    dataset,
    initial_x=None,
):

    if initial_x is None:

        initial_x = np.zeros(
            len(
                VARIABLE_PRESETS
            ),
            dtype=float,
        )


    result = least_squares(
        make_residual(
            dataset
        ),

        initial_x,

        method="trf",

        #
        # Robust against occasional mis-click /
        # difficult target.
        #
        loss="soft_l1",

        f_scale=1.0,

        max_nfev=5000,

        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
    )


    return {
        "x": result.x,

        "centers":
            centers_from_x(
                result.x
            ),

        "success":
            bool(
                result.success
            ),

        "message":
            str(
                result.message
            ),

        "cost":
            float(
                result.cost
            ),

        "optimality":
            float(
                result.optimality
            ),

        "nfev":
            int(
                result.nfev
            ),
    }


def evaluate(
    dataset,
    centers,
):

    pair_results = {}

    all_abs = []


    for a,b in PAIR_LIST:

        key = f"{a}-{b}"

        signed_errors = []


        for obs in dataset[key]:

            az_a = (
                ray_azimuth_deg(
                    obs["ray_a"]
                )
            )

            az_b = (
                ray_azimuth_deg(
                    obs["ray_b"]
                )
            )


            error = signed_deg(
                (
                    centers[a]
                    + az_a
                )
                -
                (
                    centers[b]
                    + az_b
                )
            )


            signed_errors.append(
                error
            )


        signed_errors = np.asarray(
            signed_errors,
            dtype=float,
        )

        absolute = np.abs(
            signed_errors
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

        p90_abs = float(
            np.percentile(
                absolute,
                90,
            )
        )

        max_abs = float(
            np.max(
                absolute
            )
        )

        bias = float(
            np.median(
                signed_errors
            )
        )

        fraction_1 = float(
            np.mean(
                absolute <= 1.0
            )
        )

        fraction_2 = float(
            np.mean(
                absolute <= 2.0
            )
        )


        all_abs.extend(
            absolute.tolist()
        )


        if (
            median_abs <= 1.50
            and
            p90_abs <= 2.50
        ):

            status = "PASS"

        elif (
            median_abs <= 2.00
            and
            p90_abs <= 3.50
        ):

            status = "REVIEW"

        else:

            status = "FAIL"


        pair_results[key] = {
            "count":
                int(
                    len(
                        absolute
                    )
                ),

            "signed_bias_deg":
                bias,

            "median_abs_error_deg":
                median_abs,

            "mean_abs_error_deg":
                mean_abs,

            "p90_abs_error_deg":
                p90_abs,

            "max_abs_error_deg":
                max_abs,

            "fraction_le_1deg":
                fraction_1,

            "fraction_le_2deg":
                fraction_2,

            "status":
                status,
        }


    all_abs = np.asarray(
        all_abs,
        dtype=float,
    )


    global_result = {
        "count":
            int(
                len(
                    all_abs
                )
            ),

        "median_abs_error_deg":
            float(
                np.median(
                    all_abs
                )
            ),

        "mean_abs_error_deg":
            float(
                np.mean(
                    all_abs
                )
            ),

        "p90_abs_error_deg":
            float(
                np.percentile(
                    all_abs,
                    90,
                )
            ),

        "max_abs_error_deg":
            float(
                np.max(
                    all_abs
                )
            ),
    }


    return {
        "pairs":
            pair_results,

        "global":
            global_result,
    }


def production_gate(
    evaluation,
):

    g = evaluation[
        "global"
    ]


    pair_gate = {}


    for a,b in PAIR_LIST:

        key = f"{a}-{b}"

        p = evaluation[
            "pairs"
        ][key]


        ok = (
            p[
                "median_abs_error_deg"
            ]
            <= 2.00

            and

            p[
                "p90_abs_error_deg"
            ]
            <= 3.50
        )


        pair_gate[key] = bool(
            ok
        )


    passed = (
        g[
            "median_abs_error_deg"
        ]
        <= 1.50

        and

        g[
            "p90_abs_error_deg"
        ]
        <= 2.50

        and

        all(
            pair_gate.values()
        )
    )


    return {
        "passed":
            bool(
                passed
            ),

        "pairs":
            pair_gate,
    }


def print_centers(
    title,
    centers,
):

    print()
    print(title)

    for preset in range(
        1,
        10,
    ):

        center = (
            centers[preset]
        )

        physical = (
            PHYSICAL[preset]
        )

        correction = signed_deg(
            center
            - physical
        )

        print(
            f"P{preset} "
            f"| center="
            f"{signed_deg(center):+9.4f}° "
            f"| physical="
            f"{physical:+8.3f}° "
            f"| correction="
            f"{correction:+8.4f}°"
        )


def print_evaluation(
    title,
    evaluation,
):

    print()
    print("=" * 112)
    print(title)
    print("=" * 112)


    for a,b in PAIR_LIST:

        key = f"{a}-{b}"

        p = evaluation[
            "pairs"
        ][key]


        print(
            f"{key:>5} "
            f"| n="
            f"{p['count']:3d} "
            f"| bias="
            f"{p['signed_bias_deg']:+7.3f}° "
            f"| median="
            f"{p['median_abs_error_deg']:6.3f}° "
            f"| p90="
            f"{p['p90_abs_error_deg']:6.3f}° "
            f"| max="
            f"{p['max_abs_error_deg']:7.3f}° "
            f"| <=1°="
            f"{p['fraction_le_1deg']*100:5.1f}% "
            f"| <=2°="
            f"{p['fraction_le_2deg']*100:5.1f}% "
            f"| {p['status']}"
        )


    g = evaluation[
        "global"
    ]


    print()
    print("GLOBAL")

    print(
        f"Targets : {g['count']}"
    )

    print(
        f"Median  : "
        f"{g['median_abs_error_deg']:.4f}°"
    )

    print(
        f"Mean    : "
        f"{g['mean_abs_error_deg']:.4f}°"
    )

    print(
        f"P90     : "
        f"{g['p90_abs_error_deg']:.4f}°"
    )

    print(
        f"Max     : "
        f"{g['max_abs_error_deg']:.4f}°"
    )


def main():

    print("=" * 112)

    print(
        "SMART FIRE FINAL A/B "
        "DIRECT BEARING BUNDLE v3"
    )

    print("=" * 112)

    print(
        f"TRAIN A   : {A_ROOT}"
    )

    print(
        f"HOLDOUT B : {B_ROOT}"
    )

    print(
        "OLD DATA  : IGNORED"
    )

    print(
        "OUTPUT     : azimuth/bearing only"
    )

    print(
        "R+t        : NOT USED"
    )

    print("=" * 112)


    K,D = (
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


    #
    # Fit FINAL-A only.
    #
    fit_A = solve(
        A
    )


    print()
    print(
        "TRAIN OPTIMIZER"
    )

    print(
        f"success    : "
        f"{fit_A['success']}"
    )

    print(
        f"message    : "
        f"{fit_A['message']}"
    )

    print(
        f"nfev       : "
        f"{fit_A['nfev']}"
    )

    print(
        f"cost       : "
        f"{fit_A['cost']:.8f}"
    )

    print(
        f"optimality : "
        f"{fit_A['optimality']:.8e}"
    )


    print_centers(
        "TRAINED BEARING CENTERS",
        fit_A[
            "centers"
        ],
    )


    eval_A = evaluate(
        A,
        fit_A[
            "centers"
        ],
    )


    eval_B = evaluate(
        B,
        fit_A[
            "centers"
        ],
    )


    print_evaluation(
        "FINAL-A — TRAIN RESIDUAL",
        eval_A,
    )


    print_evaluation(
        "FINAL-B — INDEPENDENT HOLDOUT",
        eval_B,
    )


    gate = production_gate(
        eval_B
    )


    print()
    print("=" * 112)

    print(
        "PRODUCTION BEARING GATE"
    )

    print("=" * 112)


    for a,b in PAIR_LIST:

        key = f"{a}-{b}"

        print(
            f"{key:>5}: "
            f"{'PASS' if gate['pairs'][key] else 'FAIL'}"
        )


    print()

    print(
        "GLOBAL MEDIAN <= 1.50°"
    )

    print(
        "GLOBAL P90    <= 2.50°"
    )

    print(
        "PAIR MEDIAN   <= 2.00°"
    )

    print(
        "PAIR P90      <= 3.50°"
    )

    print()

    print(
        "BEARING_HOLDOUT="
        + (
            "PASS"
            if gate[
                "passed"
            ]
            else "FAIL"
        )
    )


    holdout_payload = {
        "format":
            "smart-fire-direct-bearing-AB-v3-holdout",

        "train_A":
            str(A_ROOT),

        "holdout_B":
            str(B_ROOT),

        "old_data_used":
            False,

        "centers":
            {
                str(k):
                    float(v)
                for k,v
                in fit_A[
                    "centers"
                ].items()
            },

        "train_evaluation":
            eval_A,

        "holdout_evaluation":
            eval_B,

        "production_gate":
            gate,
    }


    HOLDOUT_OUTPUT.write_text(
        json.dumps(
            holdout_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    if not gate[
        "passed"
    ]:

        print()
        print(
            "FINAL_BEARING_RESULT="
            "HOLDOUT_FAILED"
        )

        print(
            "No runtime candidate created."
        )

        print(
            f"SAVED={HOLDOUT_OUTPUT}"
        )

        return


    #
    # Independent holdout passed.
    # Refit A+B.
    #
    combined = (
        core.merge_observations(
            [
                A,
                B,
            ]
        )
    )


    fit_final = solve(
        combined,
        initial_x=fit_A[
            "x"
        ],
    )


    final_A = evaluate(
        A,
        fit_final[
            "centers"
        ],
    )

    final_B = evaluate(
        B,
        fit_final[
            "centers"
        ],
    )


    print_centers(
        "FINAL A+B BEARING CENTERS",
        fit_final[
            "centers"
        ],
    )


    print_evaluation(
        "POST-REFIT FINAL-A",
        final_A,
    )

    print_evaluation(
        "POST-REFIT FINAL-B",
        final_B,
    )


    final_payload = {
        "format":
            "smart-fire-preset-bearing-AB-v3",

        "status":
            "PASS_CANDIDATE_NOT_INSTALLED",

        "model":
            "direct-undistorted-ray-azimuth-plus-preset-center",

        "runtime_image_matching":
            False,

        "old_data_used":
            False,

        "reference_preset":
            1,

        "intrinsics_file":
            str(
                core.INTRINSICS_FILE
            ),

        "session_A":
            str(A_ROOT),

        "session_B":
            str(B_ROOT),

        "preset_centers_deg":
            {
                str(p):
                    float(
                        fit_final[
                            "centers"
                        ][p]
                    )
                for p in range(
                    1,
                    10,
                )
            },

        "preset_centers_signed_deg":
            {
                str(p):
                    float(
                        signed_deg(
                            fit_final[
                                "centers"
                            ][p]
                        )
                    )
                for p in range(
                    1,
                    10,
                )
            },

        "holdout_gate":
            gate,

        "post_refit_A":
            final_A,

        "post_refit_B":
            final_B,

        "note":
            (
                "Relative bearing calibration only. "
                "True North offset is intentionally "
                "not included yet."
            ),
    }


    FINAL_OUTPUT.write_text(
        json.dumps(
            final_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print("=" * 112)

    print(
        "FINAL_BEARING_RESULT="
        "PASS_CANDIDATE_NOT_INSTALLED"
    )

    print(
        f"CANDIDATE={FINAL_OUTPUT}"
    )

    print("=" * 112)


if __name__ == "__main__":
    main()
