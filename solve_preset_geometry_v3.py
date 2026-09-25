#!/usr/bin/env python3

import heapq
import itertools
import json
import math
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

    (5, 9),
]

POSITIVE_BRANCH = [
    "1-2",
    "2-3",
    "3-4",
    "4-5",
    "5-9",
]

NEGATIVE_BRANCH = [
    "1-6",
    "6-7",
    "7-8",
    "8-9",
]


# ============================================================
# Solver tuning
# ============================================================

CLUSTER_RADIUS_DEG = 1.50

MAX_CANDIDATES_PER_PAIR = 5

# Physical preset spacing is a SOFT prior only.
# 6 deg means deviations of several degrees are allowed.
NOMINAL_PRIOR_SIGMA_DEG = 6.0

# Full-loop agreement is intentionally strong.
CLOSURE_SIGMA_DEG = 1.25
CLOSURE_WEIGHT = 5.0

# Candidate quality terms.
SUPPORT_WEIGHT = 2.0
STD_SIGMA_DEG = 1.25
NOMINAL_WEIGHT = 0.55

TOP_GLOBAL_SOLUTIONS = 10


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
# Candidate cluster generation
# ============================================================

def candidate_local_cost(
    center,
    std,
    support,
    nominal,
    count,
):
    support_penalty = (
        SUPPORT_WEIGHT
        * (
            1.0
            - float(support)
        ) ** 2
    )

    std_penalty = (
        float(std)
        / STD_SIGMA_DEG
    ) ** 2

    nominal_penalty = (
        NOMINAL_WEIGHT
        * (
            (
                float(center)
                - float(nominal)
            )
            / NOMINAL_PRIOR_SIGMA_DEG
        ) ** 2
    )

    # Two-point clusters can still be considered,
    # but receive a significant penalty.
    small_cluster_penalty = (
        2.0
        if int(count) < 3
        else 0.0
    )

    return float(
        support_penalty
        + std_penalty
        + nominal_penalty
        + small_cluster_penalty
    )


def make_candidate(
    values,
    mask,
    nominal,
):
    values = np.asarray(
        values,
        dtype=float,
    )

    mask = np.asarray(
        mask,
        dtype=bool,
    )

    selected = values[
        mask
    ]

    if len(selected) < 2:
        return None

    center = float(
        np.median(
            selected
        )
    )

    residuals = (
        selected
        - center
    )

    std = float(
        np.std(
            residuals
        )
    )

    maxdev = float(
        np.max(
            np.abs(
                residuals
            )
        )
    )

    support = float(
        len(selected)
        / len(values)
    )

    cost = candidate_local_cost(
        center=center,
        std=std,
        support=support,
        nominal=nominal,
        count=len(selected),
    )

    return {
        "center_deg": center,

        "count": int(
            len(selected)
        ),

        "total": int(
            len(values)
        ),

        "support": support,

        "std_deg": std,

        "max_deviation_deg": (
            maxdev
        ),

        "difference_from_nominal_deg": (
            float(
                center
                - nominal
            )
        ),

        "local_cost": cost,

        "indices": [
            int(index + 1)
            for index, keep
            in enumerate(mask)
            if keep
        ],

        "_mask": mask,
    }


def build_candidates(
    values,
    nominal,
):
    values = np.asarray(
        values,
        dtype=float,
    )

    if len(values) < 2:
        raise RuntimeError(
            "Need at least 2 marks"
        )

    raw_candidates = []

    # Every observed value can seed a local mode.
    for seed in values:

        center = float(seed)

        mask = None

        for _ in range(6):

            new_mask = (
                np.abs(
                    values
                    - center
                )
                <= CLUSTER_RADIUS_DEG
            )

            if (
                np.count_nonzero(
                    new_mask
                )
                < 2
            ):
                break

            new_center = float(
                np.median(
                    values[
                        new_mask
                    ]
                )
            )

            if (
                mask is not None
                and
                np.array_equal(
                    new_mask,
                    mask,
                )
                and
                abs(
                    new_center
                    - center
                )
                < 1e-9
            ):
                mask = new_mask
                center = new_center
                break

            mask = new_mask
            center = new_center

        if (
            mask is None
            or
            np.count_nonzero(
                mask
            )
            < 2
        ):
            continue

        candidate = make_candidate(
            values,
            mask,
            nominal,
        )

        if candidate is not None:
            raw_candidates.append(
                candidate
            )


    # Also explicitly seed at nominal.
    nominal_mask = (
        np.abs(
            values
            - nominal
        )
        <= CLUSTER_RADIUS_DEG
    )

    candidate = make_candidate(
        values,
        nominal_mask,
        nominal,
    )

    if candidate is not None:
        raw_candidates.append(
            candidate
        )


    # Deduplicate identical or nearly identical clusters.
    unique = []

    for candidate in sorted(
        raw_candidates,
        key=lambda item: (
            item[
                "local_cost"
            ],
            -item[
                "count"
            ],
        ),
    ):

        duplicate = False

        candidate_indices = set(
            candidate[
                "indices"
            ]
        )

        for existing in unique:

            existing_indices = set(
                existing[
                    "indices"
                ]
            )

            union = (
                candidate_indices
                | existing_indices
            )

            intersection = (
                candidate_indices
                & existing_indices
            )

            jaccard = (
                len(intersection)
                / len(union)
                if union
                else 0.0
            )

            if (
                abs(
                    candidate[
                        "center_deg"
                    ]
                    - existing[
                        "center_deg"
                    ]
                )
                <= 0.30
                and
                jaccard >= 0.60
            ):
                duplicate = True
                break

        if not duplicate:
            unique.append(
                candidate
            )


    if not unique:
        raise RuntimeError(
            "No candidate clusters found"
        )


    # Keep the strongest candidates.
    selected = unique[
        :MAX_CANDIDATES_PER_PAIR
    ]


    # Ensure nearest-to-nominal candidate remains available.
    nominal_nearest = min(
        unique,
        key=lambda item: abs(
            item[
                "center_deg"
            ]
            - nominal
        ),
    )

    if (
        nominal_nearest
        not in selected
    ):
        if (
            len(selected)
            >= MAX_CANDIDATES_PER_PAIR
        ):
            selected[
                -1
            ] = nominal_nearest
        else:
            selected.append(
                nominal_nearest
            )


    selected.sort(
        key=lambda item: (
            item[
                "local_cost"
            ],
            -item[
                "count"
            ],
        )
    )

    # Remove private numpy data.
    clean = []

    for candidate in selected:

        item = {
            key: value
            for key, value
            in candidate.items()
            if not key.startswith(
                "_"
            )
        }

        clean.append(
            item
        )

    return clean


# ============================================================
# Global combination search
# ============================================================

def branch_combinations(
    keys,
    candidate_map,
):
    lists = [
        candidate_map[
            key
        ]
        for key in keys
    ]

    output = []

    for choices in itertools.product(
        *lists
    ):

        total_delta = float(
            sum(
                item[
                    "center_deg"
                ]
                for item in choices
            )
        )

        local_cost = float(
            sum(
                item[
                    "local_cost"
                ]
                for item in choices
            )
        )

        selection = {
            key: choice
            for key, choice
            in zip(
                keys,
                choices,
            )
        }

        output.append(
            {
                "sum_deg": total_delta,
                "local_cost": local_cost,
                "selection": selection,
            }
        )

    return output


def find_global_solutions(
    candidate_map,
):
    positive = branch_combinations(
        POSITIVE_BRANCH,
        candidate_map,
    )

    negative = branch_combinations(
        NEGATIVE_BRANCH,
        candidate_map,
    )

    best_heap = []

    serial = 0

    for pos in positive:

        for neg in negative:

            closure = float(
                pos[
                    "sum_deg"
                ]
                - neg[
                    "sum_deg"
                ]
            )

            closure_cost = (
                CLOSURE_WEIGHT
                * (
                    closure
                    / CLOSURE_SIGMA_DEG
                ) ** 2
            )

            total_cost = float(
                pos[
                    "local_cost"
                ]
                + neg[
                    "local_cost"
                ]
                + closure_cost
            )

            selection = {}

            selection.update(
                pos[
                    "selection"
                ]
            )

            selection.update(
                neg[
                    "selection"
                ]
            )

            item = {
                "score": total_cost,

                "closure_deg": closure,

                "positive_c9_deg": float(
                    pos[
                        "sum_deg"
                    ]
                ),

                "negative_c9_deg": float(
                    neg[
                        "sum_deg"
                    ]
                ),

                "selection": selection,
            }

            serial += 1

            heap_entry = (
                -total_cost,
                serial,
                item,
            )

            if (
                len(best_heap)
                < TOP_GLOBAL_SOLUTIONS
            ):
                heapq.heappush(
                    best_heap,
                    heap_entry,
                )

            else:
                worst_score = (
                    -best_heap[
                        0
                    ][
                        0
                    ]
                )

                if (
                    total_cost
                    < worst_score
                ):
                    heapq.heapreplace(
                        best_heap,
                        heap_entry,
                    )


    solutions = [
        item
        for (
            _negative_score,
            _serial,
            item,
        ) in best_heap
    ]

    solutions.sort(
        key=lambda item: item[
            "score"
        ]
    )

    return solutions


# ============================================================
# Weighted graph solve
# ============================================================

def solve_graph(
    selected,
):
    variable_presets = list(
        range(
            2,
            10,
        )
    )

    variable_index = {
        preset: index
        for index, preset
        in enumerate(
            variable_presets
        )
    }

    rows = []
    targets = []
    weights = []


    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )

        candidate = selected[
            key
        ]

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


        target = float(
            candidate[
                "center_deg"
            ]
        )


        # Confidence based on actual MARK support.
        #
        # Floor std at 0.50 deg so tiny clusters do not
        # receive unrealistically huge weight.
        sigma = max(
            0.50,
            float(
                candidate[
                    "std_deg"
                ]
            ),
        )

        weight = (
            math.sqrt(
                candidate[
                    "count"
                ]
            )
            * candidate[
                "support"
            ]
            / sigma
        )

        # Prevent any edge from fully dominating the graph.
        weight = float(
            np.clip(
                weight,
                0.75,
                6.0,
            )
        )

        rows.append(
            row
        )

        targets.append(
            target
        )

        weights.append(
            weight
        )


    A = np.asarray(
        rows,
        dtype=float,
    )

    b = np.asarray(
        targets,
        dtype=float,
    )

    w = np.asarray(
        weights,
        dtype=float,
    )


    Aw = (
        A
        * w[:, None]
    )

    bw = (
        b
        * w
    )


    solution, _, rank, _ = (
        np.linalg.lstsq(
            Aw,
            bw,
            rcond=None,
        )
    )

    if int(rank) != 8:

        raise RuntimeError(
            f"Graph rank={rank}, "
            "expected 8"
        )


    centers = {
        1: 0.0
    }

    for preset in variable_presets:

        centers[
            preset
        ] = float(
            solution[
                variable_index[
                    preset
                ]
            ]
        )


    residuals = {}

    residual_values = []


    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )

        measured = float(
            selected[
                key
            ][
                "center_deg"
            ]
        )

        predicted = float(
            centers[
                preset_b
            ]
            - centers[
                preset_a
            ]
        )

        residual = float(
            predicted
            - measured
        )

        residuals[
            key
        ] = {
            "measured_delta_deg": (
                measured
            ),

            "predicted_delta_deg": (
                predicted
            ),

            "residual_deg": (
                residual
            ),
        }

        residual_values.append(
            residual
        )


    residual_values = np.asarray(
        residual_values,
        dtype=float,
    )


    rmse = float(
        np.sqrt(
            np.mean(
                residual_values ** 2
            )
        )
    )

    max_residual = float(
        np.max(
            np.abs(
                residual_values
            )
        )
    )


    return {
        "rank": int(
            rank
        ),

        "centers": centers,

        "residuals": residuals,

        "rmse_deg": rmse,

        "max_residual_deg": (
            max_residual
        ),

        "weights": {
            key: float(weight)
            for key, weight
            in zip(
                [
                    f"{a}-{b}"
                    for a, b
                    in PAIRS
                ],
                weights,
            )
        },
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
    # Validate image size
    # ========================================================

    shapes = {}


    for preset in range(
        1,
        10,
    ):

        path = (
            capture_dir
            / f"preset_{preset}.jpg"
        )

        image = cv2.imread(
            str(path)
        )

        if image is None:

            raise RuntimeError(
                f"Cannot read {path}"
            )

        height, width = (
            image.shape[:2]
        )

        shapes[
            preset
        ] = (
            width,
            height,
        )


    unique_shapes = set(
        shapes.values()
    )


    if len(
        unique_shapes
    ) != 1:

        raise RuntimeError(
            "Capture resolutions differ: "
            f"{shapes}"
        )


    width, height = next(
        iter(
            unique_shapes
        )
    )


    # ========================================================
    # Nominal physical structure
    #
    # Used ONLY for circular unwrap + soft prior.
    # ========================================================

    p1_physical = float(
        PRESET_BEARING_DEG[
            1
        ]
    )


    expected = {}


    for preset in range(
        1,
        10,
    ):

        expected[
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
        "=" * 100
    )

    print(
        "MARK-BASED PRESET GEOMETRY "
        "GLOBAL CONSTRAINT SOLVER v3"
    )

    print(
        "=" * 100
    )

    print(
        f"Site       : {site_dir}"
    )

    print(
        f"Resolution : "
        f"{width}x{height}"
    )

    print(
        "MARK data                : PRIMARY"
    )

    print(
        "Mechanical preset spacing: SOFT PRIOR"
    )

    print(
        "360-degree loop closure  : GLOBAL CONSTRAINT"
    )

    print(
        "Runtime image matching   : DISABLED"
    )

    print()


    # ========================================================
    # Convert all marks into angular measurements
    # ========================================================

    raw_pairs = {}

    candidate_map = {}


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


        if len(marks) < 2:

            raise RuntimeError(
                f"{key}: need >=2 marks; "
                f"found {len(marks)}"
            )


        nominal_delta = float(
            expected[
                preset_b
            ]
            - expected[
                preset_a
            ]
        )


        values = []

        mark_records = []


        for index, mark in enumerate(
            marks,
            start=1,
        ):

            xa, ya = mark[
                "a"
            ]

            xb, yb = mark[
                "b"
            ]


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


            signed = (
                normalize_signed_deg(
                    ray_a
                    - ray_b
                )
            )


            delta = (
                unwrap_near(
                    signed,
                    nominal_delta,
                )
            )


            values.append(
                float(delta)
            )


            mark_records.append(
                {
                    "index": int(
                        index
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

                    "delta_unwrapped_deg": (
                        float(
                            delta
                        )
                    ),
                }
            )


        candidates = (
            build_candidates(
                values,
                nominal_delta,
            )
        )


        raw_pairs[
            key
        ] = {
            "nominal_delta_deg": (
                nominal_delta
            ),

            "values_deg": values,

            "marks": mark_records,
        }


        candidate_map[
            key
        ] = candidates


        print(
            f"PAIR {key} "
            f"| marks={len(values)} "
            f"| candidates="
            f"{len(candidates)}"
        )


        for rank, candidate in enumerate(
            candidates,
            start=1,
        ):

            print(
                f"   C{rank}: "
                f"{candidate['center_deg']:+9.3f}° "
                f"| n="
                f"{candidate['count']}/"
                f"{candidate['total']} "
                f"| support="
                f"{candidate['support']*100:5.1f}% "
                f"| std="
                f"{candidate['std_deg']:.3f}° "
                f"| nominalΔ="
                f"{candidate['difference_from_nominal_deg']:+.3f}° "
                f"| local_cost="
                f"{candidate['local_cost']:.3f}"
            )


    # ========================================================
    # Global search
    # ========================================================

    global_solutions = (
        find_global_solutions(
            candidate_map
        )
    )


    if not global_solutions:

        raise RuntimeError(
            "No global solution"
        )


    best = global_solutions[
        0
    ]


    second_score = (
        global_solutions[
            1
        ][
            "score"
        ]
        if len(
            global_solutions
        ) >= 2
        else None
    )


    score_margin = (
        float(
            second_score
            - best[
                "score"
            ]
        )
        if second_score
        is not None
        else None
    )


    print()
    print(
        "=" * 100
    )

    print(
        "TOP GLOBAL SOLUTIONS"
    )

    print(
        "=" * 100
    )


    for rank, solution in enumerate(
        global_solutions[
            :5
        ],
        start=1,
    ):

        print(
            f"#{rank} "
            f"score="
            f"{solution['score']:.4f} "
            f"| closure="
            f"{solution['closure_deg']:+.4f}° "
            f"| C9-positive="
            f"{solution['positive_c9_deg']:+.3f}° "
            f"| C9-negative="
            f"{solution['negative_c9_deg']:+.3f}°"
        )


    print()
    print(
        "SELECTED EDGE CLUSTERS"
    )


    selected = best[
        "selection"
    ]


    for (
        preset_a,
        preset_b,
    ) in PAIRS:

        key = (
            f"{preset_a}-"
            f"{preset_b}"
        )

        candidate = selected[
            key
        ]

        print(
            f"  {key:>5}: "
            f"{candidate['center_deg']:+9.3f}° "
            f"| n="
            f"{candidate['count']}/"
            f"{candidate['total']} "
            f"| support="
            f"{candidate['support']*100:5.1f}% "
            f"| std="
            f"{candidate['std_deg']:.3f}° "
            f"| marks="
            f"{candidate['indices']}"
        )


    # ========================================================
    # Weighted graph solution
    # ========================================================

    graph = solve_graph(
        selected
    )


    centers = graph[
        "centers"
    ]


    presets = {}


    for preset in range(
        1,
        10,
    ):

        unwrapped = float(
            centers[
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
    # Final quality gates
    # ========================================================

    min_selected_count = min(
        candidate[
            "count"
        ]
        for candidate
        in selected.values()
    )


    min_selected_support = min(
        candidate[
            "support"
        ]
        for candidate
        in selected.values()
    )


    max_selected_std = max(
        candidate[
            "std_deg"
        ]
        for candidate
        in selected.values()
    )


    max_selected_nominal_diff = max(
        abs(
            candidate[
                "difference_from_nominal_deg"
            ]
        )
        for candidate
        in selected.values()
    )


    checks = {
        "graph_rank_8": (
            graph[
                "rank"
            ]
            == 8
        ),

        "selected_cluster_min_3_marks": (
            min_selected_count
            >= 3
        ),

        "selected_cluster_support_ge_0_25": (
            min_selected_support
            >= 0.25
        ),

        "selected_cluster_std_le_1_25_deg": (
            max_selected_std
            <= 1.25
        ),

        "selected_cluster_nominal_diff_le_8_deg": (
            max_selected_nominal_diff
            <= 8.0
        ),

        "global_pre_ls_closure_le_2_deg": (
            abs(
                best[
                    "closure_deg"
                ]
            )
            <= 2.0
        ),

        "graph_rmse_le_0_75_deg": (
            graph[
                "rmse_deg"
            ]
            <= 0.75
        ),

        "graph_max_residual_le_1_50_deg": (
            graph[
                "max_residual_deg"
            ]
            <= 1.50
        ),
    }


    passed = all(
        checks.values()
    )


    status = (
        "PASS_FOR_CROSS_PRESET_VALIDATION"
        if passed
        else
        "REVIEW_REQUIRED"
    )


    # ========================================================
    # JSON-safe candidates
    # ========================================================

    payload = {
        "format": (
            "smart-fire-preset-geometry-v1"
        ),

        "solver_version": 3,

        "method": (
            "manual-overlap-marks"
            "+calibrated-undistorted-rays"
            "+multi-cluster-candidates"
            "+soft-mechanical-prior"
            "+global-loop-closure"
            "+weighted-graph-least-squares"
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

        "raw_pairs": raw_pairs,

        "candidate_clusters": (
            candidate_map
        ),

        "selected_clusters": (
            selected
        ),

        "global_selection": {
            "score": float(
                best[
                    "score"
                ]
            ),

            "score_margin_to_second": (
                score_margin
            ),

            "pre_ls_closure_deg": float(
                best[
                    "closure_deg"
                ]
            ),

            "positive_branch_c9_deg": (
                float(
                    best[
                        "positive_c9_deg"
                    ]
                )
            ),

            "negative_branch_c9_deg": (
                float(
                    best[
                        "negative_c9_deg"
                    ]
                )
            ),
        },

        "presets": presets,

        "graph_weights": (
            graph[
                "weights"
            ]
        ),

        "graph_residuals": (
            graph[
                "residuals"
            ]
        ),

        "metrics": {
            "graph_rank": int(
                graph[
                    "rank"
                ]
            ),

            "graph_rmse_deg": float(
                graph[
                    "rmse_deg"
                ]
            ),

            "graph_max_residual_deg": float(
                graph[
                    "max_residual_deg"
                ]
            ),

            "pre_ls_loop_closure_deg": float(
                best[
                    "closure_deg"
                ]
            ),

            "min_selected_cluster_count": int(
                min_selected_count
            ),

            "min_selected_support": float(
                min_selected_support
            ),

            "max_selected_std_deg": float(
                max_selected_std
            ),

            "max_selected_nominal_difference_deg": (
                float(
                    max_selected_nominal_diff
                )
            ),

            "global_score_margin": (
                score_margin
            ),
        },

        "quality_checks": checks,

        "status": status,

        "note": (
            "This result establishes internal "
            "geometry consistency only. "
            "Independent same-target cross-preset "
            "validation is required before runtime "
            "installation."
        ),
    }


    output = (
        result_dir
        / "preset_geometry_candidate_v3.json"
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
        "=" * 100
    )

    print(
        "SOLVED RELATIVE OPTICAL CENTER MAP"
    )

    print(
        "=" * 100
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
            f"| physical="
            f"{item['physical_nominal_deg']:7.3f}°"
        )


    print()
    print(
        "-" * 100
    )

    print(
        "GLOBAL / GRAPH QUALITY"
    )

    print(
        "-" * 100
    )


    print(
        f"Pre-LS loop closure       : "
        f"{best['closure_deg']:+.4f}°"
    )

    print(
        f"Graph rank                : "
        f"{graph['rank']}/8"
    )

    print(
        f"Graph RMSE                : "
        f"{graph['rmse_deg']:.4f}°"
    )

    print(
        f"Graph max residual        : "
        f"{graph['max_residual_deg']:.4f}°"
    )

    print(
        f"Minimum cluster count     : "
        f"{min_selected_count}"
    )

    print(
        f"Minimum cluster support   : "
        f"{min_selected_support*100:.1f}%"
    )

    print(
        f"Maximum selected std      : "
        f"{max_selected_std:.4f}°"
    )

    print(
        f"Maximum nominal deviation : "
        f"{max_selected_nominal_diff:.4f}°"
    )

    if score_margin is not None:

        print(
            f"Best-vs-second score gap  : "
            f"{score_margin:.4f}"
        )


    print()
    print(
        "QUALITY CHECKS"
    )


    for name, passed_check in (
        checks.items()
    ):

        print(
            f"  "
            f"{'PASS' if passed_check else 'FAIL'} "
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
        "=" * 100
    )


if __name__ == "__main__":
    main()
