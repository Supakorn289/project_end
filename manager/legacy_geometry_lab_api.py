"""Manager-session protected review of LAB-only legacy geometry evidence."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.legacy_geometry_lab import preview, accept

legacy_geometry_lab_bp = Blueprint('legacy_geometry_lab', __name__)

@legacy_geometry_lab_bp.get('/api/runtime-sites/<site_id>/legacy-geometry-preview')
@require_manager_session
def legacy_geometry_preview(site_id):
    return jsonify(preview(site_id))

@legacy_geometry_lab_bp.post('/api/runtime-sites/<site_id>/legacy-geometry-lab-accept')
@require_manager_session
def legacy_geometry_accept(site_id):
    try:
        return jsonify(accept(site_id, request.get_json(silent=True) or {}))
    except (OSError, ValueError, KeyError, PermissionError, RuntimeError) as exc:
        return jsonify({'ok': False, 'error': str(exc), 'runtime_changed': False}), 409
