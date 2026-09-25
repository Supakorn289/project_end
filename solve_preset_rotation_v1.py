#!/usr/bin/env python3

import json
import math
from collections import deque
from pathlib import Path

import cv2
import numpy as np

try:
    from scipy.optimize import least_squares
except Exception as exc:
    raise RuntimeError(
        "scipy.optimize.least_squares is required"
    ) from exc


PAIR_LIST = [
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


PAIR_KEYS = [
    f"{a}-{b}"
    for a, b in PAIR_LIST
]


RANSAC_THRESHOLD_DEG = 2.0
RANSAC_ITERATIONS = 2500

MIN_PAIR_INLIERS = 3

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720


SITE_DIR = Path(
    Path(
        "/home/fire/current_site_setup_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)


CURRENT_VALIDATION_DIR = Path(
    Path(
        "/home/fire/current_cross_validation_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)


INTRINSICS_FILE = (
    Path("/opt/smart-fire-detection-v2")
    / "calibration"
    / "camera_intrinsics.json"
)


CALIBRATION_MARKS = (
    SITE_DIR
    / "marks"
    / "marks.json"
)


HOLDOUT_MARKS = (
    CURRENT_VALIDATION_DIR
    / "cross_preset_marks.json"
)


RESULT_DIR = (
    SITE_DIR
    / "results"
)

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


HOLDOUT_RESULT_FILE = (
    CURRENT_VALIDATION_DIR
    / "preset_rotation_holdout_result_v1.json"
)


FINAL_CANDIDATE_FILE = (
    RESULT_DIR
    / "preset_rotation_candidate_v1.json"
)


# ============================================================
# Utility
# ============================================================

def normalize_signed_deg(value):
    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


def angle_between_deg(a, b):

    a = np.asarray(
        a,
        dtype=float,
    )

    b = np.asarray(
        b,
        dtype=float,
    )

    dot = float(
        np.clip(
            np.dot(a, b),
            -1.0,
            1.0,
        )
    )

    return math.degrees(
        math.acos(dot)
    )


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


def rotvec_to_matrix(v):

    R, _ = cv2.Rodrigues(
        np.asarray(
            v,
            dtype=np.float64,
        ).reshape(3, 1)
    )

    return R


def matrix_to_rotvec(R):

    v, _ = cv2.Rodrigues(
        np.asarray(
            R,
            dtype=np.float64,
        )
    )

    return v.reshape(3)


# ============================================================
# Flexible camera-intrinsics loader
# ============================================================

def recursive_find(
    obj,
    wanted_keys,
):

    if isinstance(
        obj,
        dict,
    ):

        for key in wanted_keys:

            if key in obj:
                return obj[key]

        for value in obj.values():

            found = recursive_find(
                value,
                wanted_keys,
            )

            if found is not None:
                return found

    elif isinstance(
        obj,
        list,
    ):

        for value in obj:

            found = recursive_find(
                value,
                wanted_keys,
            )

            if found is not None:
                return found

    return None


def scalar_value(
    data,
    names,
):

    value = recursive_find(
        data,
        names,
    )

    if value is None:
        return None

    if isinstance(
        value,
        (int, float),
    ):
        return float(value)

    return None


def extract_numeric_array(
    value,
):

    if value is None:
        return None

    if isinstance(
        value,
        dict,
    ):

        for key in (
            "data",
            "values",
            "matrix",
            "coefficients",
        ):

            if key in value:
                return extract_numeric_array(
                    value[key]
                )

    if isinstance(
        value,
        list,
    ):

        try:
            return np.asarray(
                value,
                dtype=np.float64,
            )

        except Exception:
            return None

    return None


def load_intrinsics():

    if not INTRINSICS_FILE.exists():

        raise RuntimeError(
            f"Missing intrinsics: "
            f"{INTRINSICS_FILE}"
        )


    data = json.loads(
        INTRINSICS_FILE.read_text(
            encoding="utf-8"
        )
    )


    camera_matrix_raw = (
        recursive_find(
            data,
            (
                "camera_matrix",
                "cameraMatrix",
                "K",
            ),
        )
    )


    K_array = extract_numeric_array(
        camera_matrix_raw
    )


    if (
        K_array is not None
        and
        K_array.size == 9
    ):

        K = K_array.reshape(
            3,
            3,
        )

    else:

        fx = scalar_value(
            data,
            ("fx",)
        )

        fy = scalar_value(
            data,
            ("fy",)
        )

        cx = scalar_value(
            data,
            ("cx",)
        )

        cy = scalar_value(
            data,
            ("cy",)
        )


        if None in (
            fx,
            fy,
            cx,
            cy,
        ):

            raise RuntimeError(
                "Could not extract "
                "fx/fy/cx/cy from "
                f"{INTRINSICS_FILE}"
            )


        K = np.array(
            [
                [fx, 0.0, cx],
                [0.0, fy, cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )


    distortion_raw = (
        recursive_find(
            data,
            (
                "dist_coeffs",
                "distCoeffs",
                "distortion_coefficients",
                "distortion",
            ),
        )
    )


    D_array = extract_numeric_array(
        distortion_raw
    )


    if (
        D_array is not None
        and
        D_array.size >= 4
    ):

        D = D_array.reshape(-1)

    else:

        k1 = scalar_value(
            data,
            ("k1",)
        )

        k2 = scalar_value(
            data,
            ("k2",)
        )

        p1 = scalar_value(
            data,
            ("p1",)
        )

        p2 = scalar_value(
            data,
            ("p2",)
        )

        k3 = scalar_value(
            data,
            ("k3",)
        )


        if None in (
            k1,
            k2,
            p1,
            p2,
        ):

            raise RuntimeError(
                "Could not extract "
                "distortion coefficients"
            )


        if k3 is None:
            k3 = 0.0


        D = np.array(
            [
                k1,
                k2,
                p1,
                p2,
                k3,
            ],
            dtype=np.float64,
        )


    return (
        K.astype(
            np.float64
        ),
        D.astype(
            np.float64
        ),
    )


# ============================================================
# Full calibrated 3-D ray
#
# Camera coordinate:
#   +X = image right
#   +Y = image down
#   +Z = optical forward
# ============================================================

def pixel_to_unit_ray(
    x,
    y,
    K,
    D,
):

    point = np.array(
        [
            [
                [
                    float(x),
                    float(y),
                ]
            ]
        ],
        dtype=np.float64,
    )


    undistorted = (
        cv2.undistortPoints(
            point,
            K,
            D,
        )
        .reshape(2)
    )


    ray = np.array(
        [
            float(
                undistorted[0]
            ),
            float(
                undistorted[1]
            ),
            1.0,
        ],
        dtype=np.float64,
    )


    norm = float(
        np.linalg.norm(
            ray
        )
    )


    if norm <= 0.0:
        raise RuntimeError(
            "Invalid zero-length ray"
        )


    return (
        ray
        / norm
    )


# ============================================================
# MARK loading
# ============================================================

def load_mark_file(
    path,
    source_name,
    K,
    D,
):

    path = Path(path)

    if not path.exists():
        raise RuntimeError(
            f"Missing mark file: {path}"
        )


    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


    output = {
        key: []
        for key in PAIR_KEYS
    }


    pairs = payload.get(
        "pairs",
        {}
    )


    for key in PAIR_KEYS:

        for index, mark in enumerate(
            pairs.get(
                key,
                [],
            ),
            start=1,
        ):

            xa, ya = mark["a"]
            xb, yb = mark["b"]


            ray_a = pixel_to_unit_ray(
                xa,
                ya,
                K,
                D,
            )


            ray_b = pixel_to_unit_ray(
                xb,
                yb,
                K,
                D,
            )


            output[
                key
            ].append(
                {
                    "source": (
                        source_name
                    ),

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

                    "ray_a": ray_a,

                    "ray_b": ray_b,
                }
            )


    return output


def merge_observations(
    datasets,
):

    merged = {
        key: []
        for key in PAIR_KEYS
    }


    for dataset in datasets:

        for key in PAIR_KEYS:

            merged[
                key
            ].extend(
                dataset[
                    key
                ]
            )


    return merged


# ============================================================
# Relative rotation via Wahba/Kabsch
#
# Solve R_b_to_a such that:
#
#     ray_a ~= R_b_to_a @ ray_b
#
# ============================================================

def fit_rotation_b_to_a(
    rays_a,
    rays_b,
):

    A = np.asarray(
        rays_a,
        dtype=np.float64,
    )

    B = np.asarray(
        rays_b,
        dtype=np.float64,
    )


    if (
        len(A)
        != len(B)
        or
        len(A) < 2
    ):

        raise RuntimeError(
            "Need >=2 ray pairs"
        )


    H = (
        B.T
        @ A
    )


    U, _, Vt = np.linalg.svd(
        H
    )


    R = (
        Vt.T
        @ U.T
    )


    if np.linalg.det(
        R
    ) < 0.0:

        Vt[
            -1,
            :
        ] *= -1.0

        R = (
            Vt.T
            @ U.T
        )


    return R


def residual_angles_deg(
    R_b_to_a,
    rays_a,
    rays_b,
):

    A = np.asarray(
        rays_a,
        dtype=np.float64,
    )

    B = np.asarray(
        rays_b,
        dtype=np.float64,
    )


    predicted = (
        R_b_to_a
        @ B.T
    ).T


    dots = np.sum(
        predicted
        * A,
        axis=1,
    )


    dots = np.clip(
        dots,
        -1.0,
        1.0,
    )


    return np.degrees(
        np.arccos(
            dots
        )
    )


def robust_relative_rotation(
    observations,
    seed,
):

    if len(
        observations
    ) < MIN_PAIR_INLIERS:

        raise RuntimeError(
            "Not enough observations"
        )


    A = np.asarray(
        [
            item[
                "ray_a"
            ]
            for item in observations
        ],
        dtype=np.float64,
    )


    B = np.asarray(
        [
            item[
                "ray_b"
            ]
            for item in observations
        ],
        dtype=np.float64,
    )


    n = len(A)


    rng = np.random.default_rng(
        int(seed)
    )


    best_mask = None
    best_score = None


    sample_size = min(
        3,
        n,
    )


    for _ in range(
        RANSAC_ITERATIONS
    ):

        indices = rng.choice(
            n,
            size=sample_size,
            replace=False,
        )


        try:

            R = fit_rotation_b_to_a(
                A[
                    indices
                ],
                B[
                    indices
                ],
            )

        except Exception:
            continue


        errors = residual_angles_deg(
            R,
            A,
            B,
        )


        mask = (
            errors
            <= RANSAC_THRESHOLD_DEG
        )


        count = int(
            np.count_nonzero(
                mask
            )
        )


        if count < MIN_PAIR_INLIERS:
            continue


        median = float(
            np.median(
                errors[
                    mask
                ]
            )
        )


        p90 = float(
            np.percentile(
                errors[
                    mask
                ],
                90,
            )
        )


        score = (
            count,
            -median,
            -p90,
        )


        if (
            best_score is None
            or
            score > best_score
        ):

            best_score = score
            best_mask = mask


    if best_mask is None:

        raise RuntimeError(
            "RANSAC could not find "
            "a valid rotation"
        )


    #
    # Refit on selected inliers.
    #
    R = fit_rotation_b_to_a(
        A[
            best_mask
        ],
        B[
            best_mask
        ],
    )


    #
    # One robust refinement pass.
    #
    errors = residual_angles_deg(
        R,
        A,
        B,
    )


    refined_mask = (
        errors
        <= RANSAC_THRESHOLD_DEG
    )


    if (
        np.count_nonzero(
            refined_mask
        )
        >= MIN_PAIR_INLIERS
    ):

        best_mask = (
            refined_mask
        )


        R = fit_rotation_b_to_a(
            A[
                best_mask
            ],
            B[
                best_mask
            ],
        )


    errors = residual_angles_deg(
        R,
        A,
        B,
    )


    inlier_errors = errors[
        best_mask
    ]


    inlier_count = int(
        np.count_nonzero(
            best_mask
        )
    )


    inlier_fraction = float(
        inlier_count
        / n
    )


    median = float(
        np.median(
            inlier_errors
        )
    )


    mean = float(
        np.mean(
            inlier_errors
        )
    )


    p90 = float(
        np.percentile(
            inlier_errors,
            90,
        )
    )


    max_error = float(
        np.max(
            inlier_errors
        )
    )


    mad = float(
        np.median(
            np.abs(
                inlier_errors
                - median
            )
        )
    )


    robust_sigma = float(
        1.4826
        * mad
    )


    #
    # Weight for rotation graph.
    #
    # Avoid huge weights from tiny residual values.
    #
    sigma_for_weight = max(
        0.35,
        robust_sigma,
        median,
    )


    weight = (
        math.sqrt(
            inlier_count
        )
        * inlier_fraction
        / sigma_for_weight
    )


    weight = float(
        np.clip(
            weight,
            0.50,
            8.00,
        )
    )


    inlier_indices = [
        int(index)
        for index, keep
        in enumerate(
            best_mask,
            start=1,
        )
        if keep
    ]


    return {
        "R_b_to_a": R,

        "total_count": int(
            n
        ),

        "inlier_count": (
            inlier_count
        ),

        "inlier_fraction": (
            inlier_fraction
        ),

        "median_error_deg": (
            median
        ),

        "mean_error_deg": (
            mean
        ),

        "p90_error_deg": (
            p90
        ),

        "max_error_deg": (
            max_error
        ),

        "robust_sigma_deg": (
            robust_sigma
        ),

        "weight": weight,

        "inlier_indices": (
            inlier_indices
        ),
    }


# ============================================================
# Rotation graph
#
# Q_i maps camera-i ray -> P1 reference frame.
#
# Relative edge stores:
#
#     ray_a = R_b_to_a @ ray_b
#
# therefore:
#
#     Q_b = Q_a @ R_b_to_a
#
# ============================================================

def build_initial_orientations(
    edges,
):

    adjacency = {
        preset: []
        for preset in range(
            1,
            10,
        )
    }


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"

        R_b_to_a = edges[
            key
        ][
            "R_b_to_a"
        ]


        adjacency[
            a
        ].append(
            (
                b,
                R_b_to_a,
            )
        )


        adjacency[
            b
        ].append(
            (
                a,
                R_b_to_a.T,
            )
        )


    Q = {
        1: np.eye(
            3,
            dtype=np.float64,
        )
    }


    queue = deque(
        [1]
    )


    while queue:

        current = queue.popleft()


        for (
            other,
            R_other_to_current,
        ) in adjacency[
            current
        ]:

            if other in Q:
                continue


            #
            # Q_other
            # =
            # Q_current
            # @ R_other_to_current
            #
            Q[
                other
            ] = (
                Q[
                    current
                ]
                @ R_other_to_current
            )


            queue.append(
                other
            )


    if len(Q) != 9:

        raise RuntimeError(
            "Rotation graph is disconnected"
        )


    return Q


def solve_rotation_graph(
    edges,
):

    initial_Q = (
        build_initial_orientations(
            edges
        )
    )


    variable_presets = list(
        range(
            2,
            10,
        )
    )


    index_map = {
        preset: index
        for index, preset
        in enumerate(
            variable_presets
        )
    }


    def orientations_from_x(
        x,
    ):

        Q = {
            1: np.eye(
                3,
                dtype=np.float64,
            )
        }


        for preset in variable_presets:

            base = (
                3
                * index_map[
                    preset
                ]
            )


            delta = x[
                base:
                base + 3
            ]


            Q[
                preset
            ] = (
                initial_Q[
                    preset
                ]
                @ rotvec_to_matrix(
                    delta
                )
            )


        return Q


    def graph_residual(
        x,
    ):

        Q = orientations_from_x(
            x
        )


        residuals = []


        for (
            a,
            b,
        ) in PAIR_LIST:

            key = f"{a}-{b}"


            edge = edges[
                key
            ]


            R_b_to_a = edge[
                "R_b_to_a"
            ]


            expected_Qb = (
                Q[
                    a
                ]
                @ R_b_to_a
            )


            error_R = (
                expected_Qb.T
                @ Q[
                    b
                ]
            )


            error_rotvec = (
                matrix_to_rotvec(
                    error_R
                )
            )


            scale = math.sqrt(
                edge[
                    "weight"
                ]
            )


            residuals.extend(
                (
                    scale
                    * error_rotvec
                ).tolist()
            )


        return np.asarray(
            residuals,
            dtype=np.float64,
        )


    x0 = np.zeros(
        3
        * len(
            variable_presets
        ),
        dtype=np.float64,
    )


    result = least_squares(
        graph_residual,
        x0,
        method="trf",
        loss="soft_l1",
        f_scale=math.radians(
            0.50
        ),
        max_nfev=3000,
    )


    Q = orientations_from_x(
        result.x
    )


    graph_edge_residuals = {}


    graph_angles = []


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"


        expected_Qb = (
            Q[
                a
            ]
            @ edges[
                key
            ][
                "R_b_to_a"
            ]
        )


        error_R = (
            expected_Qb.T
            @ Q[
                b
            ]
        )


        error_deg = (
            rotation_angle_deg(
                error_R
            )
        )


        graph_edge_residuals[
            key
        ] = float(
            error_deg
        )


        graph_angles.append(
            error_deg
        )


    graph_angles = np.asarray(
        graph_angles,
        dtype=float,
    )


    return {
        "orientations": Q,

        "optimizer_success": bool(
            result.success
        ),

        "optimizer_message": str(
            result.message
        ),

        "graph_rmse_deg": float(
            math.sqrt(
                np.mean(
                    graph_angles ** 2
                )
            )
        ),

        "graph_max_residual_deg": float(
            np.max(
                graph_angles
            )
        ),

        "edge_residuals_deg": (
            graph_edge_residuals
        ),
    }


# ============================================================
# Optical-axis reporting
# ============================================================

def optical_axis_metrics(
    Q,
):

    forward = (
        Q
        @ np.array(
            [
                0.0,
                0.0,
                1.0,
            ],
            dtype=float,
        )
    )


    azimuth = math.degrees(
        math.atan2(
            float(
                forward[0]
            ),
            float(
                forward[2]
            ),
        )
    )


    elevation = math.degrees(
        math.atan2(
            -float(
                forward[1]
            ),
            math.hypot(
                float(
                    forward[0]
                ),
                float(
                    forward[2]
                ),
            ),
        )
    )


    return {
        "azimuth_deg": (
            azimuth
            % 360.0
        ),

        "azimuth_signed_deg": (
            normalize_signed_deg(
                azimuth
            )
        ),

        "elevation_deg": float(
            elevation
        ),

        "forward_vector": [
            float(v)
            for v in forward
        ],
    }


# ============================================================
# Holdout evaluation
# ============================================================

def vector_azimuth_deg(v):

    return math.degrees(
        math.atan2(
            float(v[0]),
            float(v[2]),
        )
    ) % 360.0


def vector_elevation_deg(v):

    return math.degrees(
        math.atan2(
            -float(v[1]),
            math.hypot(
                float(v[0]),
                float(v[2]),
            ),
        )
    )


def evaluate_dataset(
    observations,
    Q,
):

    pair_results = {}

    all_abs_az = []
    all_3d = []


    pass_count = 0
    review_count = 0
    fail_count = 0


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"


        items = observations[
            key
        ]


        if len(items) < 3:

            raise RuntimeError(
                f"Holdout pair {key} "
                f"has only {len(items)} marks"
            )


        target_rows = []

        abs_az_values = []
        angular_values = []


        for index, item in enumerate(
            items,
            start=1,
        ):

            world_a = (
                Q[
                    a
                ]
                @ item[
                    "ray_a"
                ]
            )


            world_b = (
                Q[
                    b
                ]
                @ item[
                    "ray_b"
                ]
            )


            world_a = (
                world_a
                / np.linalg.norm(
                    world_a
                )
            )


            world_b = (
                world_b
                / np.linalg.norm(
                    world_b
                )
            )


            az_a = (
                vector_azimuth_deg(
                    world_a
                )
            )


            az_b = (
                vector_azimuth_deg(
                    world_b
                )
            )


            elevation_a = (
                vector_elevation_deg(
                    world_a
                )
            )


            elevation_b = (
                vector_elevation_deg(
                    world_b
                )
            )


            az_error = (
                normalize_signed_deg(
                    az_a
                    - az_b
                )
            )


            elevation_error = (
                elevation_a
                - elevation_b
            )


            angular_error = (
                angle_between_deg(
                    world_a,
                    world_b,
                )
            )


            abs_az = abs(
                az_error
            )


            abs_az_values.append(
                abs_az
            )


            angular_values.append(
                angular_error
            )


            all_abs_az.append(
                abs_az
            )


            all_3d.append(
                angular_error
            )


            target_rows.append(
                {
                    "index": int(
                        index
                    ),

                    "azimuth_a_deg": (
                        float(
                            az_a
                        )
                    ),

                    "azimuth_b_deg": (
                        float(
                            az_b
                        )
                    ),

                    "azimuth_error_deg": (
                        float(
                            az_error
                        )
                    ),

                    "elevation_a_deg": (
                        float(
                            elevation_a
                        )
                    ),

                    "elevation_b_deg": (
                        float(
                            elevation_b
                        )
                    ),

                    "elevation_error_deg": (
                        float(
                            elevation_error
                        )
                    ),

                    "angular_3d_error_deg": (
                        float(
                            angular_error
                        )
                    ),
                }
            )


        abs_az_values = np.asarray(
            abs_az_values,
            dtype=float,
        )


        angular_values = np.asarray(
            angular_values,
            dtype=float,
        )


        median_az = float(
            np.median(
                abs_az_values
            )
        )


        p90_az = float(
            np.percentile(
                abs_az_values,
                90,
            )
        )


        max_az = float(
            np.max(
                abs_az_values
            )
        )


        fraction_le_2 = float(
            np.mean(
                abs_az_values
                <= 2.0
            )
        )


        median_3d = float(
            np.median(
                angular_values
            )
        )


        p90_3d = float(
            np.percentile(
                angular_values,
                90,
            )
        )


        if (
            median_az <= 1.50
            and
            p90_az <= 3.00
            and
            fraction_le_2 >= 0.70
            and
            median_3d <= 2.00
        ):

            status = "PASS"
            pass_count += 1

        elif (
            median_az <= 2.50
            and
            p90_az <= 5.00
            and
            median_3d <= 3.00
        ):

            status = "REVIEW"
            review_count += 1

        else:

            status = "FAIL"
            fail_count += 1


        pair_results[
            key
        ] = {
            "target_count": int(
                len(items)
            ),

            "median_abs_azimuth_error_deg": (
                median_az
            ),

            "p90_abs_azimuth_error_deg": (
                p90_az
            ),

            "max_abs_azimuth_error_deg": (
                max_az
            ),

            "fraction_le_2deg": (
                fraction_le_2
            ),

            "median_3d_error_deg": (
                median_3d
            ),

            "p90_3d_error_deg": (
                p90_3d
            ),

            "status": status,

            "targets": (
                target_rows
            ),
        }


    all_abs_az = np.asarray(
        all_abs_az,
        dtype=float,
    )


    all_3d = np.asarray(
        all_3d,
        dtype=float,
    )


    global_metrics = {
        "target_count": int(
            len(
                all_abs_az
            )
        ),

        "median_abs_azimuth_error_deg": float(
            np.median(
                all_abs_az
            )
        ),

        "mean_abs_azimuth_error_deg": float(
            np.mean(
                all_abs_az
            )
        ),

        "p90_abs_azimuth_error_deg": float(
            np.percentile(
                all_abs_az,
                90,
            )
        ),

        "max_abs_azimuth_error_deg": float(
            np.max(
                all_abs_az
            )
        ),

        "median_3d_error_deg": float(
            np.median(
                all_3d
            )
        ),

        "p90_3d_error_deg": float(
            np.percentile(
                all_3d,
                90,
            )
        ),

        "pass_pairs": int(
            pass_count
        ),

        "review_pairs": int(
            review_count
        ),

        "fail_pairs": int(
            fail_count
        ),
    }


    holdout_pass = (
        fail_count == 0
        and
        global_metrics[
            "median_abs_azimuth_error_deg"
        ] <= 1.50
        and
        global_metrics[
            "p90_abs_azimuth_error_deg"
        ] <= 3.00
    )


    return {
        "pairs": pair_results,

        "global_metrics": (
            global_metrics
        ),

        "pass_for_final_refit": bool(
            holdout_pass
        ),
    }


# ============================================================
# Model fitting
# ============================================================

def fit_model(
    observations,
):

    edges = {}


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"


        result = robust_relative_rotation(
            observations[
                key
            ],
            seed=(
                1000
                + a * 100
                + b
            ),
        )


        edges[
            key
        ] = result


    graph = solve_rotation_graph(
        edges
    )


    return (
        edges,
        graph
    )


# ============================================================
# JSON serialization helpers
# ============================================================

def serialize_edges(
    edges,
):

    output = {}


    for key, edge in edges.items():

        output[
            key
        ] = {
            "R_b_to_a": (
                edge[
                    "R_b_to_a"
                ].tolist()
            ),

            "total_count": int(
                edge[
                    "total_count"
                ]
            ),

            "inlier_count": int(
                edge[
                    "inlier_count"
                ]
            ),

            "inlier_fraction": float(
                edge[
                    "inlier_fraction"
                ]
            ),

            "median_error_deg": float(
                edge[
                    "median_error_deg"
                ]
            ),

            "mean_error_deg": float(
                edge[
                    "mean_error_deg"
                ]
            ),

            "p90_error_deg": float(
                edge[
                    "p90_error_deg"
                ]
            ),

            "max_error_deg": float(
                edge[
                    "max_error_deg"
                ]
            ),

            "robust_sigma_deg": float(
                edge[
                    "robust_sigma_deg"
                ]
            ),

            "weight": float(
                edge[
                    "weight"
                ]
            ),
        }


    return output


def serialize_orientations(
    Q,
):

    output = {}


    for preset in range(
        1,
        10,
    ):

        metrics = (
            optical_axis_metrics(
                Q[
                    preset
                ]
            )
        )


        output[
            str(
                preset
            )
        ] = {
            "camera_to_reference_rotation": (
                Q[
                    preset
                ].tolist()
            ),

            **metrics,
        }


    return output


# ============================================================
# Console reports
# ============================================================

def print_edge_report(
    title,
    edges,
    graph,
):

    print()
    print("=" * 108)
    print(title)
    print("=" * 108)


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"

        edge = edges[
            key
        ]


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
            f"| graph="
            f"{graph['edge_residuals_deg'][key]:6.3f}°"
        )


    print(
        f"Graph RMSE : "
        f"{graph['graph_rmse_deg']:.4f}°"
    )

    print(
        f"Graph max  : "
        f"{graph['graph_max_residual_deg']:.4f}°"
    )


    print()
    print(
        "OPTICAL AXES RELATIVE TO P1"
    )


    for preset in range(
        1,
        10,
    ):

        m = optical_axis_metrics(
            graph[
                "orientations"
            ][
                preset
            ]
        )


        print(
            f"P{preset} "
            f"| az="
            f"{m['azimuth_signed_deg']:+9.3f}° "
            f"| elev="
            f"{m['elevation_deg']:+8.3f}°"
        )


def print_holdout_report(
    evaluation,
):

    print()
    print("=" * 108)
    print(
        "FRESH HOLDOUT — 3-D ROTATION VALIDATION"
    )
    print("=" * 108)


    for (
        a,
        b,
    ) in PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            evaluation[
                "pairs"
            ][
                key
            ]
        )


        print(
            f"{key:>5} "
            f"| n="
            f"{item['target_count']:3d} "
            f"| median az="
            f"{item['median_abs_azimuth_error_deg']:6.3f}° "
            f"| p90 az="
            f"{item['p90_abs_azimuth_error_deg']:6.3f}° "
            f"| <=2°="
            f"{item['fraction_le_2deg']*100:5.1f}% "
            f"| median 3D="
            f"{item['median_3d_error_deg']:6.3f}° "
            f"| {item['status']}"
        )


    metrics = (
        evaluation[
            "global_metrics"
        ]
    )


    print()
    print(
        "GLOBAL HOLDOUT"
    )

    print(
        f"Targets        : "
        f"{metrics['target_count']}"
    )

    print(
        f"Pairs P/R/F    : "
        f"{metrics['pass_pairs']}/"
        f"{metrics['review_pairs']}/"
        f"{metrics['fail_pairs']}"
    )

    print(
        f"Median abs az  : "
        f"{metrics['median_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Mean abs az    : "
        f"{metrics['mean_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"P90 abs az     : "
        f"{metrics['p90_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Max abs az     : "
        f"{metrics['max_abs_azimuth_error_deg']:.4f}°"
    )

    print(
        f"Median 3D      : "
        f"{metrics['median_3d_error_deg']:.4f}°"
    )

    print(
        f"P90 3D         : "
        f"{metrics['p90_3d_error_deg']:.4f}°"
    )

    print(
        "RESULT         : "
        + (
            "PASS_FOR_FINAL_ALL_MARK_REFIT"
            if evaluation[
                "pass_for_final_refit"
            ]
            else
            "3D_ROTATION_REVIEW_REQUIRED"
        )
    )


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 108)
    print(
        "SMART FIRE PRESET 3-D ROTATION GRAPH SOLVER v1"
    )
    print("=" * 108)

    print(
        f"Site             : "
        f"{SITE_DIR}"
    )

    print(
        f"Current holdout  : "
        f"{CURRENT_VALIDATION_DIR}"
    )

    print(
        f"Intrinsics       : "
        f"{INTRINSICS_FILE}"
    )

    print(
        "Model            : "
        "central-camera pure 3-D rotation"
    )

    print(
        "Runtime images   : "
        "NOT REQUIRED"
    )


    K, D = load_intrinsics()


    print()
    print("Camera matrix K:")
    print(K)

    print(
        "Distortion D:",
        D.tolist(),
    )


    #
    # --------------------------------------------------------
    # Phase A training sources
    #
    # Calibration marks +
    # all archived cross-preset mark sets EXCEPT current.
    # --------------------------------------------------------
    #

    train_sources = []


    calibration_dataset = (
        load_mark_file(
            CALIBRATION_MARKS,
            "site_calibration_marks",
            K,
            D,
        )
    )


    train_sources.append(
        calibration_dataset
    )


    train_source_names = [
        str(
            CALIBRATION_MARKS
        )
    ]


    for directory in sorted(
        Path(
            "/home/fire"
        ).glob(
            "cross_preset_validation_*"
        )
    ):

        if (
            directory.resolve()
            ==
            CURRENT_VALIDATION_DIR.resolve()
        ):
            continue


        mark_file = (
            directory
            / "cross_preset_marks.json"
        )


        if not mark_file.exists():
            continue


        dataset = load_mark_file(
            mark_file,
            f"archive:{directory.name}",
            K,
            D,
        )


        train_sources.append(
            dataset
        )


        train_source_names.append(
            str(
                mark_file
            )
        )


    training = merge_observations(
        train_sources
    )


    #
    # Current fresh set remains untouched as HOLDOUT.
    #
    holdout = load_mark_file(
        HOLDOUT_MARKS,
        "fresh_holdout",
        K,
        D,
    )


    print()
    print(
        "PHASE A TRAIN SOURCES"
    )

    for source in train_source_names:
        print(
            f"  - {source}"
        )


    print(
        f"HOLDOUT:"
        f" {HOLDOUT_MARKS}"
    )


    #
    # Fit using previous data only.
    #
    train_edges, train_graph = (
        fit_model(
            training
        )
    )


    print_edge_report(
        "PHASE A — TRAINED 3-D ROTATION GRAPH",
        train_edges,
        train_graph,
    )


    #
    # Independent fresh evaluation.
    #
    holdout_eval = evaluate_dataset(
        holdout,
        train_graph[
            "orientations"
        ],
    )


    print_holdout_report(
        holdout_eval
    )


    holdout_payload = {
        "format": (
            "smart-fire-preset-rotation-"
            "holdout-result-v1"
        ),

        "solver_version": 1,

        "model": (
            "central-camera-pure-3d-rotation"
        ),

        "intrinsics_file": str(
            INTRINSICS_FILE
        ),

        "training_sources": (
            train_source_names
        ),

        "holdout_source": str(
            HOLDOUT_MARKS
        ),

        "training_edges": (
            serialize_edges(
                train_edges
            )
        ),

        "training_orientations": (
            serialize_orientations(
                train_graph[
                    "orientations"
                ]
            )
        ),

        "training_graph": {
            "optimizer_success": (
                train_graph[
                    "optimizer_success"
                ]
            ),

            "optimizer_message": (
                train_graph[
                    "optimizer_message"
                ]
            ),

            "graph_rmse_deg": (
                train_graph[
                    "graph_rmse_deg"
                ]
            ),

            "graph_max_residual_deg": (
                train_graph[
                    "graph_max_residual_deg"
                ]
            ),

            "edge_residuals_deg": (
                train_graph[
                    "edge_residuals_deg"
                ]
            ),
        },

        "holdout_evaluation": (
            holdout_eval
        ),
    }


    HOLDOUT_RESULT_FILE.write_text(
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
        f"{HOLDOUT_RESULT_FILE}"
    )


    #
    # --------------------------------------------------------
    # Phase B
    #
    # Only if the independent holdout passes:
    # refit with EVERY mark set, including current.
    # --------------------------------------------------------
    #

    if not holdout_eval[
        "pass_for_final_refit"
    ]:

        print()
        print("=" * 108)

        print(
            "FINAL RESULT : "
            "3D_ROTATION_REVIEW_REQUIRED"
        )

        print(
            "No runtime candidate was installed "
            "or promoted."
        )

        print(
            "Next diagnostic: inspect P7/P8 and "
            "P8/P9 holdout residual structure; "
            "if error correlates with target depth, "
            "move to translation/parallax model."
        )

        print("=" * 108)

        return


    print()
    print("=" * 108)

    print(
        "PHASE B — HOLDOUT PASSED; "
        "FINAL REFIT WITH ALL MARKS"
    )

    print("=" * 108)


    all_sources = list(
        train_sources
    )


    all_sources.append(
        holdout
    )


    all_observations = (
        merge_observations(
            all_sources
        )
    )


    final_edges, final_graph = (
        fit_model(
            all_observations
        )
    )


    print_edge_report(
        "FINAL ALL-MARK 3-D ROTATION GRAPH",
        final_edges,
        final_graph,
    )


    final_payload = {
        "format": (
            "smart-fire-preset-rotation-v1"
        ),

        "solver_version": 1,

        "model": (
            "central-camera-pure-3d-rotation"
        ),

        "runtime_image_matching": False,

        "reference_preset": 1,

        "frame_width": (
            FRAME_WIDTH
        ),

        "frame_height": (
            FRAME_HEIGHT
        ),

        "intrinsics_file": str(
            INTRINSICS_FILE
        ),

        "sources": (
            train_source_names
            + [
                str(
                    HOLDOUT_MARKS
                )
            ]
        ),

        "holdout_gate": (
            holdout_eval
        ),

        "pair_rotations": (
            serialize_edges(
                final_edges
            )
        ),

        "presets": (
            serialize_orientations(
                final_graph[
                    "orientations"
                ]
            )
        ),

        "graph": {
            "optimizer_success": (
                final_graph[
                    "optimizer_success"
                ]
            ),

            "optimizer_message": (
                final_graph[
                    "optimizer_message"
                ]
            ),

            "graph_rmse_deg": (
                final_graph[
                    "graph_rmse_deg"
                ]
            ),

            "graph_max_residual_deg": (
                final_graph[
                    "graph_max_residual_deg"
                ]
            ),

            "edge_residuals_deg": (
                final_graph[
                    "edge_residuals_deg"
                ]
            ),
        },

        "status": (
            "PASS_CANDIDATE_NOT_INSTALLED"
        ),

        "note": (
            "Pure 3-D rotation model. "
            "No translation/parallax term. "
            "Candidate must not be installed "
            "until final fresh cross-preset "
            "validation is accepted."
        ),
    }


    FINAL_CANDIDATE_FILE.write_text(
        json.dumps(
            final_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print(
        f"FINAL CANDIDATE SAVED : "
        f"{FINAL_CANDIDATE_FILE}"
    )

    print(
        "STATUS                : "
        "PASS_CANDIDATE_NOT_INSTALLED"
    )

    print("=" * 108)


if __name__ == "__main__":
    main()
