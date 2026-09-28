from __future__ import annotations

import json
import math

from flask import (
    Blueprint,
    jsonify,
    request,
)

from manager.security import (
    require_manager_session,
)

from manager.services.calibration_adapter import (
    build_bearing_candidate,
    build_distance_candidate,
    engine_info,
    verify_distance_candidate,
)

from manager.services.wizard_store import (
    candidate_path,
    load_state,
    save_candidate,
    save_state,
)


calibration_adapter_bp = Blueprint(
    "manager_calibration_adapter",
    __name__,
)


def request_json():

    return (
        request.get_json(
            silent=True
        )
        or {}
    )


@calibration_adapter_bp.get(
    "/api/calibration-adapter/engines"
)
def adapter_engines():

    return jsonify({
        "ok": True,
        "engines":
            engine_info(),
    })


# ============================================================
# Distance candidate
# ============================================================

@calibration_adapter_bp.post(
    "/api/calibration-adapter/"
    "<site_id>/distance/fit"
)
@require_manager_session
def adapter_distance_fit(
    site_id,
):

    data = request_json()


    try:

        candidate = (
            build_distance_candidate(
                data.get(
                    "points",
                    []
                ),

                preset=data.get(
                    "preset"
                ),
            )
        )


        path = save_candidate(
            site_id,
            "distance_global.json",
            candidate,
        )


        return jsonify({
            "ok": True,

            "engine":
                "calibration.fit_distance_model",

            "candidate":
                candidate,

            "candidate_file":
                str(
                    path
                ),

            "runtime_changed":
                False,
        })


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }), 400


@calibration_adapter_bp.post(
    "/api/calibration-adapter/"
    "<site_id>/distance/verify"
)
@require_manager_session
def adapter_distance_verify(
    site_id,
):

    data = request_json()


    try:

        path = candidate_path(
            site_id,
            "distance_global.json",
        )


        if not path.exists():

            raise ValueError(
                "distance candidate "
                "does not exist"
            )


        candidate = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )


        verification = (
            verify_distance_candidate(
                candidate,

                y_px=data[
                    "y_px"
                ],

                actual_distance_m=data[
                    "actual_distance_m"
                ],
            )
        )


        return jsonify({
            "ok": True,

            "engine":
                "calibration."
                "DistanceModel.estimate",

            "verification":
                verification,

            "runtime_changed":
                False,
        })


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }), 400


# ============================================================
# Bearing candidate
# ============================================================

@calibration_adapter_bp.post(
    "/api/calibration-adapter/"
    "<site_id>/bearing/build"
)
@require_manager_session
def adapter_bearing_build(
    site_id,
):

    data = request_json()


    try:

        candidate = (
            build_bearing_candidate(
                data[
                    "measured_preset1_bearing_deg"
                ],

                site_id=
                    site_id,
            )
        )


        path = save_candidate(
            site_id,
            "site.json",
            candidate,
        )


        state = load_state(
            site_id
        )


        state[
            "north"
        ][
            "candidate"
        ] = candidate


        state[
            "step"
        ] = "GPS"


        save_state(
            site_id,
            state,
        )


        return jsonify({
            "ok": True,

            "engine":
                "geometry.normalize_bearing",

            "candidate":
                candidate,

            "candidate_file":
                str(
                    path
                ),

            "runtime_changed":
                False,
        })


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }), 400


# ============================================================
# Candidate status
# ============================================================

@calibration_adapter_bp.get(
    "/api/calibration-adapter/"
    "<site_id>/status"
)
def adapter_status(
    site_id,
):

    result = {}


    for filename in (
        "distance_global.json",
        "site.json",
        "preset_rotation.json",
    ):

        path = candidate_path(
            site_id,
            filename,
        )


        if path.exists():

            try:

                data = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )


                result[
                    filename
                ] = {
                    "exists":
                        True,

                    "path":
                        str(
                            path
                        ),

                    "version":
                        data.get(
                            "version"
                        ),

                    "status":
                        data.get(
                            "status"
                        ),

                    "model":
                        data.get(
                            "model"
                        ),
                }


            except Exception as exc:

                result[
                    filename
                ] = {
                    "exists":
                        True,

                    "valid_json":
                        False,

                    "error":
                        str(
                            exc
                        ),
                }


        else:

            result[
                filename
            ] = {
                "exists":
                    False,
            }


    return jsonify({
        "ok": True,

        "site_id":
            site_id,

        "candidate_only":
            True,

        "runtime_changed":
            False,

        "candidates":
            result,
    })


# ============================================================
# GPS / Site Location Candidate
# ============================================================

@calibration_adapter_bp.post(
    "/api/calibration-adapter/"
    "<site_id>/location/build"
)
@require_manager_session
def adapter_location_build(
    site_id,
):

    data = request_json()


    try:

        latitude = float(
            data[
                "camera_lat"
            ]
        )

        longitude = float(
            data[
                "camera_lon"
            ]
        )


        if (
            not math.isfinite(
                latitude
            )
            or
            not (
                -90.0
                <= latitude
                <= 90.0
            )
        ):

            raise ValueError(
                "Latitude ต้องอยู่ระหว่าง "
                "-90 ถึง 90"
            )


        if (
            not math.isfinite(
                longitude
            )
            or
            not (
                -180.0
                <= longitude
                <= 180.0
            )
        ):

            raise ValueError(
                "Longitude ต้องอยู่ระหว่าง "
                "-180 ถึง 180"
            )


        candidate = {
            "version":
                1,

            "camera_lat":
                latitude,

            "camera_lon":
                longitude,

            "status":
                "CANDIDATE",

            "runtime_env": {
                "CAMERA_LAT":
                    str(
                        latitude
                    ),

                "CAMERA_LON":
                    str(
                        longitude
                    ),
            },

            "runtime_changed":
                False,
        }


        candidate_file = (
            save_candidate(
                site_id,
                "location.json",
                candidate,
            )
        )


        state = load_state(
            site_id
        )


        state[
            "gps"
        ] = {
            "candidate":
                candidate,
        }


        state[
            "step"
        ] = "FINAL_VERIFY"


        save_state(
            site_id,
            state,
        )


        return jsonify({
            "ok": True,

            "candidate":
                candidate,

            "candidate_file":
                str(
                    candidate_file
                ),

            "runtime_changed":
                False,
        })


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),

            "runtime_changed":
                False,
        }), 400

