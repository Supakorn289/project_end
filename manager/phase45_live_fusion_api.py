"""Session/CSRF protected API for real-camera three-preset fusion tests."""
from flask import Blueprint, jsonify, request, send_file
from manager.security import require_manager_session
from manager.services.ops_agent import agent_request
from manager.services.live_fusion_web import get_status, get_image

live_fusion_bp=Blueprint('phase45_live_fusion', __name__)

def _presets(payload):
    values=payload.get('presets') if isinstance(payload,dict) else None
    if not isinstance(values,list) or len(values)!=3 or any(type(v)!=int or not 1<=v<=9 for v in values) or len(set(values))!=3:
        raise ValueError('choose_exactly_three_distinct_presets_1_to_9')
    return values

@live_fusion_bp.post('/api/phase45/fusion/live/preview')
@require_manager_session
def live_preview():
    try:
        presets=_presets(request.get_json(silent=True) or {})
        result=agent_request({'action':'live_fusion_web_preview','presets':presets},timeout=55)
        return jsonify(result), 200 if result.get('ok') else 409
    except ValueError as e:
        return jsonify({'ok':False,'error':str(e)}),400

@live_fusion_bp.post('/api/phase45/fusion/live/start')
@require_manager_session
def live_start():
    try:
        obj=request.get_json(silent=True) or {}
        presets=_presets(obj)
        if obj.get('confirmation')!='LAB_LIVE_TEST' or obj.get('maintenance_ack') is not True:
            raise ValueError('maintenance_confirmation_required')
        result=agent_request({'action':'live_fusion_web_start','presets':presets,
                              'site_id':obj.get('site_id'),'revision_id':obj.get('revision_id')},timeout=60)
        return jsonify(result),200 if result.get('ok') else 409
    except ValueError as e:
        return jsonify({'ok':False,'error':str(e)}),400

@live_fusion_bp.get('/api/phase45/fusion/live/jobs/<job_id>')
@require_manager_session
def live_status(job_id):
    try:
        return jsonify(get_status(job_id))
    except (ValueError, FileNotFoundError):
        return jsonify({'ok':False,'error':'test_not_found'}),404
    except Exception:
        return jsonify({'ok':False,'error':'test_status_unavailable'}),503

@live_fusion_bp.get('/api/phase45/fusion/live/jobs/<job_id>/images/<int:preset>')
@require_manager_session
def live_image(job_id,preset):
    try:
        path=get_image(job_id,preset)
        rsp=send_file(path,mimetype='image/jpeg',conditional=False)
        rsp.headers['Cache-Control']='private, no-store'
        return rsp
    except (ValueError,FileNotFoundError):
        return jsonify({'ok':False,'error':'image_not_available'}),404
