"""Authenticated site-specific Telegram revision fork API."""
from flask import Blueprint, jsonify, request
from manager.security import require_manager_session
from manager.services.site_notifications_v22 import preview, fork, check_reuse

site_notification_v22_bp = Blueprint('site_notification_v22', __name__)


@site_notification_v22_bp.get('/api/runtime-sites/<site_id>/revision/<revision_id>/notification-fork-preview')
@require_manager_session
def notification_fork_preview(site_id, revision_id):
    try:
        return jsonify(preview(site_id, revision_id))
    except Exception:
        return jsonify({'ok': False, 'error': 'notification_fork_preflight_failed', 'runtime_changed': False}), 409


@site_notification_v22_bp.post('/api/runtime-sites/<site_id>/revision/<revision_id>/notification-reuse-check')
@require_manager_session
def notification_reuse_check(site_id, revision_id):
    try:
        result = check_reuse(site_id, revision_id, request.get_json(silent=True) or {})
        return jsonify(result)
    except (ValueError, PermissionError, FileNotFoundError, RuntimeError):
        return jsonify({'ok': False, 'error': 'notification_reuse_check_failed',
                        'runtime_changed': False}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'notification_reuse_internal_error',
                        'runtime_changed': False}), 500


@site_notification_v22_bp.post('/api/runtime-sites/<site_id>/revision/<revision_id>/notification-fork')
@require_manager_session
def notification_fork_publish(site_id, revision_id):
    try:
        result = fork(site_id, revision_id, request.get_json(silent=True) or {})
        return jsonify(result)
    except (ValueError, PermissionError, FileNotFoundError, RuntimeError) as exc:
        # Allowlisted public codes, never the exception text or a Bot Token.
        message = str(exc)
        if message.startswith('telegram_delivery_test_failed'):
            code = 'telegram_test_failed_check_bot_chat_permissions'
        elif message.startswith('typed_confirmation'):
            code = 'typed_site_revision_confirmation_required'
        else:
            code = 'notification_fork_validation_failed'
        return jsonify({'ok': False, 'error': code, 'runtime_changed': False}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'notification_fork_internal_error', 'runtime_changed': False}), 500
