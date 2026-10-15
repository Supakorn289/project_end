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


        request_data = request.get_json(silent=True) or {}
        historical = request_data.get('source') == 'historical_draft_lab_only'
        if historical:
            # This pathway is never the default; three explicit acknowledgments
            # and the exact active/site identity are mandatory.
            from manager.services.phase45_editor import _LEGACY_REV
            if (request_data.get('confirm_site_id') != site_id
                or request_data.get('confirm_revision_id') != _LEGACY_REV
                or request_data.get('acknowledge_source_sessions') is not True
                or request_data.get('acknowledge_lab_only') is not True
                or request_data.get('acknowledge_field_verification') is not True):
                raise PermissionError('HISTORICAL_SOLVER_CONFIRMATION_REQUIRED')
            from manager.services.geometry_mark_adapter import historical_draft_solver_inputs
            prepared = historical_draft_solver_inputs(site_id)
            # Invalidate any prior manifest BEFORE new inputs are written. An
            # interrupted prepare cannot leave a stale manifest runnable.
            save_candidate(site_id,'geometry_inputs/manifest.json',
                           {'version':2,'source':'INCOMPLETE_PREPARE_BLOCK_SOLVE'})
        else:
            if request_data.get('source') not in (None,'current_wizard'):
                raise ValueError('UNSUPPORTED_GEOMETRY_SOURCE')
            prepared = build_final_solver_inputs(state)


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
                2 if historical else 1,
            "source": "historical_draft_lab_only" if historical else "current_wizard",
            "historical_dataset_digest": prepared.get('dataset_digest') if historical else None,
            "historical_fingerprints": prepared.get('fingerprints') if historical else None,
            "production_certified": False if historical else None,
            "field_accuracy_proven": False if historical else None,

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


        if historical:
            state['phase45_geometry_dirty']=True
            state['geometry'].pop('solver_result',None)
            state['geometry']['historical_draft_solver_source']={
                'dataset_digest':prepared['dataset_digest'],
                'parent_revision':prepared['parent_revision'],
                'lab_only':True,'field_verification_required':True}
        else:
            state['geometry'].pop('historical_draft_solver_source',None)
        state[
            "geometry"
        ][
            "solver_inputs"
        ] = {
            "prepared":
                True,
            "source": "historical_draft_lab_only" if historical else "current_wizard",
            "lab_only": bool(historical),
            "requires_field_verification":bool(historical),

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
