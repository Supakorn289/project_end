"""Authenticated Active Site editor endpoints."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.phase45_editor import snapshot, edit_marks

phase45_editor_bp = Blueprint("phase45_active_editor", __name__)

@phase45_editor_bp.get("/api/phase45/active/editor")
@require_manager_session
def current_editor():
    try:
        return jsonify(snapshot())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409

@phase45_editor_bp.post("/api/phase45/active/marks")
@require_manager_session
def edit_mark():
    try:
        return jsonify(edit_marks(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "runtime_changed": False}), 409

@phase45_editor_bp.post("/api/phase45/fusion/replay-three")
@require_manager_session
def fusion_replay_three():
    try:
        from manager.services.phase45_fusion_replay import replay
        return jsonify(replay(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc),"runtime_changed":False}),400
