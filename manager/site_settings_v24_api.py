"""Manager-session protected Site Settings v2.4 endpoints."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.site_settings_v24 import snapshot, save

site_settings_v24_bp = Blueprint('site_settings_v24', __name__)

@site_settings_v24_bp.get('/api/phase45/site-settings')
@require_manager_session
def site_settings_snapshot():
    try:
        return jsonify(snapshot())
    except Exception as exc:
        return jsonify({'ok':False,'error':f'{type(exc).__name__}: {exc}'}),409

@site_settings_v24_bp.post('/api/phase45/site-settings')
@require_manager_session
def site_settings_update():
    try:
        return jsonify(save(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({'ok':False,'error':f'{type(exc).__name__}: {exc}', 'runtime_changed':False}),409
