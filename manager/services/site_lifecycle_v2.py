"""Controlled legacy recovery and per-site write policy for Smart Fire Manager.

Legacy recovery deliberately does not import secrets and does not modify
active runtime pointers, daemon configuration or immutable source revisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from manager.services import site_registry
from manager.services.hardware_lock import hardware_lock
from manager.services.site_store import get_active_site
from manager.services.wizard_store import CANDIDATE_DIR, STATE_DIR, load_state, save_state
from manager.services.revision_engine import REVISION_ROOT

BASE = Path('/opt/smart-fire-detection-v2')
CAL = BASE / 'calibration'
DEPLOY = CAL / 'sites'
MGR = CAL / '.manager'
ARCHIVE = MGR / 'trash' / 'legacy-recovery'
ALLOWED = ('camera_intrinsics.json', 'distance_global.json', 'site.json', 'preset_rotation.json')
EDITABLE = {'EDITING', 'CAMERA_CHANGED', 'READY_FOR_VERIFICATION', 'CAMERA_TEST_FAILED', 'RECOVERY_EDITING'}
REV_RE = re.compile(r'^rev-[A-Za-z0-9TZ._-]{8,100}$')


def _clock():
    return datetime.now(timezone.utc).isoformat()


def _site(value):
    return site_registry._validate_site_id(value)


def _revision(value):
    val = str(value or '')
    if not REV_RE.fullmatch(val):
        raise ValueError('invalid revision id')
    return val


def _path(base, *parts):
    anchor = Path(base).resolve()
    p = anchor.joinpath(*parts)
    # validate that no symlink can escape the managed root
    if not p.resolve().is_relative_to(anchor):
        raise ValueError('managed path escape')
    return p


def _read(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('invalid JSON object')
    return value


def _hash(path):
    sha = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def _active():
    value = get_active_site() or {}
    return value.get('site_id'), value.get('revision_id')


def _registry(site_id):
    obj = site_registry.list_registered_sites().get('sites', {}).get(site_id)
    if obj is None:
        raise KeyError('site not registered')
    return obj


def _protected_site(site_id):
    """Fail closed for uncertain active pointer state."""
    from manager.services.runtime_site_crud import _runtime_pointer_guards
    names, _, uncertain = _runtime_pointer_guards()
    active_site, _ = _active()
    if uncertain:
        return True
    return bool(site_id == active_site or site_id in names)


def site_write_allowed(site_id):
    """Allowed: active editable draft, new uncommissioned site, or recovery draft."""
    site_id = _site(site_id)
    record = _registry(site_id)
    working = record.get('working_copy') or {}
    state = working.get('state')
    current_site, _ = _active()
    if current_site == site_id:
        return state in EDITABLE
    if working.get('recovery') is True and state in EDITABLE:
        return True
    # First-time setup: no immutable revision and not a deployed site
    source = REVISION_ROOT / site_id
    deployed = DEPLOY / site_id
    no_revision = not source.exists() or not any(p.is_dir() for p in source.iterdir())
    has_deployment = deployed.exists() and any(deployed.iterdir())
    return bool(no_revision and not has_deployment)


def ensure_site_write(site_id):
    if not site_write_allowed(site_id):
        raise PermissionError('site_read_only: edit active working copy, first-time setup, or explicitly recovered legacy draft')



def check_revision_source_integrity(site_id, revision_id):
    """Validate all immutable revision artifacts before creating an editable copy."""
    site_id = _site(site_id)
    revision_id = _revision(revision_id)
    source = _path(REVISION_ROOT, site_id, revision_id)
    if not source.is_dir():
        raise FileNotFoundError('Revision missing')
    revision = _read(source / 'revision.json')
    if revision.get('site_id') != site_id or revision.get('revision_id') != revision_id:
        raise ValueError('Revision identity mismatch')
    if (source / 'artifacts').is_symlink():
        raise ValueError('Revision artifacts directory must not be a symlink')
    manifest = _read(source / 'manifest.json')
    files = manifest.get('files', [])
    if not isinstance(files, list) or not files:
        raise ValueError('Revision manifest is empty')
    verified = 0
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Invalid manifest entry')
        rel = Path(str(item.get('path') or ''))
        if rel.is_absolute() or '..' in rel.parts or len(rel.parts) == 0 or str(rel) == '.':
            raise ValueError('Unsafe manifest artifact path')
        artifact = _path(source / 'artifacts', *rel.parts)
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError(f'Missing or unsafe revision artifact: {rel}')
        if _hash(artifact) != item.get('sha256'):
            raise ValueError(f'Integrity failed: {rel}')
        verified += 1
    return {'ok': True, 'site_id': site_id, 'revision_id': revision_id,
            'verified_artifacts': verified, 'write_performed': False}


def legacy_preview(site_id, revision_id):
    site_id = _site(site_id)
    revision_id = _revision(revision_id)
    _registry(site_id)
    src = _path(REVISION_ROOT, site_id, revision_id)
    if not src.is_dir() or src.is_symlink():
        raise FileNotFoundError('revision does not exist')
    artifact = src / 'artifacts'
    if not artifact.is_dir() or artifact.is_symlink():
        raise ValueError('revision artifact directory missing')
    manifest = _read(src / 'manifest.json')
    revision = _read(src / 'revision.json')
    if revision.get('site_id') != site_id or revision.get('revision_id') != revision_id:
        raise ValueError('revision identity mismatch')
    by_name = {}
    for entry in manifest.get('files', []):
        path = entry.get('path', '')
        if path in ALLOWED:
            by_name[path] = entry
    audit = []
    valid = True
    for name in ALLOWED:
        f = artifact / name
        ref = by_name.get(name) or {}
        present = f.is_file() and not f.is_symlink()
        digest = _hash(f) if present else None
        verified = bool(present and ref.get('sha256') == digest)
        legacy_file = DEPLOY / site_id / name
        legacy_hash = _hash(legacy_file) if legacy_file.is_file() and not legacy_file.is_symlink() else None
        provenance = ref.get('source')
        # 3 legacy artifacts are known historical site-specific; insist on match.
        matches_legacy = legacy_hash == digest if legacy_hash else None
        if name != 'camera_intrinsics.json' and matches_legacy is not True:
            valid = False
        if not verified:
            valid = False
        audit.append({'artifact': name, 'present': present, 'sha256': digest,
                      'manifest_verified': verified, 'manifest_source': provenance,
                      'same_as_legacy_site': matches_legacy})
    geom_path = artifact / 'preset_rotation.json'
    distance_path = artifact / 'distance_global.json'
    geom_verified = any(e['artifact'] == 'preset_rotation.json' and e['manifest_verified'] for e in audit)
    distance_verified = any(e['artifact'] == 'distance_global.json' and e['manifest_verified'] for e in audit)
    geom = _read(geom_path) if geom_verified else {}
    gate = geom.get('independent_holdout_gate') or {}
    pairs = gate.get('pairs') or {}
    holdout = gate.get('passed') is True and bool(pairs) and all(v is True for v in pairs.values())
    distance = _read(distance_path) if distance_verified else {}
    current_site, _ = _active()
    working = _registry(site_id).get('working_copy') or {}
    has_candidate = (CANDIDATE_DIR / site_id).exists() and any((CANDIDATE_DIR / site_id).iterdir())
    return {
        'ok': True, 'write_performed': False, 'site_id': site_id, 'revision_id': revision_id,
        'recoverable': bool(valid and holdout and site_id != current_site and not _protected_site(site_id)),
        'source_status': revision.get('status'), 'manifest_verified': valid,
        'artifacts': audit, 'geometry_status': geom.get('status'),
        'holdout_passed': holdout, 'holdout_pair_count': len(pairs),
        'distance_points': distance.get('points'), 'distance_pixel_rmse': distance.get('pixel_rmse'),
        'candidate_exists': has_candidate, 'existing_working_copy': working.get('state'),
        'camera_restored': False, 'telegram_restored': False,
        'warnings': [
            'This imports historical calibration only: it does not copy Camera/Telegram credentials.',
            'Confirm the same physical camera, lens, resolution, mount and PTZ preset positions before reuse.',
            'Camera Test will temporarily stop Detection; schedule a maintenance window.',
            'New Final Verification and a new immutable revision are mandatory.',
            'Historical holdout success does not substitute for current field accuracy verification.',
        ],
    }


def recover_legacy(site_id, revision_id, payload):
    site_id = _site(site_id)
    revision_id = _revision(revision_id)
    if payload.get('confirm_site_id') != site_id or payload.get('confirm_revision_id') != revision_id:
        raise ValueError('typed confirmation mismatch')
    if payload.get('same_hardware_confirmed') is not True:
        raise ValueError('must confirm physical hardware/mount continuity')
    if payload.get('maintenance_acknowledged') is not True:
        raise ValueError('must acknowledge Camera Test downtime')
    with hardware_lock('legacy-recovery:'+site_id, timeout=2.0):
        preview = legacy_preview(site_id, revision_id)
        if not preview['recoverable']:
            raise RuntimeError('legacy recovery validation failed; no write performed')
        if preview['existing_working_copy'] in EDITABLE and payload.get('archive_existing') is not True:
            raise RuntimeError('existing working copy: explicit archive_existing required')
        if preview['candidate_exists'] and payload.get('archive_existing') is not True:
            raise RuntimeError('existing candidate evidence: explicit archive_existing required')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10]
        candidate = _path(CANDIDATE_DIR, site_id)
        if candidate.is_symlink():
            raise ValueError('Candidate path must not be a symlink')
        artifact = _path(REVISION_ROOT, site_id, revision_id) / 'artifacts'
        CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix='.site-recovery-'+site_id+'-', dir=CANDIDATE_DIR))
        archived = None
        wizard = STATE_DIR / (site_id + '.json')
        wizard_backup = None
        previous = wizard.exists()
        completed = False
        installed_candidate = False
        try:
            for name in ALLOWED:
                src = artifact / name
                dst = staged / name
                shutil.copyfile(src, dst, follow_symlinks=False)
                dst.chmod(0o640)
                expected = next(e['sha256'] for e in preview['artifacts'] if e['artifact'] == name)
                if _hash(dst) != expected:
                    raise RuntimeError('staged artifact digest mismatch: '+name)
            target_archive = _path(ARCHIVE, site_id, stamp)
            target_archive.mkdir(parents=True, exist_ok=False)
            target_archive.chmod(0o700)
            if previous:
                wizard_backup = target_archive / 'wizard_state.json'
                shutil.copy2(wizard, wizard_backup)
                wizard_backup.chmod(0o600)
            if candidate.exists():
                archived = target_archive / 'candidate'
                os.rename(candidate, archived)
            os.rename(staged, candidate)
            staged = None
            installed_candidate = True
            state = _read(_path(REVISION_ROOT, site_id, revision_id) / 'wizard_state.json') if (_path(REVISION_ROOT, site_id, revision_id) / 'wizard_state.json').is_file() else load_state(site_id)
            state['camera_connection'] = {'configured': False, 'tested': False}
            state['draft_parent_revision'] = revision_id
            state['recovery'] = {'revision_id': revision_id, 'created_at': _clock(), 'verified': True}
            state['calibration_mode'] = False
            save_state(site_id, state)
            def mutate(registry):
                row = registry['sites'].get(site_id)
                if row is None: raise KeyError('site not registered')
                row['working_copy'] = {'parent_revision': revision_id, 'started_at': _clock(),
                    'state': 'RECOVERY_EDITING', 'camera_test_required': True,
                    'camera_test_passed': False, 'recovery': True}
                row['configuration_state'] = 'LEGACY_RECOVERY_CAMERA_REQUIRED'
                row['updated_at'] = _clock()
                return None
            site_registry._with_registry(mutate)
            completed = True
        finally:
            if staged and staged.exists():
                shutil.rmtree(staged)
            if not completed:
                if installed_candidate and candidate.exists() and candidate.is_dir():
                    shutil.rmtree(candidate)
                if archived and archived.exists():
                    os.rename(archived, candidate)
                if wizard_backup and wizard_backup.exists():
                    shutil.copy2(wizard_backup, wizard)
                elif not previous and wizard.exists():
                    wizard.unlink()
        from manager.services.runtime_site_crud import _audit
        _audit('legacy_site_recovery', site_id=site_id, parent_revision=revision_id,
               archive=str(_path(ARCHIVE, site_id, stamp)))
        return {'ok': True, 'site_id': site_id, 'parent_revision': revision_id,
                'state': 'RECOVERY_EDITING', 'active_runtime_changed': False,
                'candidate_backup': str(archived) if archived else None,
                'next_steps': ['configure camera in Setup Wizard', 'camera test',
                               'review Telegram', 'final verification', 'create new revision',
                               'activation plan', 'activate']}


# All mutating per-site commissioning endpoints go through this policy;
# the legacy recovery endpoint is separate and uses explicit authorization.
_PREFIXES = {
    'wizard': 3,  # /api/wizard/<site_id>/...  (except site/new, state, etc.)
    'camera-setup': 2,
    'telegram-setup': 2,
    'intrinsics-setup': 2,
    'calibration-adapter': 2,
    'geometry-adapter': 2,
    'revisions': 2,
}


def enforce_site_write_policy():
    if request.method not in {'POST', 'PATCH', 'PUT', 'DELETE'}:
        return None
    path = request.path.split('/')
    if len(path) < 4 or path[1] != 'api':
        return None
    category = path[2]
    if category not in _PREFIXES:
        return None
    if category == 'intrinsics-setup' and path[-1] == 'reuse-active':
        active_site, _ = _active()
        if path[3] != active_site:
            return jsonify({'ok': False, 'error': 'CROSS_SITE_INTRINSICS_REUSE_BLOCKED', 'runtime_changed': False}), 409
    if category == 'wizard':
        # /api/wizard/site/new and global wizard actions are managed separately.
        if path[3] in {'site', 'sites'}:
            return None
        if path[3] == 'state':
            return None
        site_id = path[3]
    else:
        site_id = path[3]
    try:
        ensure_site_write(site_id)
    except (PermissionError, ValueError, KeyError) as exc:
        return jsonify({'ok': False, 'error': 'SITE_EDIT_POLICY_BLOCKED',
                        'reason': str(exc), 'runtime_changed': False}), 409
    return None


def register_site_write_guard(app):
    app.before_request(enforce_site_write_policy)
