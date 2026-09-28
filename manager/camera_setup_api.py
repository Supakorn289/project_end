from __future__ import annotations


from flask import (
    Blueprint,
    jsonify,
    request,
)


from manager.security import (
    require_manager_session,
)

from manager.services.hardware_lock import (
    hardware_lock,
)


from manager.services.camera_setup import (
    camera_status,
    save_camera_candidate,
    test_camera_candidate,
)


camera_setup_bp = Blueprint(
    "manager_camera_setup",
    __name__,
)


@camera_setup_bp.get(
    "/api/camera-setup/"
    "<site_id>/status"
)
def camera_setup_status(
    site_id,
):

    return jsonify({
        "ok":
            True,

        "status":
            camera_status(
                site_id
            ),
    })


@camera_setup_bp.post(
    "/api/camera-setup/"
    "<site_id>/save"
)
@require_manager_session
def camera_setup_save(
    site_id,
):

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )


    try:

        result = (
            save_camera_candidate(
                site_id,

                camera_ip=
                    data.get(
                        "camera_ip"
                    ),

                camera_port=
                    data.get(
                        "camera_port"
                    ),

                camera_user=
                    data.get(
                        "camera_user"
                    ),

                camera_password=
                    data.get(
                        "camera_password"
                    ),

                rtsp_port=
                    data.get(
                        "rtsp_port"
                    ),

                rtsp_path=
                    data.get(
                        "rtsp_path"
                    ),
            )
        )


        return jsonify({
            "ok":
                True,

            "status":
                result,
        })


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
        }), 400


@camera_setup_bp.post(
    "/api/camera-setup/"
    "<site_id>/test"
)
@require_manager_session
def camera_setup_test(
    site_id,
):

    try:

        with hardware_lock(
            "manager:camera_test",
            timeout=1.0,
        ):

            result = (
                test_camera_candidate(
                    site_id
                )
            )


        return jsonify(
            result
        ), (
            200
            if result.get(
                "ok"
            )
            else 400
        )


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

            "runtime_changed":
                False,
        }), 400
