from __future__ import annotations


from flask import (
    Blueprint,
    jsonify,
)


from manager.security import (
    require_manager_session,
)

from manager.services.activation_plan import (
    build_activation_plan,
)


from manager.services.ops_agent import (
    activate_revision,
)


from manager.services.site_registry import (
    reconcile_active_runtime,
)


activation_bp = Blueprint(
    "manager_activation",
    __name__,
)


@activation_bp.get(
    "/api/activation/"
    "<site_id>/<revision_id>/plan"
)
@require_manager_session
def activation_plan(
    site_id,
    revision_id,
):

    try:

        result = (
            build_activation_plan(
                site_id,
                revision_id,
            )
        )


        return jsonify(
            result
        ), (
            200
            if result.get(
                "ok"
            )
            else 409
        )


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "activatable":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

            "runtime_changed":
                False,
        }), 400



@activation_bp.post(
    "/api/activation/"
    "<site_id>/<revision_id>/activate"
)
@require_manager_session
def activation_execute(
    site_id,
    revision_id,
):

    try:

        # Manager-side validation first.
        plan = build_activation_plan(
            site_id,
            revision_id,
        )


        if not plan.get(
            "activatable"
        ):

            return jsonify(
                plan
            ), 409


        # Root agent independently validates
        # the immutable revision again.
        result = activate_revision(
            site_id,
            revision_id,
        )


        if result.get(
            "ok"
        ):
            try:
                reconcile_active_runtime()
                result[
                    "registry_reconciled"
                ] = True

            except Exception as exc:
                result[
                    "registry_reconciled"
                ] = False
                result[
                    "registry_warning"
                ] = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )


        return jsonify(
            result
        ), (
            200
            if result.get(
                "ok"
            )
            else 409
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
        }), 400
