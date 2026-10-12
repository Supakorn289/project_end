"""Authorized read-only recovery preview + confirmed recovery transaction."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.site_lifecycle_v2 import legacy_preview, recover_legacy

site_v2_bp = Blueprint('runtime_site_v2', __name__)


@site_v2_bp.get('/api/runtime-sites/<site_id>/revision/<revision_id>/recovery-preview')
@require_manager_session
def recovery_preview(site_id, revision_id):
    try:
        return jsonify(legacy_preview(site_id, revision_id))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409


@site_v2_bp.post('/api/runtime-sites/<site_id>/revision/<revision_id>/recover')
@require_manager_session
def recover(site_id, revision_id):
    try:
        return jsonify(recover_legacy(site_id, revision_id, request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'runtime_changed': False}), 409
