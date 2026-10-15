from __future__ import annotations

from flask import Blueprint, jsonify, request

from manager.security import require_manager_session
from manager.services.runtime_site_crud import (
    activate_site_revision,
    create_site_record,
    create_working_copy,
    get_working_copy_detail,
    delete_revision,
    delete_site,
    list_restorable_trash, trash_restore_preview, restore_from_trash,
    discard_working_copy,
    inventory,
    preview_site_update,
    publish_working_copy,
    revision_delete_preview,
    revision_detail,
    preview_resume_published,
    resume_published_candidate,
    site_delete_preview,
    test_working_camera,
    update_site_record,
    update_working_camera,
    offline_calibration_review,
    save_offline_calibration_review,
)

runtime_site_bp = Blueprint("runtime_site_manager", __name__)


def _json():
    return request.get_json(silent=True) or {}


def _error(exc, status=400):
    return jsonify({
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
    }), status


@runtime_site_bp.get("/api/runtime-sites")
@require_manager_session
def runtime_sites_list():
    try:
        return jsonify(inventory())
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.post("/api/runtime-sites")
@require_manager_session
def runtime_sites_create():
    try:
        return jsonify(create_site_record(_json()))
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.post("/api/runtime-sites/<site_id>/update-preview")
@require_manager_session
def runtime_site_update_preview(site_id):
    try:
        return jsonify(preview_site_update(site_id, _json()))
    except KeyError as exc:
        return _error(exc, 404)
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.patch("/api/runtime-sites/<site_id>")
@require_manager_session
def runtime_site_update(site_id):
    try:
        return jsonify(update_site_record(site_id, _json()))
    except KeyError as exc:
        return _error(exc, 404)
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.get("/api/runtime-sites/<site_id>/revision/<revision_id>")
@require_manager_session
def runtime_revision_detail(site_id, revision_id):
    try:
        result = revision_detail(site_id, revision_id)
        result["published_resume"] = preview_resume_published(site_id, revision_id)
        return jsonify(result)
    except FileNotFoundError as exc:
        return _error(exc, 404)
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.post("/api/runtime-sites/<site_id>/revision/<revision_id>/activate")
@require_manager_session
def runtime_revision_activate(site_id, revision_id):
    data = _json()

    if (
        data.get("confirm_site_id") != site_id
        or data.get("confirm_revision_id") != revision_id
    ):
        return jsonify({
            "ok": False,
            "error": "confirmation_mismatch",
        }), 400

    try:
        result = activate_site_revision(site_id, revision_id)
        return jsonify(result), 200 if result.get("ok") else 409
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.post("/api/runtime-sites/<site_id>/revision/<revision_id>/working-copy")
@require_manager_session
def runtime_revision_working_copy(site_id, revision_id):
    data = _json()
    try:
        if data.get("resume_published") is True:
            return jsonify(resume_published_candidate(site_id, revision_id, data))
        return jsonify(
            create_working_copy(
                site_id,
                revision_id,
                overwrite=bool(data.get("overwrite", False)),
                offline_only=data.get("offline_only") is True,
                expected_updated_at=data.get("expected_updated_at"),
            )
        )
    except Exception as exc:
        return _error(
            exc,
            409 if "working_copy_exists" in str(exc) else 400,
        )


@runtime_site_bp.get("/api/runtime-sites/<site_id>/working-copy")
@require_manager_session
def runtime_working_copy_detail(site_id):
    try:
        return jsonify(get_working_copy_detail(site_id))
    except Exception as exc:
        return _error(exc, 409)


@runtime_site_bp.patch("/api/runtime-sites/<site_id>/working-copy/camera")
@require_manager_session
def runtime_working_camera_update(site_id):
    try:
        return jsonify(update_working_camera(site_id, _json()))
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.get("/api/runtime-sites/<site_id>/working-copy/calibration-review")
@require_manager_session
def runtime_offline_calibration_review(site_id):
    try:
        return jsonify(offline_calibration_review(site_id))
    except Exception as exc:
        return _error(exc, 409)


@runtime_site_bp.patch("/api/runtime-sites/<site_id>/working-copy/calibration-review")
@require_manager_session
def runtime_offline_calibration_review_save(site_id):
    try:
        return jsonify(save_offline_calibration_review(site_id, _json()))
    except Exception as exc:
        return _error(exc, 409)


@runtime_site_bp.post("/api/runtime-sites/<site_id>/working-copy/camera/test")
@require_manager_session
def runtime_working_camera_test(site_id):
    try:
        result = test_working_camera(site_id)
        return jsonify(result), 200 if result.get("ok") else 400
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.post("/api/runtime-sites/<site_id>/working-copy/publish")
@require_manager_session
def runtime_working_publish(site_id):
    try:
        result = publish_working_copy(site_id)
        return jsonify(result), 200 if result.get("candidate_ready") else 409
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.delete("/api/runtime-sites/<site_id>/working-copy")
@require_manager_session
def runtime_working_discard(site_id):
    try:
        data = _json()
        return jsonify(discard_working_copy(
            site_id,
            expected_updated_at=data.get("expected_updated_at"),
            confirm_site_id=data.get("confirm_site_id"),
        ))
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.get("/api/runtime-sites/<site_id>/revision/<revision_id>/delete-preview")
@require_manager_session
def runtime_revision_delete_preview(site_id, revision_id):
    try:
        return jsonify(revision_delete_preview(site_id, revision_id))
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.delete("/api/runtime-sites/<site_id>/revision/<revision_id>")
@require_manager_session
def runtime_revision_delete(site_id, revision_id):
    try:
        return jsonify(
            delete_revision(
                site_id,
                revision_id,
                _json().get("confirm_value", ""),
            )
        )
    except Exception as exc:
        return _error(exc, 409 if "active" in str(exc) else 400)


@runtime_site_bp.get("/api/runtime-sites/<site_id>/delete-preview")
@require_manager_session
def runtime_site_delete_preview(site_id):
    try:
        return jsonify(site_delete_preview(site_id))
    except Exception as exc:
        return _error(exc)


@runtime_site_bp.delete("/api/runtime-sites/<site_id>")
@require_manager_session
def runtime_site_delete(site_id):
    try:
        return jsonify(
            delete_site(
                site_id,
                _json().get("confirm_value", ""),
            )
        )
    except Exception as exc:
        return _error(exc, 409 if "active" in str(exc) else 400)


# Stage 3E.1 — safe Trash restore under the existing authorized Manager session.
@runtime_site_bp.get("/api/runtime-sites/trash")
@require_manager_session
def runtime_trash_inventory():
    try:
        return jsonify(list_restorable_trash())
    except Exception as exc:
        return _error(exc, 409)


@runtime_site_bp.get("/api/runtime-sites/trash/<kind>/<site_id>/<archive_id>/restore-preview")
@require_manager_session
def runtime_trash_restore_preview(kind, site_id, archive_id):
    try:
        return jsonify(trash_restore_preview(kind, site_id, archive_id))
    except Exception as exc:
        return _error(exc, 409)


@runtime_site_bp.post("/api/runtime-sites/trash/<kind>/<site_id>/<archive_id>/restore")
@require_manager_session
def runtime_trash_restore(kind, site_id, archive_id):
    data = _json()
    try:
        return jsonify(restore_from_trash(kind, site_id, archive_id,
                       data.get("confirm_value", ""), data.get("expected_proof", "")))
    except Exception as exc:
        return _error(exc, 409)
