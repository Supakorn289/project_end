"""v2.5a: guarded Active-Site camera *connection* editor, LAB-only legacy re-attestation.

Camera tests temporarily stop/restart Detection. Never return credentials/log tails.
No method updates the Active Runtime or immutable Revision.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from manager.services.hardware_lock import hardware_lock
from manager.services.site_store import get_active_site
from manager.services.site_registry import list_registered_sites
from manager.services import site_registry
from manager.services.site_lifecycle_v2 import check_revision_source_integrity
from manager.services.revision_engine import REVISION_ROOT
from manager.services.wizard_store import CANDIDATE_DIR, load_state, save_candidate
from manager.services.runtime_site_crud import (
    _audit, _camera_summary, _require_editable_working_copy,
    update_working_camera, test_working_camera,
)
from manager.services.camera_setup import validate_camera_settings

CAMERA_FILE = 'camera_connection.json'
WAIVER_FILE = 'legacy_geometry_lab_trial.json'
NET_KEYS = frozenset({'CAMERA_IP', 'CAMERA_PORT', 'CAMERA_USER', 'CAMERA_PWD', 'RTSP_PORT', 'RTSP_PATH'})
IGNORE_DRAFT_STATE = frozenset({'draft_parent_revision', 'draft_started_at', 'calibration_mode', 'updated_at'})


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('missing_or_unsafe_file')
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise RuntimeError('invalid_json_object')
    return obj


def _sha(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('missing_or_unsafe_file')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(payload=None, *, editable=False):
    active = get_active_site() or {}
    site, rev = active.get('site_id'), active.get('revision_id')
    if not site or not rev:
        raise RuntimeError('no_active_revision')
    if payload is not None and (payload.get('site_id'), payload.get('revision_id')) != (site, rev):
        raise PermissionError('active_revision_changed_refresh_required')
    if check_revision_source_integrity(site, rev).get('ok') is not True:
        raise RuntimeError('source_revision_integrity_failed')
    record = (list_registered_sites().get('sites') or {}).get(site) or {}
    working = record.get('working_copy') or {}
    valid = bool(working.get('state') in {'EDITING', 'CAMERA_CHANGED', 'CAMERA_TEST_FAILED', 'READY_FOR_VERIFICATION'}
                 and working.get('parent_revision') == rev and working.get('recovery') is not True)
    if editable:
        if not valid:
            raise PermissionError('active_working_copy_required')
        _require_editable_working_copy(site)
    return site, rev, record, working, valid


def _paths(site, rev):
    revision = REVISION_ROOT / site / rev
    candidate = CANDIDATE_DIR / site
    if revision.is_symlink() or candidate.is_symlink():
        raise RuntimeError('unsafe_revision_or_candidate')
    return revision, candidate


def _sanitized_camera(path):
    d = _camera_summary(path)
    # Current camera credentials are *never* sent to the browser.
    return {k: d.get(k) for k in ('configured','tested','camera_ip','camera_port',
                                  'camera_user_hint','password_configured','rtsp_port','rtsp_path')}


def snapshot():
    site, rev, record, working, editable = _identity()
    revision, draft = _paths(site, rev)
    parent = revision / 'artifacts' / CAMERA_FILE
    _read(parent)
    selected = draft / CAMERA_FILE if editable else parent
    if editable:
        _read(selected)
    current_sha = _sha(selected)
    return {
        'ok': True, 'site_id': site, 'revision_id': rev,
        'mode': str(record.get('mode') or 'LAB').upper(),
        'source': 'WORKING_COPY' if editable else 'ACTIVE_REVISION',
        'editable': editable, 'working_state': working.get('state'),
        'camera_test_required': working.get('camera_test_required') is True,
        'camera_test_passed': working.get('camera_test_passed') is True,
        'active_camera': _sanitized_camera(parent),
        'selected_camera': _sanitized_camera(selected),
        'camera_digest': current_sha,
        'changed_from_active': current_sha != _sha(parent),
        'camera_test_interrupts_detection': True,
        'runtime_changed': False,
    }


def update(payload):
    site, rev, record, working, editable = _identity(payload, editable=True)
    if str(record.get('mode') or '').upper() != 'LAB':
        raise PermissionError('camera_editor_v25_lab_only_use_verified_production_workflow')
    with hardware_lock('v25:camera-connection-edit', timeout=3.0):
        site2, rev2, record, working, editable = _identity(payload, editable=True)
        if (site2, rev2) != (site, rev):
            raise RuntimeError('active_revision_changed')
        source, draft = _paths(site, rev)
        file = draft / CAMERA_FILE
        if _sha(file) != payload.get('expected_digest'):
            raise RuntimeError('camera_draft_changed_refresh_required')
        old = _read(file).get('runtime_env') or {}
        def field(name, key, preserve_empty=False):
            v = payload.get(name) if name in payload else old.get(key)
            return old.get(key) if preserve_empty and (v is None or v == '') else v
        fields = {
            'camera_ip': field('camera_ip','CAMERA_IP'),
            'camera_port': field('camera_port','CAMERA_PORT'),
            'camera_user': field('camera_user','CAMERA_USER',True),
            'camera_password': field('camera_password','CAMERA_PWD',True),
            'rtsp_port': field('rtsp_port','RTSP_PORT'),
            'rtsp_path': field('rtsp_path','RTSP_PATH'),
        }
        validated = validate_camera_settings(**fields)
        if all(str(validated[k]) == str(old.get(k)) for k in NET_KEYS):
            raise ValueError('no_connection_change_detected')
        # Legacy API safely writes Candidate and revokes previous test, never changes active Runtime.
        result = update_working_camera(site, fields)
        return {
            'ok': True, 'site_id': site, 'revision_id': rev,
            'camera': _sanitized_camera(file),
            'camera_digest': _sha(file),
            'camera_test_required': True,
            'runtime_changed': False,
            'warning': 'Camera test will temporarily interrupt Detection; test during supervised LAB maintenance.',
        }


def test(payload):
    site, rev, record, working, editable = _identity(payload, editable=True)
    if str(record.get('mode') or '').upper() != 'LAB':
        raise PermissionError('camera_editor_v25_lab_only_use_verified_production_workflow')
    if payload.get('confirm_detection_interruption') is not True:
        raise PermissionError('explicit_detection_interruption_ack_required')
    revision, draft = _paths(site, rev)
    file = draft / CAMERA_FILE
    if _sha(file) != payload.get('expected_digest'):
        raise RuntimeError('camera_draft_changed_refresh_required')
    # Underlying Camera Test acquires hardware.lock; MUST NOT nest that lock.
    result = test_working_camera(site)
    same_active = (get_active_site() or {})
    intact = same_active.get('site_id') == site and same_active.get('revision_id') == rev
    file_digest = _sha(file)
    passed = (result.get('ok') is True and result.get('tested') is True and
              result.get('detection_restored') is True and intact and
              _read(file).get('tested') is True)
    # The v2.4 camera-test API records only subprocess success; v2.5 additionally
    # requires Detection to be restored and binds the test to exact camera bytes.
    def reconcile(registry):
        r = (registry.get('sites') or {}).get(site) or {}
        w = r.get('working_copy') or {}
        if w.get('parent_revision') != rev or w.get('recovery') is True:
            raise RuntimeError('working_copy_changed_after_camera_test')
        w['camera_v25_test_digest'] = file_digest if passed else None
        w['camera_v25_detection_restored'] = bool(passed)
        w['camera_test_passed'] = bool(passed)
        w['camera_test_required'] = not passed
        if not passed:
            w['state'] = 'CAMERA_TEST_FAILED'
        r['working_copy'] = w
        registry['sites'][site] = r
    site_registry._with_registry(reconcile)
    _audit('v25_camera_connection_test',site_id=site,revision_id=rev,passed=passed)
    return {
        'ok': passed, 'tested': result.get('tested') is True,
        'detection_was_active': bool(result.get('detection_was_active')),
        'detection_restored': result.get('detection_restored') is True,
        'active_runtime_unchanged': intact, 'camera_digest': _sha(file),
        'camera_test_passed': passed, 'runtime_changed': False,
        'error': None if passed else ('camera_test_failed_or_detection_restore_not_confirmed'),
        # Deliberately omit test_camera.py stdout/stderr: they can include credentials.
    }


def _camera_artifact_change_only(parent_camera, new_camera):
    """Conservatively allow changed network credentials/host/ports, no hidden camera metadata."""
    p, q = _read(parent_camera), _read(new_camera)
    if not isinstance(p.get('runtime_env'), dict) or not isinstance(q.get('runtime_env'),dict):
        return False
    for key in set(p) | set(q):
        if key in {'runtime_env','status','tested'}:
            continue
        if p.get(key) != q.get(key):
            return False
    env_a, env_b = p['runtime_env'], q['runtime_env']
    if any(env_a.get(k) != env_b.get(k) for k in (set(env_a) | set(env_b)) - NET_KEYS):
        return False
    if q.get('tested') is not True:
        return False
    try:
        validate_camera_settings(
            camera_ip=env_b.get('CAMERA_IP'), camera_port=env_b.get('CAMERA_PORT'),
            camera_user=env_b.get('CAMERA_USER'),camera_password=env_b.get('CAMERA_PWD'),
            rtsp_port=env_b.get('RTSP_PORT'),rtsp_path=env_b.get('RTSP_PATH'))
    except (ValueError, TypeError):
        return False
    return True


def _allowed_maintenance(site, rev, record, working):
    if str(record.get('mode') or '').upper() != 'LAB':
        raise PermissionError('legacy_camera_maintenance_lab_only')
    if working.get('camera_test_required') is True or working.get('camera_test_passed') is not True or working.get('state') != 'READY_FOR_VERIFICATION':
        raise RuntimeError('camera_test_must_pass_before_attestation')
    source, draft = _paths(site, rev)
    if (working.get('camera_v25_detection_restored') is not True or
        working.get('camera_v25_test_digest') != _sha(draft / CAMERA_FILE)):
        raise RuntimeError('v25_camera_test_or_detection_restore_evidence_missing')
    artifacts = source / 'artifacts'
    manifest = _read(source / 'manifest.json')
    names = [x.get('path') for x in manifest.get('files',[]) if isinstance(x,dict)]
    required = {'camera_connection.json','camera_intrinsics.json','distance_global.json',
                'preset_rotation.json','site.json','telegram.json','legacy_geometry_lab_trial.json'} | {
                f'ptz_captures/main/preset_{i}.jpg' for i in range(1,10)}
    if (len(names)!=len(manifest.get('files',[])) or len(set(names))!=len(names) or
        set(names) not in (required, required | {'site_detection_settings.json'})):
        raise RuntimeError('legacy_manifest_shape_changed')
    candidate_files=set()
    for path in draft.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('unsafe_candidate_artifact')
        if path.is_file():
            candidate_files.add(path.relative_to(draft).as_posix())
    if candidate_files != set(names):
        raise RuntimeError('camera_maintenance_must_not_add_or_remove_artifacts')
    if _sha(artifacts / CAMERA_FILE) == _sha(draft / CAMERA_FILE):
        raise RuntimeError('no_camera_artifact_change')
    for name in set(names) - {CAMERA_FILE,WAIVER_FILE}:
        if _sha(artifacts / name) != _sha(draft / name):
            raise RuntimeError('non_camera_artifact_changed:'+name)
    if not _camera_artifact_change_only(artifacts / CAMERA_FILE, draft / CAMERA_FILE):
        raise RuntimeError('camera_change_exceeds_connection_scope')
    old = _read(source / 'wizard_state.json')
    new = load_state(site)
    def rest(a):
        return {k:v for k,v in a.items() if k not in IGNORE_DRAFT_STATE | {'camera_connection'}}
    from manager.services.runtime_site_crud import verified_published_history
    if old.get('latest_revision') != new.get('latest_revision'):
        if not verified_published_history(site, working, new.get('latest_revision')):
            raise RuntimeError('unverified_wizard_revision_history')
        old = {k:v for k,v in old.items() if k != 'latest_revision'}
        new = {k:v for k,v in new.items() if k != 'latest_revision'}
    if rest(old)!=rest(new) or new.get('draft_parent_revision') != rev:
        raise RuntimeError('wizard_modified_outside_camera_connection')
    state_camera = new.get('camera_connection') or {}
    current = _read(draft / CAMERA_FILE)
    env = current['runtime_env']
    if (state_camera.get('tested') is not True or state_camera.get('configured') is not True or
        state_camera.get('camera_ip') != env.get('CAMERA_IP') or
        str(state_camera.get('camera_port')) != str(env.get('CAMERA_PORT')) or
        str(state_camera.get('rtsp_port')) != str(env.get('RTSP_PORT')) or
        state_camera.get('rtsp_path') != env.get('RTSP_PATH')):
        raise RuntimeError('camera_wizard_evidence_mismatch')
    parent_waiver = _read(artifacts / WAIVER_FILE)
    current_waiver = _read(draft / WAIVER_FILE)
    if any(parent_waiver.get(k) != current_waiver.get(k)
           for k in set(parent_waiver)|set(current_waiver) if k not in {'files_sha256','connection_maintenance'}):
        raise RuntimeError('legacy_waiver_other_metadata_changed')
    old_dig = parent_waiver.get('files_sha256') or {}
    new_dig = current_waiver.get('files_sha256') or {}
    if old_dig != new_dig and set(new_dig) != set(old_dig):
        raise RuntimeError('legacy_waiver_dependency_list_changed')
    for name,digest in old_dig.items():
        if name != CAMERA_FILE and (_sha(draft / name)!=digest or new_dig.get(name)!=digest):
            raise RuntimeError('original_legacy_calibration_not_preserved:'+name)
    return artifacts, draft, parent_waiver, current_waiver


def attest(payload):
    site, rev, record, working, _ = _identity(payload, editable=True)
    if (payload.get('confirm_site_id') != site or
        payload.get('same_physical_camera_ack') is not True or
        payload.get('installation_unchanged_ack') is not True or
        payload.get('explicit_lab_only_ack') is not True):
        raise PermissionError('typed_site_id_and_3_camera_safety_acknowledgements_required')
    with hardware_lock('v25:legacy-lab-camera-reattest',timeout=3.0):
        _identity(payload, editable=True)
        site,rev,record,working,_=_identity(payload,editable=True)
        artifacts,draft,old,waiver = _allowed_maintenance(site, rev, record, working)
        camera_sha = _sha(draft / CAMERA_FILE)
        if payload.get('expected_digest') != camera_sha:
            raise RuntimeError('camera_draft_changed_refresh_required')
        updated = dict(old)
        updated['files_sha256'] = dict(old['files_sha256'], **{CAMERA_FILE: camera_sha})
        updated['connection_maintenance'] = {
            'parent_revision':rev,
            'source_camera_sha256':_sha(artifacts / CAMERA_FILE),
            'candidate_camera_sha256':camera_sha,
            'same_physical_camera_ack':True,
            'installation_unchanged_ack':True,
            'explicit_lab_only_ack':True,
            'camera_test_passed':True,
            'ack_at':datetime.now(timezone.utc).isoformat(),
        }
        file=save_candidate(site,WAIVER_FILE,updated)
        file.chmod(0o600)
        from manager.services.legacy_geometry_lab import preview
        result=preview(site)
        if result.get('accepted') is not True or result.get('connection_only') is not True:
            # Fail-closed: restore prior draft waiver (if it existed), not an invented PASS.
            save_candidate(site,WAIVER_FILE,waiver).chmod(0o600)
            raise RuntimeError('post_attestation_legacy_publish_gate_failed')
        _audit('v25_camera_maintenance_attested',site_id=site,parent_revision=rev,
               camera_source_digest=_sha(artifacts/CAMERA_FILE),camera_candidate_digest=camera_sha,
               lab_only=True)
        return {'ok':True,'site_id':site,'revision_id':rev,
                'accepted':True,'connection_only':True,'lab_only':True,
                'runtime_changed':False,
                'warning':'Historic Geometry remains LAB-only; physical-camera identity is an operator attestation, not independently verified.'}
