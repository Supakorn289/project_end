"""Manager-session API for guarded Camera Connection Editor v2.5a."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.active_camera_connection_v25 import snapshot, update, test, attest

camera_v25_bp = Blueprint('active_camera_connection_v25', __name__)


def _run(call, *args):
    try:
        return jsonify(call(*args))
    except Exception as exc:
        return jsonify({'ok':False,'error':f'{type(exc).__name__}: {exc}', 'runtime_changed':False}),409


@camera_v25_bp.get('/api/phase45/active/camera')
@require_manager_session
def camera_snapshot():
    return _run(snapshot)


@camera_v25_bp.patch('/api/phase45/active/camera')
@require_manager_session
def camera_update():
    return _run(update,request.get_json(silent=True) or {})


@camera_v25_bp.post('/api/phase45/active/camera/test')
@require_manager_session
def camera_test():
    return _run(test,request.get_json(silent=True) or {})


@camera_v25_bp.post('/api/phase45/active/camera/attest')
@require_manager_session
def camera_attest():
    return _run(attest,request.get_json(silent=True) or {})
