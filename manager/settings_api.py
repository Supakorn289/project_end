from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)

from manager.security import (
    authenticate_manager_token,
    close_manager_session,
    open_manager_session,
    require_manager_session,
)

from manager.services.runtime_settings import (
    apply_runtime_settings,
    get_runtime_settings,
    restart_detection,
    save_runtime_settings,
)


settings_bp = Blueprint(
    "manager_settings",
    __name__,
)


@settings_bp.get(
    "/settings"
)
def settings_page():

    return render_template(
        "settings.html"
    )


@settings_bp.get(
    "/api/auth/session"
)
def auth_session():

    authenticated = bool(
        session.get(
            "manager_authenticated"
        )
    )

    return jsonify(
        {
            "ok": True,
            "authenticated":
                authenticated,

            "csrf": (
                session.get(
                    "manager_csrf"
                )
                if authenticated
                else None
            ),
        }
    )


@settings_bp.post(
    "/api/auth/login"
)
def auth_login():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    if not (
        authenticate_manager_token(
            payload.get(
                "token"
            )
        )
    ):

        return jsonify(
            {
                "ok": False,
                "error":
                    "invalid_token",
            }
        ), 401


    csrf = (
        open_manager_session()
    )


    return jsonify(
        {
            "ok": True,
            "csrf": csrf,
        }
    )


@settings_bp.post(
    "/api/auth/logout"
)
@require_manager_session
def auth_logout():

    close_manager_session()

    return jsonify(
        {
            "ok": True,
        }
    )


@settings_bp.get(
    "/api/settings/runtime"
)
def runtime_settings():

    result = (
        get_runtime_settings()
    )

    code = (
        200
        if result.get(
            "ok"
        )
        else 500
    )

    return jsonify(
        result
    ), code


@settings_bp.post(
    "/api/settings/runtime/save"
)
@require_manager_session
def runtime_settings_save():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    result = (
        save_runtime_settings(
            payload
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


@settings_bp.post(
    "/api/settings/runtime/apply"
)
@require_manager_session
def runtime_settings_apply():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    result = (
        apply_runtime_settings(
            payload
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


@settings_bp.post(
    "/api/control/detection/restart"
)
@require_manager_session
def detection_restart():

    result = (
        restart_detection()
    )

    return jsonify(
        result
    ), (
        200
        if result.get(
            "ok"
        )
        else 500
    )
