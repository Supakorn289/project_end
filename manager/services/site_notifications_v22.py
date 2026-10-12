"""v2.2: immutable notification-only revision fork for existing LAB sites.

The source revision and current runtime are never changed.  A notification test
is required before the new revision is committed.  The service must be called
through an authenticated manager session and explicitly confirmed by operator.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from manager.services import site_registry
from manager.services.activation_plan import build_activation_plan
from manager.services.legacy_geometry_lab import revision_lab_trial_guard
from manager.services.revision_engine import REVISION_ROOT, LOCK_FILE
from manager.services.site_lifecycle_v2 import check_revision_source_integrity
from manager.services.site_store import get_active_site
from manager.services.telegram_setup import _validate_token, _validate_chat_id

MAX_FILE = 16 * 1024 * 1024
REV_PATTERN = re.compile(r'^rev-[A-Za-z0-9TZ_-]{8,80}$')


def _json(path):
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise ValueError('invalid_revision_metadata')
    return obj


def _sha(path):
    h = hashlib.sha256()
    with path.open('rb') as fd:
        for data in iter(lambda: fd.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def _write_json(path, value, secret=False):
    with path.open('x', encoding='utf-8') as fd:
        os.fchmod(fd.fileno(), 0o600 if secret else 0o640)
        json.dump(value, fd, sort_keys=True, ensure_ascii=False, indent=2)
        fd.write('\n')
        fd.flush()
        os.fsync(fd.fileno())


def _source(site_id, revision_id):
    site_id = site_registry._validate_site_id(site_id)
    if not REV_PATTERN.fullmatch(str(revision_id)):
        raise ValueError('invalid_revision_id')
    row = (site_registry.list_registered_sites().get('sites') or {}).get(site_id)
    if not row or str(row.get('mode', '')).upper() != 'LAB':
        raise PermissionError('notification_fork_requires_registered_lab_site')
    base = REVISION_ROOT / site_id
    src = base / revision_id
    if base.is_symlink() or src.is_symlink() or not src.is_dir():
        raise FileNotFoundError('source_revision_missing')
    check_revision_source_integrity(site_id, revision_id)
    meta = _json(src / 'revision.json')
    site_meta = _json(src / 'site_record.json')
    if (meta.get('status') != 'VALIDATED_CANDIDATE' or
        meta.get('candidate_ready') is not True or
        meta.get('site_id') != site_id or
        site_meta.get('mode') != 'LAB'):
        raise ValueError('source_revision_not_validated_lab')
    plan = build_activation_plan(site_id, revision_id)
    if (plan.get('activatable') is not True or plan.get('site_id') != site_id or
        plan.get('revision_id') != revision_id):
        raise ValueError('source_activation_plan_not_ready')
    err = revision_lab_trial_guard(src, site_id, 'LAB', 'LAB')
    if err:
        raise ValueError('source_lab_evidence_invalid:' + err)
    return src, plan


def preview(site_id, revision_id):
    src, plan = _source(site_id, revision_id)
    telegram = src / 'artifacts' / 'telegram.json'
    return {
        'ok': True, 'site_id': site_id, 'revision_id': revision_id,
        'eligible': True, 'mode': 'LAB',
        'existing_telegram': telegram.is_file() and not telegram.is_symlink(),
        'existing_notification_configured': bool(plan.get('secret_status', {}).get('telegram_token')),
        'legacy_lab_trial': bool(plan.get('legacy_lab_trial')),
        'required_action': 'enter_site_specific_token_and_chat_then_test_and_publish',
        'runtime_changed': False,
    }


def _notify(token, chat_id, site_id):
    """Test exactly the proposed Bot and Chat. Never return URL/exception/token."""
    message = f'[Smart Fire v2.2] Notification test for site {site_id}. No fire incident.'
    payload = urllib.parse.urlencode({'chat_id': chat_id, 'text': message}).encode('utf-8')
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=18) as res:
            if res.status != 200:
                return False
            result = json.loads(res.read(65536))
            return result.get('ok') is True
    except Exception:
        return False


def _source_files(source):
    entries = _json(source / 'manifest.json').get('files')
    if not isinstance(entries, list) or not entries or len(entries) > 300:
        raise ValueError('invalid_source_manifest')
    filenames = set()
    for entry in entries:
        rel = entry.get('path')
        if not isinstance(rel, str) or not rel or rel.startswith('/'):
            raise ValueError('unsafe_artifact_name')
        parts = Path(rel).parts
        if '..' in parts or '.' in parts or rel in filenames:
            raise ValueError('unsafe_or_duplicate_artifact')
        filenames.add(rel)
        p = source / 'artifacts' / rel
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE:
            raise ValueError('source_artifact_missing_or_unsafe')
        if any(x.is_symlink() for x in p.parents if x != source and source in x.parents):
            raise ValueError('source_artifact_parent_symlink')
    return entries


def _active_credentials():
    """Read active REVISION only; never read or mutate production.env."""
    active = get_active_site() or {}
    site_id, rev = active.get('site_id'), active.get('revision_id')
    if not site_id or not rev:
        raise RuntimeError('active_runtime_identity_missing')
    fp = REVISION_ROOT / site_id / rev / 'artifacts' / 'telegram.json'
    if not fp.is_file() or fp.is_symlink():
        return active, {}
    data = _json(fp)
    env = data.get('runtime_env') or data
    return active, {
        'token': env.get('TELEGRAM_TOKEN') or env.get('telegram_token') or env.get('token'),
        'chat_id': env.get('TELEGRAM_CHAT_ID') or env.get('telegram_chat_id') or env.get('chat_id'),
    }


def _shared_fields(left_token, left_chat, right_token, right_chat):
    """Compare values in process; never return a token or chat identifier."""
    shared = []
    if left_token and right_token and hmac.compare_digest(str(left_token), str(right_token)):
        shared.append('bot')
    if left_chat and right_chat and hmac.compare_digest(str(left_chat), str(right_chat)):
        shared.append('chat')
    return shared


def _telegram_from_revision(directory):
    """Trust only a regular Telegram artifact matching its immutable manifest."""
    try:
        artifact = directory / 'artifacts' / 'telegram.json'
        manifest_path = directory / 'manifest.json'
        if (directory.is_symlink() or artifact.is_symlink() or
            manifest_path.is_symlink() or not artifact.is_file()):
            return {}
        files = _json(manifest_path).get('files') or []
        expected = next((entry.get('sha256') for entry in files
                         if isinstance(entry, dict) and entry.get('path') == 'telegram.json'), None)
        if not isinstance(expected, str) or _sha(artifact) != expected:
            return {}
        data = _json(artifact)
        env = data.get('runtime_env') or data
        if not isinstance(env, dict):
            return {}
        return {
            'token': env.get('TELEGRAM_TOKEN') or env.get('telegram_token') or env.get('token'),
            'chat_id': env.get('TELEGRAM_CHAT_ID') or env.get('telegram_chat_id') or env.get('chat_id'),
        }
    except (OSError, ValueError, TypeError, StopIteration, KeyError):
        return {}


def _telegram_reuse(site_id, token, chat_id, active, active_creds):
    """Report reuse by other sites without exposing either credential."""
    matches = []
    registry = site_registry.list_registered_sites().get('sites') or {}
    active_site = active.get('site_id')
    for other_site, record in sorted(registry.items()):
        if other_site == site_id:
            continue
        if not isinstance(record, dict):
            continue
        try:
            site_registry._validate_site_id(other_site)
        except (ValueError, TypeError):
            continue
        is_active = other_site == active_site
        found = active_creds if is_active else {}
        if not is_active:
            directory = REVISION_ROOT / other_site
            if directory.is_symlink() or not directory.is_dir():
                continue
            # Compare with the most recent validated revision of each other site.
            try:
                revisions = sorted((p for p in directory.iterdir()
                                    if p.is_dir() and not p.is_symlink()
                                    and REV_PATTERN.fullmatch(p.name)), reverse=True)
            except OSError:
                continue
            for revision in revisions[:200]:
                try:
                    metadata = _json(revision / 'revision.json')
                    if (metadata.get('site_id') != other_site or
                        metadata.get('status') != 'VALIDATED_CANDIDATE' or
                        metadata.get('candidate_ready') is not True):
                        continue
                except (ValueError, OSError):
                    continue
                found = _telegram_from_revision(revision)
                break
        shared = _shared_fields(token, chat_id, found.get('token'), found.get('chat_id'))
        if shared:
            matches.append({
                'site_id': other_site,
                'site_name': str(record.get('display_name') or other_site)[:100],
                'active': is_active,
                'shared': shared,
            })
    # The published warning contains only labels and site identities.
    return {'reused': bool(matches), 'matches': matches}


def check_reuse(site_id, revision_id, payload):
    """Authenticated read-only check. Does not send a Telegram message."""
    token = _validate_token(payload.get('telegram_token'))
    chat_id = _validate_chat_id(payload.get('telegram_chat_id'))
    active, creds = _active_credentials()
    if site_id == active.get('site_id'):
        raise PermissionError('inactive_site_only_use_active_working_copy')
    _source(site_id, revision_id)
    return {
        'ok': True, 'site_id': site_id, 'revision_id': revision_id,
        'telegram_reuse': _telegram_reuse(site_id, token, chat_id, active, creds),
        'runtime_changed': False, 'telegram_test_sent': False,
    }


def _verification_from_parent(parent):
    verified = _json(parent / 'final_verification.json')
    if verified.get('candidate_ready') is not True or verified.get('blocker_count') != 0:
        raise ValueError('parent_verification_blocked')
    for key in ('checks', 'warnings'):
        for item in verified.get(key, []):
            if item.get('key') in ('telegram_config', 'telegram_test'):
                item.update({'ok': True, 'status': 'PASS', 'detail': 'Site-specific Telegram tested before notification-only fork',
                             'source': 'notification-only-v2.2'})
    verified['warnings'] = [w for w in verified.get('warnings', []) if w.get('key') not in ('telegram_config', 'telegram_test')]
    verified['warning_count'] = len(verified['warnings'])
    verified['notification_test_passed'] = True
    verified['notification_revision_scope'] = 'telegram_only'
    verified['ready_for_activation'] = False  # Activation Plan is separate.
    return verified


def fork(site_id, revision_id, payload):
    """Explicit operator action. Test new bot/chat then create sealed revision."""
    if payload.get('confirm_site_id') != site_id or payload.get('confirm_revision_id') != revision_id:
        raise ValueError('typed_confirmation_required')
    token = _validate_token(payload.get('telegram_token'))
    chat_id = _validate_chat_id(payload.get('telegram_chat_id'))
    before, current_creds = _active_credentials()
    if site_id == before.get('site_id'):
        raise PermissionError('inactive_site_only_use_active_working_copy')
    source, plan = _source(site_id, revision_id)
    old = _json(source / 'revision.json')
    if not _notify(token, chat_id, site_id):
        raise RuntimeError('telegram_delivery_test_failed_no_revision_created')
    # Notification may take seconds; fail closed if active pointers have changed.
    if get_active_site() != before:
        raise RuntimeError('active_identity_changed_during_test')
    if not LOCK_FILE.parent.is_dir():
        raise RuntimeError('revision_storage_missing')
    with LOCK_FILE.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        source, plan = _source(site_id, revision_id)
        if get_active_site() != before:
            raise RuntimeError('active_identity_changed_before_publish')
        entries = _source_files(source)
        reuse = _telegram_reuse(site_id, token, chat_id, before, current_creds)
        verified = _verification_from_parent(source)
        telegram = {
            'version': 1, 'telegram_token': token, 'telegram_chat_id': chat_id,
            'status': 'CANDIDATE', 'tested': True, 'runtime_changed': False,
        }
        files = [e for e in entries if e['path'] != 'telegram.json']
        serialized = json.dumps(telegram, sort_keys=True, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
        files.append({'path': 'telegram.json', 'sha256': hashlib.sha256(serialized).hexdigest(),
                      'size': len(serialized), 'source': 'site-notification-v2.2'})
        files.sort(key=lambda x: x['path'])
        digest = hashlib.sha256(json.dumps({
            'site_id': site_id, 'parent_revision': revision_id,
            'files': files, 'verification': verified,
        }, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        new_id = f'rev-{stamp}-{digest[:12]}'
        directory = REVISION_ROOT / site_id
        new_final = directory / new_id
        if new_final.exists() or new_final.is_symlink():
            raise RuntimeError('revision_id_collision_try_again')
        tmp = Path(tempfile.mkdtemp(prefix='.v22-notification-', dir=directory))
        committed = False
        try:
            (tmp / 'artifacts').mkdir(mode=0o700)
            for entry in files:
                rel = entry['path']
                target = tmp / 'artifacts' / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if rel == 'telegram.json':
                    _write_json(target, telegram, secret=True)
                else:
                    shutil.copyfile(source / 'artifacts' / rel, target, follow_symlinks=False)
                    target.chmod(0o600 if target.name == 'camera_connection.json' else 0o640)
                if _sha(target) != entry['sha256']:
                    raise RuntimeError('staged_artifact_digest_mismatch')
            meta = dict(old)
            meta.update({'revision_id': new_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                         'parent_revision': revision_id, 'change_scope': 'telegram_only',
                         'candidate_digest': digest, 'blocker_count': 0,
                         'warning_count': verified['warning_count'], 'runtime_changed': False})
            manifest = {'schema_version': 1, 'revision_id': new_id,
                        'candidate_digest': digest, 'files': files}
            _write_json(tmp / 'revision.json', meta)
            _write_json(tmp / 'manifest.json', manifest)
            _write_json(tmp / 'final_verification.json', verified)
            for name in ('wizard_state.json', 'site_record.json', 'runtime_baseline.json'):
                src = source / name
                if not src.is_file() or src.is_symlink():
                    raise RuntimeError('parent_revision_document_missing:' + name)
                shutil.copyfile(src, tmp / name, follow_symlinks=False)
                (tmp / name).chmod(0o640)
            err = revision_lab_trial_guard(tmp, site_id, 'LAB', 'LAB')
            if err:
                raise RuntimeError('lab_evidence_invalid_after_fork:' + err)
            # Forbid changing camera and calibration in a notification-only fork.
            originals = {x['path']: x['sha256'] for x in entries if x['path'] != 'telegram.json'}
            after_map = {x['path']: x['sha256'] for x in files if x['path'] != 'telegram.json'}
            if originals != after_map:
                raise RuntimeError('non_notification_artifact_changed')
            os.rename(tmp, new_final)
            committed = True
        finally:
            if not committed and tmp.exists():
                shutil.rmtree(tmp)
        result = build_activation_plan(site_id, new_id)
        if (result.get('activatable') is not True or result.get('site_id') != site_id or
            result.get('revision_id') != new_id or
            result.get('secret_status', {}).get('telegram_token') is not True or
            bool(result.get('legacy_lab_trial')) != bool(plan.get('legacy_lab_trial'))):
            # This new revision has never been activated. Quarantine, never mutate parent.
            quarantine = REVISION_ROOT.parent / 'trash' / 'notification-fork-rejected' / site_id / new_id
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            quarantine.parent.chmod(0o700)
            os.rename(new_final, quarantine)
            raise RuntimeError('new_revision_activation_plan_failed_quarantined')
        from manager.services.runtime_site_crud import _audit
        _audit('site_notification_revision_published', site_id=site_id,
               parent_revision=revision_id, revision_id=new_id,
               change_scope='telegram_only', artifact_count=len(files),
               shared_telegram_sites=[x['site_id'] for x in reuse['matches']])
        return {'ok': True, 'published': True, 'site_id': site_id, 'revision_id': new_id,
                'parent_revision': revision_id, 'artifact_count': len(files),
                'telegram_test_passed': True, 'telegram_configured': True,
                'legacy_lab_trial': bool(result.get('legacy_lab_trial')),
                'telegram_reuse': reuse,
                'activatable': True, 'runtime_changed': False,
                'instruction': 'Select new revision and inspect Activation Plan before LAB activation'}
