from __future__ import annotations

import hmac
from functools import wraps
from pathlib import Path

from flask import jsonify, request


TOKEN_FILE = Path(
    "/etc/smart-fire-detection/manager.token"
)


def _load_token() -> str | None:
    try:
        token = TOKEN_FILE.read_text(
            encoding="utf-8"
        ).strip()

        return token or None

    except OSError:
        return None


def require_manager_token(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        expected = _load_token()

        if not expected:
            return jsonify({
                "ok": False,
                "error": "manager token unavailable",
            }), 503

        supplied = request.headers.get(
            "X-Manager-Token",
            ""
        )

        if not hmac.compare_digest(
            supplied,
            expected
        ):
            return jsonify({
                "ok": False,
                "error": "unauthorized",
            }), 401

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# Browser session security
# ============================================================

def configure_session_security(
    app,
):
    import hashlib

    token = (
        _load_token()
        or "manager-session-unavailable"
    )

    app.secret_key = (
        hashlib.sha256(
            (
                "smart-fire-manager-session:"
                + token
            ).encode(
                "utf-8"
            )
        ).digest()
    )

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
    )


def authenticate_manager_token(
    supplied,
) -> bool:

    import hmac

    expected = (
        _load_token()
    )

    if (
        not expected
        or not supplied
    ):
        return False

    return hmac.compare_digest(
        str(
            supplied
        ),
        expected,
    )


def open_manager_session():

    import secrets

    from flask import session

    csrf = (
        secrets.token_urlsafe(
            32
        )
    )

    session[
        "manager_authenticated"
    ] = True

    session[
        "manager_csrf"
    ] = csrf

    return csrf


def close_manager_session():

    from flask import session

    session.clear()


def require_manager_session(
    func,
):

    from functools import wraps

    from flask import (
        jsonify,
        request,
        session,
    )

    @wraps(func)
    def wrapper(
        *args,
        **kwargs,
    ):

        if not session.get(
            "manager_authenticated"
        ):

            return jsonify(
                {
                    "ok": False,
                    "error":
                        "authentication_required",
                }
            ), 401


        if request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:

            expected = session.get(
                "manager_csrf"
            )

            supplied = request.headers.get(
                "X-CSRF-Token"
            )

            if (
                not expected
                or not supplied
                or not hmac.compare_digest(
                    expected,
                    supplied,
                )
            ):

                return jsonify(
                    {
                        "ok": False,
                        "error":
                            "csrf_failed",
                    }
                ), 403


        return func(
            *args,
            **kwargs,
        )


    return wrapper
