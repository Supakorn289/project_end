"""Authenticated Active Site editor endpoints."""
from flask import Blueprint, jsonify, request, send_file
from manager.security import require_manager_session
from manager.services.phase45_editor import snapshot, edit_marks, legacy_draft_preview, legacy_draft_edit, legacy_source_frame

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


@phase45_editor_bp.get('/api/phase45/active/legacy-evidence/<phase>/<pair>')
@require_manager_session
def legacy_evidence_view(phase,pair):
    try:
        response=jsonify(legacy_draft_preview(phase,pair))
        response.headers['Cache-Control']='no-store'
        return response
    except Exception:
        # Do not leak private filesystem paths in unauthorized/error responses.
        return jsonify({'ok':False,'error':'LEGACY_EVIDENCE_UNAVAILABLE_OR_CHANGED'}),409


@phase45_editor_bp.get('/api/phase45/active/legacy-frame/<phase>/<pair>/<side>')
@require_manager_session
def legacy_evidence_image(phase,pair,side):
    try:
        path=legacy_source_frame(phase,pair,side)
        response=send_file(path,mimetype='image/jpeg',conditional=True,max_age=0)
        response.headers['Cache-Control']='no-store, private'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    except Exception:
        return jsonify({'ok':False,'error':'LEGACY_FRAME_UNAVAILABLE_OR_CHANGED'}),409


@phase45_editor_bp.post('/api/phase45/active/legacy-evidence/<phase>/<pair>')
@require_manager_session
def legacy_evidence_draft_mutation(phase,pair):
    try:
        response=jsonify(legacy_draft_edit(phase,pair,request.get_json(silent=True) or {}))
        response.headers['Cache-Control']='no-store'
        return response
    except Exception as exc:
        # Expose a bounded error code, not server filesystem locations/secrets.
        code=str(exc).split(':')[0]
        allowed={'LEGACY_DRAFT_SITE_REVISION_MISMATCH','LEGACY_DRAFT_WORKING_PARENT_MISMATCH',
            'LEGACY_DRAFT_STALE_REFRESH_REQUIRED','LEGACY_DRAFT_UNSAFE_DIRECTORY',
            'LEGACY_DRAFT_LINEAGE_MISMATCH','LEGACY_MARK_OUTSIDE_SOURCE_FRAME',
            'LEGACY_MARK_SCHEMA_INVALID','LEGACY_CLEAR_EXPLICIT_CONFIRM_REQUIRED',
            'LEGACY_RESET_EXPLICIT_CONFIRM_REQUIRED','LEGACY_SOURCE_SHA_MISMATCH',
            'LEGACY_STAGED_EVIDENCE_SHA_MISMATCH','LEGACY_ACTIVE_REVISION_INTEGRITY_FAILED'}
        return jsonify({'ok':False,'error':code if code in allowed else 'LEGACY_DRAFT_EDIT_REJECTED','runtime_changed':False}),409
