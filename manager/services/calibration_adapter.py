from __future__ import annotations

import math

from calibration import (
    DistanceModel,
    fit_distance_model,
)

from config import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    HFOV_DEG,
)

from geometry import (
    normalize_bearing,
)


# ============================================================
# Distance
# ============================================================

def build_distance_candidate(
    points,
    *,
    preset=None,
):
    """
    ใช้ Distance Engine เดิมของโครงการ:
        calibration.fit_distance_model()

    Candidate นี้ยังไม่ถูก activate.
    """

    if not isinstance(
        points,
        list,
    ):
        raise ValueError(
            "points must be list"
        )


    samples = []


    for index, point in enumerate(
        points,
        start=1,
    ):

        try:

            distance_m = float(
                point[
                    "distance_m"
                ]
            )

            y_px = float(
                point[
                    "y_px"
                ]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:

            raise ValueError(
                f"invalid point #{index}"
            ) from exc


        if (
            not math.isfinite(
                distance_m
            )
            or
            distance_m <= 0
        ):

            raise ValueError(
                f"distance #{index} invalid"
            )


        if (
            not math.isfinite(
                y_px
            )
            or
            y_px < 0
            or
            y_px >= FRAME_HEIGHT
        ):

            raise ValueError(
                f"Y #{index} invalid"
            )


        samples.append(
            (
                distance_m,
                y_px,
            )
        )


    # --------------------------------------------------------
    # ORIGINAL ENGINE
    # --------------------------------------------------------

    model = fit_distance_model(
        samples,
        preset=preset,
    )


    # Schema เดียวกับ save_distance_model() เดิม
    candidate = {
        "version": 3,

        "H":
            float(
                model.H
            ),

        "K":
            float(
                model.K
            ),

        "pixel_rmse":
            float(
                model.pixel_rmse
            ),

        "frame_width":
            int(
                model.frame_width
            ),

        "frame_height":
            int(
                model.frame_height
            ),

        "hfov_deg":
            float(
                HFOV_DEG
            ),

        "points":
            int(
                model.points
            ),

        "preset":
            model.preset,

        "min_distance_m":
            (
                None
                if model.min_distance_m
                is None
                else float(
                    model.min_distance_m
                )
            ),

        "max_distance_m":
            (
                None
                if model.max_distance_m
                is None
                else float(
                    model.max_distance_m
                )
            ),
    }


    return candidate


def distance_model_from_candidate(
    candidate,
):

    return DistanceModel(
        H=float(
            candidate[
                "H"
            ]
        ),

        K=float(
            candidate[
                "K"
            ]
        ),

        pixel_rmse=float(
            candidate[
                "pixel_rmse"
            ]
        ),

        frame_width=int(
            candidate[
                "frame_width"
            ]
        ),

        frame_height=int(
            candidate[
                "frame_height"
            ]
        ),

        points=int(
            candidate[
                "points"
            ]
        ),

        preset=(
            None
            if candidate.get(
                "preset"
            )
            is None
            else int(
                candidate[
                    "preset"
                ]
            )
        ),

        min_distance_m=(
            None
            if candidate.get(
                "min_distance_m"
            )
            is None
            else float(
                candidate[
                    "min_distance_m"
                ]
            )
        ),

        max_distance_m=(
            None
            if candidate.get(
                "max_distance_m"
            )
            is None
            else float(
                candidate[
                    "max_distance_m"
                ]
            )
        ),
    )


def verify_distance_candidate(
    candidate,
    *,
    y_px,
    actual_distance_m,
):
    """
    ใช้ DistanceModel.estimate() เดิม
    ไม่เขียน runtime.
    """

    y_px = float(
        y_px
    )

    actual = float(
        actual_distance_m
    )


    if (
        not math.isfinite(
            actual
        )
        or
        actual <= 0
    ):

        raise ValueError(
            "actual distance invalid"
        )


    model = (
        distance_model_from_candidate(
            candidate
        )
    )


    # --------------------------------------------------------
    # ORIGINAL ENGINE
    # --------------------------------------------------------

    predicted = (
        model.estimate(
            y_px
        )
    )


    if predicted is None:

        raise ValueError(
            "Y cannot be estimated "
            "by this calibration"
        )


    signed_error = (
        predicted
        -
        actual
    )

    absolute_error = abs(
        signed_error
    )

    percent_error = (
        absolute_error
        /
        actual
        *
        100.0
    )


    # เกณฑ์เดิมของ workflow verification
    if percent_error <= 5.0:

        grade = "EXCELLENT"

    elif percent_error <= 10.0:

        grade = "GOOD"

    elif percent_error <= 15.0:

        grade = "FAIR"

    else:

        grade = "RECALIBRATE"


    return {
        "y_px":
            y_px,

        "actual_distance_m":
            actual,

        "predicted_distance_m":
            float(
                predicted
            ),

        "signed_error_m":
            float(
                signed_error
            ),

        "absolute_error_m":
            float(
                absolute_error
            ),

        "percent_error":
            float(
                percent_error
            ),

        "grade":
            grade,

        "within_calibrated_range":
            bool(
                model.is_within_calibrated_range(
                    predicted
                )
            ),
    }


# ============================================================
# Bearing / True North
# ============================================================

def build_bearing_candidate(
    measured_preset1_bearing_deg,
):
    """
    Logic เดียวกับ calibrate_bearing.py เดิม.

    ไม่เรียก save_site_calibration()
    เพราะ Manager ต้องสร้าง Candidate ก่อน.
    """

    measured = float(
        measured_preset1_bearing_deg
    )


    if not math.isfinite(
        measured
    ):

        raise ValueError(
            "bearing must be finite"
        )


    # --------------------------------------------------------
    # ORIGINAL GEOMETRY ENGINE
    # --------------------------------------------------------

    measured = normalize_bearing(
        measured
    )


    offset = normalize_bearing(
        measured
    )


    if offset > 180.0:

        offset -= 360.0


    # Schema เดียวกับ save_site_calibration()
    return {
        "version": 1,

        "north_offset_deg":
            float(
                offset
            ),

        "measured_preset1_bearing_deg":
            float(
                measured
            ),

        "frame_width":
            int(
                FRAME_WIDTH
            ),

        "frame_height":
            int(
                FRAME_HEIGHT
            ),

        "hfov_deg":
            float(
                HFOV_DEG
            ),
    }


# ============================================================
# Engine metadata
# ============================================================

def engine_info():

    return {
        "distance": {
            "fit":
                "calibration.fit_distance_model",

            "estimate":
                "calibration.DistanceModel.estimate",

            "runtime_format":
                "distance_global.json v3",
        },

        "bearing": {
            "normalize":
                "geometry.normalize_bearing",

            "runtime_format":
                "site.json v1",

            "active_writer":
                "calibration.save_site_calibration",
        },

        "policy": {
            "candidate_only":
                True,

            "writes_active_runtime":
                False,
        },
    }
