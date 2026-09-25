from __future__ import annotations

import json

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
    save_candidate,
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
                ]
            )
        )


        path = save_candidate(
            site_id,
            "site.json",
            candidate,
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
