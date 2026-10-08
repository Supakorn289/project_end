from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    request,
)

from manager.security import (
    require_manager_session,
)

from manager.services.geometry_mark_adapter import (
    build_final_solver_inputs,
    geometry_readiness,
)

from manager.services.wizard_store import (
    load_state,
    save_candidate,
    save_state,
)


geometry_adapter_bp = Blueprint(
    "manager_geometry_adapter",
    __name__,
)


@geometry_adapter_bp.get(
    "/api/geometry-adapter/"
    "<site_id>/status"
)
def geometry_adapter_status(
    site_id,
):

    try:

        state = load_state(
            site_id
        )


        return jsonify({
            "ok": True,

            "site_id":
                site_id,

            "readiness":
                geometry_readiness(
                    state
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


@geometry_adapter_bp.post(
    "/api/geometry-adapter/"
    "<site_id>/prepare"
)
@require_manager_session
def geometry_adapter_prepare(
    site_id,
):

    try:

        state = load_state(
            site_id
        )


        prepared = (
            build_final_solver_inputs(
                state
            )
        )


        paths = {}


        files = {
            "positive_train":
                "geometry_inputs/"
                "positive_train.json",

            "negative_train":
                "geometry_inputs/"
                "negative_train.json",

            "positive_holdout":
                "geometry_inputs/"
                "positive_holdout.json",

            "negative_holdout":
                "geometry_inputs/"
                "negative_holdout.json",
        }


        for key, filename in (
            files.items()
        ):

            path = save_candidate(
                site_id,
                filename,
                prepared[
                    key
                ],
            )

            paths[
                key
            ] = str(
                path
            )


        manifest = {
            "version":
                1,

            "site_id":
                site_id,

            "solver":
                "solve_final_mixed_"
                "rotation_AB_v3.py",

            "inputs":
                paths,

            "readiness":
                prepared[
                    "readiness"
                ],

            "runtime_changed":
                False,
        }


        manifest_path = (
            save_candidate(
                site_id,
                "geometry_inputs/"
                "manifest.json",
                manifest,
            )
        )


        state[
            "geometry"
        ][
            "solver_inputs"
        ] = {
            "prepared":
                True,

            "manifest":
                str(
                    manifest_path
                ),
        }


        save_state(
            site_id,
            state,
        )


        return jsonify({
            "ok": True,

            "prepared":
                True,

            "manifest":
                str(
                    manifest_path
                ),

            "files":
                paths,

            "readiness":
                prepared[
                    "readiness"
                ],

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


@geometry_adapter_bp.post(
    "/api/geometry-adapter/"
    "<site_id>/solve"
)
@require_manager_session
def geometry_adapter_solve(
    site_id,
):

    from manager.services.geometry_solver_runner import (
        run_existing_geometry_solver,
    )


    try:

        result = (
            run_existing_geometry_solver(
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
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),

            "runtime_changed":
                False,
        }), 400

@geometry_adapter_bp.get(
    "/api/geometry-adapter/"
    "<site_id>/force-status"
)
@require_manager_session
def geometry_adapter_force_status(
    site_id,
):

    from manager.services.geometry_solver_runner import (
        failed_geometry_force_status,
    )


    try:

        return jsonify(
            failed_geometry_force_status(
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


@geometry_adapter_bp.post(
    "/api/geometry-adapter/"
    "<site_id>/force"
)
@require_manager_session
def geometry_adapter_force(
    site_id,
):

    from manager.services.geometry_solver_runner import (
        force_failed_geometry_candidate,
    )


    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        result = (
            force_failed_geometry_candidate(
                site_id,

                confirmation=
                    data.get(
                        "confirmation"
                    ),

                reason=
                    data.get(
                        "reason"
                    ),
            )
        )


        return jsonify(
            result
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
