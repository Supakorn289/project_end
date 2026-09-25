#!/usr/bin/env python3

import json
import math
from pathlib import Path

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

HOLDOUT_RESULT = (
    B_ROOT
    / "final_AB_holdout_result_v1.json"
)

FINAL_RESULT = (
    Path("/opt/smart-fire-detection-v2")
    / "calibration"
    / "preset_rotation_candidate_AB_v1.json"
)


# ------------------------------------------------------------
# Production prototype gates
# ------------------------------------------------------------

GLOBAL_MEDIAN_LIMIT_DEG = 1.50
GLOBAL_P90_LIMIT_DEG = 2.50

PAIR_MEDIAN_LIMIT_DEG = 2.00
PAIR_P90_LIMIT_DEG = 3.50

GRAPH_RMSE_LIMIT_DEG = 1.50
GRAPH_MAX_LIMIT_DEG = 3.00


def require_inputs():

    if A_ROOT.resolve() == B_ROOT.resolve():
        raise RuntimeError(
            "Session A and B are the same directory"
        )

    for path in (
        A_MARKS,
        B_MARKS,
    ):

        if not path.exists():
            raise RuntimeError(
                f"Missing MARK file: {path}"
            )

    for label, root in (
        ("A", A_ROOT),
        ("B", B_ROOT),
    ):

        captures = list(
            (
                root
                / "captures"
            ).glob(
                "step_*.jpg"
            )
        )

        if len(captures) != 17:
            raise RuntimeError(
                f"Session {label}: "
                f"expected 17 captures, "
                f"found {len(captures)}"
            )


def print_pair_fit(
    title,
    edges,
    graph,
):

    print()
    print("=" * 112)
    print(title)
    print("=" * 112)

    for a, b in core.PAIR_LIST:

        key = f"{a}-{b}"

        edge = edges[key]

        print(
            f"{key:>5} "
            f"| inliers="
            f"{edge['inlier_count']:3d}/"
            f"{edge['total_count']:<3d} "
            f"| support="
            f"{edge['inlier_fraction']*100:5.1f}% "
            f"| med3D="
            f"{edge['median_error_deg']:6.3f}° "
            f"| p90="
            f"{edge['p90_error_deg']:6.3f}° "
            f"| graph residual="
            f"{graph['edge_residuals_deg'][key]:6.3f}°"
        )

    print()
    print(
        f"Graph RMSE : "
        f"{graph['graph_rmse_deg']:.4f}°"
    )

    print(
        f"Graph max  : "
        f"{graph['graph_max_residual_deg']:.4f}°"
    )

    print()
    print("RELATIVE OPTICAL AXES")

    for preset in range(1, 10):

        metrics = (
            core.optical_axis_metrics(
                graph[
                    "orientations"
                ][
                    preset
                ]
            )
        )

        print(
            f"P{preset} "
            f"| az="
            f"{metrics['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{metrics['elevation_deg']:+8.3f}°"
        )


def production_holdout_gate(
    evaluation,
):

    metrics = (
        evaluation[
            "global_metrics"
        ]
    )

    pair_checks = {}

    all_pairs_ok = True

    for a, b in core.PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            evaluation[
                "pairs"
            ][
                key
            ]
        )

        median_ok = (
            item[
                "median_abs_azimuth_error_deg"
            ]
            <= PAIR_MEDIAN_LIMIT_DEG
        )

        p90_ok = (
            item[
                "p90_abs_azimuth_error_deg"
            ]
            <= PAIR_P90_LIMIT_DEG
        )

        passed = (
            median_ok
            and p90_ok
        )

        pair_checks[key] = {
            "median_ok": bool(
                median_ok
            ),
            "p90_ok": bool(
                p90_ok
            ),
            "passed": bool(
                passed
            ),
        }

        all_pairs_ok &= passed

    global_median_ok = (
        metrics[
            "median_abs_azimuth_error_deg"
        ]
        <= GLOBAL_MEDIAN_LIMIT_DEG
    )

    global_p90_ok = (
        metrics[
            "p90_abs_azimuth_error_deg"
        ]
        <= GLOBAL_P90_LIMIT_DEG
    )

    passed = (
        all_pairs_ok
        and
        global_median_ok
        and
        global_p90_ok
    )

    return {
        "passed": bool(
            passed
        ),

        "all_pairs_ok": bool(
            all_pairs_ok
        ),

        "global_median_ok": bool(
            global_median_ok
        ),

        "global_p90_ok": bool(
            global_p90_ok
        ),

        "pair_checks": (
            pair_checks
        ),
    }


def print_holdout(
    evaluation,
    gate,
):

    print()
    print("=" * 112)
    print(
        "SESSION B — INDEPENDENT HOLDOUT"
    )
    print("=" * 112)

    for a, b in core.PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            evaluation[
                "pairs"
            ][
                key
            ]
        )

        gate_item = (
            gate[
                "pair_checks"
            ][
                key
            ]
        )

        status = (
            "PASS"
            if gate_item[
                "passed"
            ]
            else "FAIL"
        )

        print(
            f"{key:>5} "
            f"| n="
            f"{item['target_count']:3d} "
            f"| median az="
            f"{item['median_abs_azimuth_error_deg']:6.3f}° "
            f"| p90 az="
            f"{item['p90_abs_azimuth_error_deg']:6.3f}° "
            f"| max="
            f"{item['max_abs_azimuth_error_deg']:6.3f}° "
            f"| <=2°="
            f"{item['fraction_le_2deg']*100:5.1f}% "
            f"| median3D="
            f"{item['median_3d_error_deg']:6.3f}° "
            f"| {status}"
        )

    m = (
        evaluation[
            "global_metrics"
        ]
    )

    print()
    print("GLOBAL HOLDOUT")
    print(
        f"Targets       : "
        f"{m['target_count']}"
    )

    print(
        f"Median abs az : "
        f"{m['median_abs_azimuth_error_deg']:.4f}° "
        f"(limit {GLOBAL_MEDIAN_LIMIT_DEG:.2f}°)"
    )

    print(
        f"Mean abs az   : "
        f"{m['mean_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"P90 abs az    : "
        f"{m['p90_abs_azimuth_error_deg']:.4f}° "
        f"(limit {GLOBAL_P90_LIMIT_DEG:.2f}°)"
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

    print()
    print(
        "PRODUCTION_GEOMETRY_HOLDOUT="
        + (
            "PASS"
            if gate[
                "passed"
            ]
            else "FAIL"
        )
    )


def evaluate_combined_sessions(
    observations_a,
    observations_b,
    Q,
):

    eval_a = (
        core.evaluate_dataset(
            observations_a,
            Q,
        )
    )

    eval_b = (
        core.evaluate_dataset(
            observations_b,
            Q,
        )
    )

    return (
        eval_a,
        eval_b,
    )


def compact_eval(
    evaluation,
):

    m = (
        evaluation[
            "global_metrics"
        ]
    )

    return {
        "target_count": int(
            m[
                "target_count"
            ]
        ),

        "median_abs_azimuth_error_deg":
            float(
                m[
                    "median_abs_azimuth_error_deg"
                ]
            ),

        "mean_abs_azimuth_error_deg":
            float(
                m[
                    "mean_abs_azimuth_error_deg"
                ]
            ),

        "p90_abs_azimuth_error_deg":
            float(
                m[
                    "p90_abs_azimuth_error_deg"
                ]
            ),

        "max_abs_azimuth_error_deg":
            float(
                m[
                    "max_abs_azimuth_error_deg"
                ]
            ),

        "median_3d_error_deg":
            float(
                m[
                    "median_3d_error_deg"
                ]
            ),

        "p90_3d_error_deg":
            float(
                m[
                    "p90_3d_error_deg"
                ]
            ),
    }


def main():

    require_inputs()

    print("=" * 112)
    print(
        "SMART FIRE FINAL A/B "
        "3-D ROTATION SOLVER v1"
    )
    print("=" * 112)

    print(
        f"TRAIN A : {A_ROOT}"
    )

    print(
        f"HOLDOUT B: {B_ROOT}"
    )

    print(
        "OLD DATA : IGNORED COMPLETELY"
    )

    print(
        "MODEL    : calibrated "
        "central-camera 3-D rotation"
    )

    print("=" * 112)


    K, D = (
        core.load_intrinsics()
    )


    #
    # Load only FINAL A / FINAL B
    #
    dataset_a = (
        core.load_mark_file(
            A_MARKS,
            "FINAL_A",
            K,
            D,
        )
    )

    dataset_b = (
        core.load_mark_file(
            B_MARKS,
            "FINAL_B",
            K,
            D,
        )
    )


    #
    # PHASE 1
    # Fit A only.
    #
    edges_a, graph_a = (
        core.fit_model(
            dataset_a
        )
    )


    print_pair_fit(
        "PHASE 1 — TRAIN ON FINAL-A ONLY",
        edges_a,
        graph_a,
    )


    #
    # PHASE 2
    # Independent B holdout.
    #
    holdout = (
        core.evaluate_dataset(
            dataset_b,
            graph_a[
                "orientations"
            ],
        )
    )


    gate = (
        production_holdout_gate(
            holdout
        )
    )


    print_holdout(
        holdout,
        gate,
    )


    holdout_payload = {
        "format":
            "smart-fire-final-AB-holdout-v1",

        "session_A": str(
            A_ROOT
        ),

        "session_B": str(
            B_ROOT
        ),

        "old_data_used": False,

        "model":
            "central-camera-pure-3d-rotation",

        "training_graph": {
            "graph_rmse_deg":
                float(
                    graph_a[
                        "graph_rmse_deg"
                    ]
                ),

            "graph_max_residual_deg":
                float(
                    graph_a[
                        "graph_max_residual_deg"
                    ]
                ),

            "edge_residuals_deg":
                graph_a[
                    "edge_residuals_deg"
                ],
        },

        "holdout": holdout,

        "production_gate": gate,
    }


    HOLDOUT_RESULT.write_text(
        json.dumps(
            holdout_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print(
        f"HOLDOUT SAVED : "
        f"{HOLDOUT_RESULT}"
    )


    #
    # Stop here if independent B fails.
    #
    if not gate[
        "passed"
    ]:

        print()
        print("=" * 112)

        print(
            "FINAL_AB_RESULT="
            "HOLDOUT_FAILED"
        )

        print(
            "No production candidate "
            "was created."
        )

        print(
            "Do NOT change runtime geometry yet."
        )

        print("=" * 112)

        return


    #
    # PHASE 3
    # Refit on A+B only after independent holdout passes.
    #
    combined = (
        core.merge_observations(
            [
                dataset_a,
                dataset_b,
            ]
        )
    )


    final_edges, final_graph = (
        core.fit_model(
            combined
        )
    )


    print_pair_fit(
        "PHASE 3 — FINAL REFIT WITH A + B",
        final_edges,
        final_graph,
    )


    final_eval_a, final_eval_b = (
        evaluate_combined_sessions(
            dataset_a,
            dataset_b,
            final_graph[
                "orientations"
            ],
        )
    )


    graph_gate = (
        final_graph[
            "graph_rmse_deg"
        ]
        <= GRAPH_RMSE_LIMIT_DEG
        and
        final_graph[
            "graph_max_residual_deg"
        ]
        <= GRAPH_MAX_LIMIT_DEG
    )


    final_payload = {
        "format":
            "smart-fire-preset-rotation-AB-v1",

        "status":
            (
                "PASS_CANDIDATE_NOT_INSTALLED"
                if graph_gate
                else
                "FINAL_GRAPH_REVIEW_REQUIRED"
            ),

        "runtime_image_matching": False,

        "old_data_used": False,

        "model":
            "central-camera-pure-3d-rotation",

        "reference_preset": 1,

        "intrinsics_file": str(
            core.INTRINSICS_FILE
        ),

        "session_A": str(
            A_ROOT
        ),

        "session_B": str(
            B_ROOT
        ),

        "independent_holdout_gate":
            gate,

        "final_pair_rotations":
            core.serialize_edges(
                final_edges
            ),

        "presets":
            core.serialize_orientations(
                final_graph[
                    "orientations"
                ]
            ),

        "graph": {
            "optimizer_success":
                bool(
                    final_graph[
                        "optimizer_success"
                    ]
                ),

            "optimizer_message":
                str(
                    final_graph[
                        "optimizer_message"
                    ]
                ),

            "graph_rmse_deg":
                float(
                    final_graph[
                        "graph_rmse_deg"
                    ]
                ),

            "graph_max_residual_deg":
                float(
                    final_graph[
                        "graph_max_residual_deg"
                    ]
                ),

            "edge_residuals_deg":
                final_graph[
                    "edge_residuals_deg"
                ],

            "production_graph_gate":
                bool(
                    graph_gate
                ),
        },

        "post_refit_session_A":
            compact_eval(
                final_eval_a
            ),

        "post_refit_session_B":
            compact_eval(
                final_eval_b
            ),

        "note":
            (
                "Candidate generated only "
                "from FINAL-A and FINAL-B. "
                "Not installed into runtime. "
                "True North is not included."
            ),
    }


    FINAL_RESULT.write_text(
        json.dumps(
            final_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print("=" * 112)

    print("FINAL REFIT SUMMARY")

    print("=" * 112)

    print(
        f"Graph RMSE : "
        f"{final_graph['graph_rmse_deg']:.4f}° "
        f"(limit {GRAPH_RMSE_LIMIT_DEG:.2f}°)"
    )

    print(
        f"Graph max  : "
        f"{final_graph['graph_max_residual_deg']:.4f}° "
        f"(limit {GRAPH_MAX_LIMIT_DEG:.2f}°)"
    )


    A = compact_eval(
        final_eval_a
    )

    B = compact_eval(
        final_eval_b
    )


    print(
        f"A median/P90 : "
        f"{A['median_abs_azimuth_error_deg']:.4f}° / "
        f"{A['p90_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"B median/P90 : "
        f"{B['median_abs_azimuth_error_deg']:.4f}° / "
        f"{B['p90_abs_azimuth_error_deg']:.4f}°"
    )


    if graph_gate:

        print(
            "FINAL_AB_RESULT="
            "PASS_CANDIDATE_NOT_INSTALLED"
        )

        print(
            f"CANDIDATE : "
            f"{FINAL_RESULT}"
        )

    else:

        print(
            "FINAL_AB_RESULT="
            "FINAL_GRAPH_REVIEW_REQUIRED"
        )

        print(
            "Candidate file contains "
            "diagnostic data only."
        )


    print("=" * 112)


if __name__ == "__main__":
    main()
