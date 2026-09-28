from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    request,
)


from manager.security import (
    require_manager_session,
)

from manager.services.telegram_setup import (
    save_telegram_candidate,
    telegram_status,
    test_telegram_candidate,
)


telegram_setup_bp = Blueprint(
    "manager_telegram_setup",
    __name__,
)


@telegram_setup_bp.get(
    "/api/telegram-setup/"
    "<site_id>/status"
)
def telegram_setup_status(
    site_id,
):

    return jsonify({
        "ok":
            True,

        "status":
            telegram_status(
                site_id
            ),
    })


@telegram_setup_bp.post(
    "/api/telegram-setup/"
    "<site_id>/save"
)
@require_manager_session
def telegram_setup_save(
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
            save_telegram_candidate(
                site_id,

                token=
                    data.get(
                        "telegram_token"
                    ),

                chat_id=
                    data.get(
                        "telegram_chat_id"
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
                f"{type(exc).__name__}: {exc}",
        }), 400


@telegram_setup_bp.post(
    "/api/telegram-setup/"
    "<site_id>/test"
)
@require_manager_session
def telegram_setup_test(
    site_id,
):

    try:

        result = (
            test_telegram_candidate(
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
                f"{type(exc).__name__}: {exc}",

            "runtime_changed":
                False,
        }), 400
