from __future__ import annotations


from flask import (
    Blueprint,
    jsonify,
)


from manager.security import (
    require_manager_session,
)

from manager.services.revision_engine import (
    create_revision,
    list_revisions,
)


revision_bp = Blueprint(
    "manager_revision",
    __name__,
)


@revision_bp.get(
    "/api/revisions/<site_id>"
)
@require_manager_session
def revisions_list(
    site_id,
):

    try:

        return jsonify({
            "ok":
                True,

            "revisions":
                list_revisions(
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


@revision_bp.post(
    "/api/revisions/<site_id>"
)
@require_manager_session
def revisions_create(
    site_id,
):

    try:

        return jsonify(
            create_revision(
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
