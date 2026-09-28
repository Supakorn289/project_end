from __future__ import annotations

import re


from flask import (
    Blueprint,
    jsonify,
    send_file,
)


from manager.security import (
    require_manager_session,
)

from manager.services.calibration_worker_client import (
    intrinsics_capture,
    intrinsics_probe,
)

from manager.services.camera_setup import (
    camera_source_for_site,
)

from manager.services.intrinsics_setup import (
    capture_dir,
    fit_intrinsics_candidate,
    intrinsics_status,
    reset_intrinsics_captures,
    reuse_active_intrinsics,
)


intrinsics_setup_bp = Blueprint(
    "manager_intrinsics_setup",
    __name__,
)


IMAGE_NAME_RE = re.compile(
    r"^(?:preview_latest|calib_[0-9]{3})\.jpg$"
)


@intrinsics_setup_bp.get(
    "/api/intrinsics-setup/"
    "<site_id>/status"
)
def intrinsics_setup_status(
    site_id,
):

    try:

        return jsonify({
            "ok":
                True,

            "status":
                intrinsics_status(
                    site_id
                ),
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


@intrinsics_setup_bp.post(
    "/api/intrinsics-setup/"
    "<site_id>/reuse-active"
)
@require_manager_session
def intrinsics_setup_reuse(
    site_id,
):

    try:

        return jsonify(
            reuse_active_intrinsics(
                site_id
            )
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


@intrinsics_setup_bp.post(
    "/api/intrinsics-setup/"
    "<site_id>/probe"
)
@require_manager_session
def intrinsics_setup_probe(
    site_id,
):

    try:

        source = (
            camera_source_for_site(
                site_id
            )
        )


        result = intrinsics_probe(
            site_id,
            source,
        )


        if result.get(
            "ok"
        ):

            result[
                "preview_url"
            ] = (
                "/api/intrinsics-setup/"
                f"{site_id}/image/"
                "preview_latest.jpg"
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


@intrinsics_setup_bp.post(
    "/api/intrinsics-setup/"
    "<site_id>/capture"
)
@require_manager_session
def intrinsics_setup_capture(
    site_id,
):

    try:

        source = (
            camera_source_for_site(
                site_id
            )
        )


        result = intrinsics_capture(
            site_id,
            source,
        )


        if result.get(
            "ok"
        ):

            result[
                "preview_url"
            ] = (
                "/api/intrinsics-setup/"
                f"{site_id}/image/"
                "preview_latest.jpg"
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


@intrinsics_setup_bp.post(
    "/api/intrinsics-setup/"
    "<site_id>/reset"
)
@require_manager_session
def intrinsics_setup_reset(
    site_id,
):

    try:

        return jsonify(
            reset_intrinsics_captures(
                site_id
            )
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


@intrinsics_setup_bp.post(
    "/api/intrinsics-setup/"
    "<site_id>/fit"
)
@require_manager_session
def intrinsics_setup_fit(
    site_id,
):

    try:

        result = (
            fit_intrinsics_candidate(
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


@intrinsics_setup_bp.get(
    "/api/intrinsics-setup/"
    "<site_id>/image/<filename>"
)
@require_manager_session
def intrinsics_setup_image(
    site_id,
    filename,
):

    if not IMAGE_NAME_RE.fullmatch(
        filename
    ):

        return jsonify({
            "ok":
                False,

            "error":
                "invalid_image_name",
        }), 400


    path = (
        capture_dir(
            site_id
        )
        / filename
    )


    if not path.exists():

        return jsonify({
            "ok":
                False,

            "error":
                "image_not_found",
        }), 404


    response = send_file(
        path,
        mimetype="image/jpeg",
        conditional=True,
    )


    response.headers[
        "Cache-Control"
    ] = (
        "private, no-store, "
        "max-age=0"
    )


    return response
