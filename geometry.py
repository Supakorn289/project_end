import math
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


# ============================================================
# WGS84 Ellipsoid
# ============================================================

WGS84_A_M = 6378137.0
WGS84_INV_F = 298.257223563
WGS84_F = 1.0 / WGS84_INV_F
WGS84_B_M = WGS84_A_M * (1.0 - WGS84_F)

VINCENTY_TOLERANCE_RAD = 1e-12
VINCENTY_MAX_ITERATIONS = 200


def normalize_bearing(angle_deg: float) -> float:
    if not math.isfinite(angle_deg):
        raise ValueError("angle_deg must be finite")

    return angle_deg % 360.0


def normalize_longitude(longitude_deg: float) -> float:
    if not math.isfinite(longitude_deg):
        raise ValueError("longitude_deg must be finite")

    return (longitude_deg + 180.0) % 360.0 - 180.0


def focal_length_px(
    frame_width: int,
    hfov_deg: float,
) -> float:

    if frame_width <= 0:
        raise ValueError(
            "frame_width must be > 0"
        )

    if (
        not math.isfinite(hfov_deg)
        or not 0.0 < hfov_deg < 180.0
    ):
        raise ValueError(
            "hfov_deg must be between 0 and 180"
        )

    return frame_width / (
        2.0
        * math.tan(
            math.radians(hfov_deg) / 2.0
        )
    )



# ============================================================
# Calibrated Camera Ray
# ============================================================

@lru_cache(maxsize=1)
def _load_runtime_camera_intrinsics():
    """
    Load the production camera intrinsic calibration once.

    This calibration is used only for post-detection geometry.
    It does NOT modify/preprocess frames before YOLO inference.
    """

    path = (
        Path(__file__).resolve().parent
        / "calibration"
        / "camera_intrinsics.json"
    )

    if not path.is_file():
        raise RuntimeError(
            f"Camera intrinsics not found: {path}"
        )

    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not data.get(
        "valid_for_production",
        False,
    ):
        raise RuntimeError(
            "Camera intrinsics are not production-valid"
        )

    if (
        data.get("status")
        != "intrinsics_calibrated"
    ):
        raise RuntimeError(
            "Camera intrinsic status is not calibrated"
        )

    camera_matrix = np.array(
        [
            [
                float(data["fx_px"]),
                0.0,
                float(data["cx_px"]),
            ],
            [
                0.0,
                float(data["fy_px"]),
                float(data["cy_px"]),
            ],
            [
                0.0,
                0.0,
                1.0,
            ],
        ],
        dtype=np.float64,
    )

    distortion = np.asarray(
        data["distortion_coefficients"],
        dtype=np.float64,
    )

    return (
        data,
        camera_matrix,
        distortion,
    )


def calibrated_horizontal_offset_deg(
    x_px: float,
    y_px: float,
    frame_width: int,
    frame_height: int,
) -> float:
    """
    Convert a RAW distorted image pixel into the horizontal
    camera-ray angle using calibrated OpenCV intrinsics.

    Pipeline:

        raw pixel
            ↓
        lens distortion correction
            ↓
        normalized camera ray
            ↓
        horizontal angular offset

    Positive = right
    Negative = left
    """

    values = (
        x_px,
        y_px,
    )

    if not all(
        math.isfinite(v)
        for v in values
    ):
        raise ValueError(
            "Pixel coordinates must be finite"
        )

    (
        data,
        camera_matrix,
        distortion,
    ) = _load_runtime_camera_intrinsics()

    calibrated_width = int(
        data["frame_width"]
    )

    calibrated_height = int(
        data["frame_height"]
    )

    if (
        frame_width
        != calibrated_width
        or
        frame_height
        != calibrated_height
    ):
        raise RuntimeError(
            "Camera intrinsic resolution mismatch: "
            f"runtime={frame_width}x{frame_height}, "
            f"calibration="
            f"{calibrated_width}x{calibrated_height}"
        )

    point = np.array(
        [
            [
                [
                    float(x_px),
                    float(y_px),
                ]
            ]
        ],
        dtype=np.float64,
    )

    normalized = cv2.undistortPoints(
        point,
        camera_matrix,
        distortion,
    )

    ray_x = float(
        normalized[0, 0, 0]
    )

    if not math.isfinite(
        ray_x
    ):
        raise RuntimeError(
            "Invalid undistorted camera ray"
        )

    return math.degrees(
        math.atan2(
            ray_x,
            1.0,
        )
    )


def calibrated_pixel_to_bearing(
    preset_bearing_deg: float,
    x_px: float,
    y_px: float,
    frame_width: int,
    frame_height: int,
    north_offset_deg: float = 0.0,
) -> float:
    """
    Production bearing calculation using calibrated
    lens intrinsics and distortion correction.
    """

    offset_deg = (
        calibrated_horizontal_offset_deg(
            x_px,
            y_px,
            frame_width,
            frame_height,
        )
    )

    return normalize_bearing(
        preset_bearing_deg
        + north_offset_deg
        + offset_deg
    )


def pixel_to_bearing(
    preset_bearing_deg: float,
    x_px: float,
    frame_width: int,
    hfov_deg: float,
    north_offset_deg: float = 0.0,
    principal_x_px: float | None = None,
) -> float:
    """
    Pinhole projection:
    pixel X -> angular offset -> bearing
    """

    if not math.isfinite(x_px):
        raise ValueError(
            "x_px must be finite"
        )

    cx = (
        frame_width / 2.0
        if principal_x_px is None
        else principal_x_px
    )

    fx = focal_length_px(
        frame_width,
        hfov_deg,
    )

    offset_deg = math.degrees(
        math.atan2(
            x_px - cx,
            fx,
        )
    )

    return normalize_bearing(
        preset_bearing_deg
        + north_offset_deg
        + offset_deg
    )


def gps_from_bearing_distance(
    camera_lat: float,
    camera_lon: float,
    distance_m: float,
    bearing_deg: float,
) -> tuple[float, float]:
    """
    Vincenty Direct Formula on WGS84 Ellipsoid.

    Direct Geodetic Problem:

        Start latitude/longitude
        + initial bearing
        + geodesic distance
        ->
        destination latitude/longitude

    The function signature remains compatible
    with the previous spherical implementation.
    """

    values = (
        camera_lat,
        camera_lon,
        distance_m,
        bearing_deg,
    )

    if not all(
        math.isfinite(v)
        for v in values
    ):
        raise ValueError(
            "All geolocation inputs must be finite"
        )

    if not -90.0 <= camera_lat <= 90.0:
        raise ValueError(
            "camera_lat must be between -90 and 90"
        )

    if distance_m < 0:
        raise ValueError(
            "distance_m must be >= 0"
        )

    if distance_m == 0:
        return (
            float(camera_lat),
            normalize_longitude(camera_lon),
        )

    # --------------------------------------------------------
    # WGS84 parameters
    # --------------------------------------------------------

    a = WGS84_A_M
    b = WGS84_B_M
    f = WGS84_F

    phi1 = math.radians(
        camera_lat
    )

    lambda1 = math.radians(
        normalize_longitude(camera_lon)
    )

    alpha1 = math.radians(
        normalize_bearing(bearing_deg)
    )

    sin_alpha1 = math.sin(alpha1)
    cos_alpha1 = math.cos(alpha1)

    # --------------------------------------------------------
    # Reduced latitude U1
    # --------------------------------------------------------

    tan_u1 = (
        (1.0 - f)
        * math.tan(phi1)
    )

    cos_u1 = 1.0 / math.sqrt(
        1.0 + tan_u1 * tan_u1
    )

    sin_u1 = (
        tan_u1
        * cos_u1
    )

    sigma1 = math.atan2(
        tan_u1,
        cos_alpha1,
    )

    sin_alpha = (
        cos_u1
        * sin_alpha1
    )

    cos_sq_alpha = max(
        0.0,
        1.0
        - sin_alpha * sin_alpha,
    )

    # --------------------------------------------------------
    # Ellipsoid correction
    # --------------------------------------------------------

    u_sq = (
        cos_sq_alpha
        * (
            a * a
            - b * b
        )
        / (
            b * b
        )
    )

    coeff_a = (
        1.0
        + (
            u_sq / 16384.0
        )
        * (
            4096.0
            + u_sq
            * (
                -768.0
                + u_sq
                * (
                    320.0
                    - 175.0 * u_sq
                )
            )
        )
    )

    coeff_b = (
        u_sq / 1024.0
    ) * (
        256.0
        + u_sq
        * (
            -128.0
            + u_sq
            * (
                74.0
                - 47.0 * u_sq
            )
        )
    )

    # --------------------------------------------------------
    # Solve sigma iteratively
    # --------------------------------------------------------

    sigma = (
        distance_m
        / (
            b * coeff_a
        )
    )

    converged = False

    for _ in range(
        VINCENTY_MAX_ITERATIONS
    ):

        cos_2sigma_m = math.cos(
            2.0 * sigma1
            + sigma
        )

        sin_sigma = math.sin(
            sigma
        )

        cos_sigma = math.cos(
            sigma
        )

        delta_sigma = (
            coeff_b
            * sin_sigma
            * (
                cos_2sigma_m
                + (
                    coeff_b / 4.0
                )
                * (
                    cos_sigma
                    * (
                        -1.0
                        + 2.0
                        * cos_2sigma_m
                        * cos_2sigma_m
                    )
                    - (
                        coeff_b / 6.0
                    )
                    * cos_2sigma_m
                    * (
                        -3.0
                        + 4.0
                        * sin_sigma
                        * sin_sigma
                    )
                    * (
                        -3.0
                        + 4.0
                        * cos_2sigma_m
                        * cos_2sigma_m
                    )
                )
            )
        )

        sigma_next = (
            distance_m
            / (
                b * coeff_a
            )
            + delta_sigma
        )

        if abs(
            sigma_next - sigma
        ) <= VINCENTY_TOLERANCE_RAD:

            sigma = sigma_next
            converged = True
            break

        sigma = sigma_next

    if not converged:
        raise RuntimeError(
            "Vincenty direct solution "
            "did not converge"
        )

    # --------------------------------------------------------
    # Destination latitude
    # --------------------------------------------------------

    sin_sigma = math.sin(
        sigma
    )

    cos_sigma = math.cos(
        sigma
    )

    cos_2sigma_m = math.cos(
        2.0 * sigma1
        + sigma
    )

    tmp = (
        sin_u1
        * sin_sigma
        - cos_u1
        * cos_sigma
        * cos_alpha1
    )

    phi2 = math.atan2(
        (
            sin_u1
            * cos_sigma
            + cos_u1
            * sin_sigma
            * cos_alpha1
        ),
        (
            (1.0 - f)
            * math.sqrt(
                sin_alpha
                * sin_alpha
                + tmp
                * tmp
            )
        ),
    )

    # --------------------------------------------------------
    # Destination longitude
    # --------------------------------------------------------

    lambda_delta = math.atan2(
        (
            sin_sigma
            * sin_alpha1
        ),
        (
            cos_u1
            * cos_sigma
            - sin_u1
            * sin_sigma
            * cos_alpha1
        ),
    )

    c = (
        f
        / 16.0
        * cos_sq_alpha
        * (
            4.0
            + f
            * (
                4.0
                - 3.0
                * cos_sq_alpha
            )
        )
    )

    big_l = (
        lambda_delta
        - (
            1.0 - c
        )
        * f
        * sin_alpha
        * (
            sigma
            + c
            * sin_sigma
            * (
                cos_2sigma_m
                + c
                * cos_sigma
                * (
                    -1.0
                    + 2.0
                    * cos_2sigma_m
                    * cos_2sigma_m
                )
            )
        )
    )

    lambda2 = (
        lambda1
        + big_l
    )

    lat2 = math.degrees(
        phi2
    )

    lon2 = normalize_longitude(
        math.degrees(lambda2)
    )

    return (
        lat2,
        lon2,
    )


def bearing_to_compass(
    bearing_deg: float,
) -> str:

    labels = [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]

    return labels[
        int(
            (
                normalize_bearing(
                    bearing_deg
                )
                + 22.5
            )
            // 45.0
        )
        % 8
    ]


# === FINAL_DYNAMIC_3D_RAY_V1 ===
#
# Raw distorted pixel
#   -> calibrated undistorted camera ray
#
# Camera coordinate convention:
#   +X = image right
#   +Y = image down
#   +Z = optical forward
#
# Used by dynamic preset rotation runtime.
#

def calibrated_pixel_to_unit_ray(
    x_px: float,
    y_px: float,
    frame_width: int,
    frame_height: int,
):
    """
    Convert current image pixel (x,y) into a calibrated
    unit camera ray.

    This function does NOT contain any preset bearing.
    Preset orientation is applied later by preset_geometry.py.
    """

    import json
    from pathlib import Path

    import cv2
    import numpy as np

    values = (
        x_px,
        y_px,
        frame_width,
        frame_height,
    )

    if not all(
        math.isfinite(float(v))
        for v in values
    ):
        raise ValueError(
            "Pixel/raster values must be finite"
        )

    frame_width = int(frame_width)
    frame_height = int(frame_height)

    if (
        frame_width <= 0
        or frame_height <= 0
    ):
        raise ValueError(
            "Invalid runtime frame dimensions"
        )

    intrinsics_path = (
        Path(__file__).resolve().parent
        / "calibration"
        / "camera_intrinsics.json"
    )

    if not intrinsics_path.exists():
        raise FileNotFoundError(
            f"Camera intrinsics not found: "
            f"{intrinsics_path}"
        )

    data = json.loads(
        intrinsics_path.read_text(
            encoding="utf-8"
        )
    )

    if not data.get(
        "valid_for_production",
        False,
    ):
        raise RuntimeError(
            "Camera intrinsics are not "
            "production-valid"
        )

    camera_matrix = np.asarray(
        data["camera_matrix"],
        dtype=np.float64,
    )

    distortion = np.asarray(
        data["distortion_coefficients"],
        dtype=np.float64,
    ).reshape(-1, 1)

    calibration_width = int(
        data["frame_width"]
    )

    calibration_height = int(
        data["frame_height"]
    )

    if (
        calibration_width <= 0
        or calibration_height <= 0
    ):
        raise RuntimeError(
            "Invalid intrinsic calibration size"
        )

    #
    # Scale K if runtime resolution differs while
    # preserving the same optical/crop configuration.
    #
    sx = (
        frame_width
        / float(calibration_width)
    )

    sy = (
        frame_height
        / float(calibration_height)
    )

    K = camera_matrix.copy()

    K[0, 0] *= sx
    K[0, 2] *= sx

    K[1, 1] *= sy
    K[1, 2] *= sy

    point = np.asarray(
        [[[
            float(x_px),
            float(y_px),
        ]]],
        dtype=np.float64,
    )

    undistorted = cv2.undistortPoints(
        point,
        K,
        distortion,
    )

    x_norm = float(
        undistorted[0, 0, 0]
    )

    y_norm = float(
        undistorted[0, 0, 1]
    )

    ray = np.asarray(
        [
            x_norm,
            y_norm,
            1.0,
        ],
        dtype=np.float64,
    )

    norm = float(
        np.linalg.norm(ray)
    )

    if (
        not math.isfinite(norm)
        or norm <= 1e-12
    ):
        raise RuntimeError(
            "Invalid calibrated camera ray"
        )

    ray /= norm

    if not np.all(
        np.isfinite(ray)
    ):
        raise RuntimeError(
            "Non-finite calibrated camera ray"
        )

    return ray

