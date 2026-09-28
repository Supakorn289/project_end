from __future__ import annotations


from flask import (
    Blueprint,
    jsonify,
)


from manager.security import (
    require_manager_session,
)

from manager.services.final_verification import (
    verify_site_candidate,
)


final_verification_bp = Blueprint(
    "manager_final_verification",
    __name__,
)


@final_verification_bp.get(
    "/api/final-verification/"
    "<site_id>"
)
@require_manager_session
def final_verification(
    site_id,
):

    try:

        return jsonify(
            verify_site_candidate(
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
