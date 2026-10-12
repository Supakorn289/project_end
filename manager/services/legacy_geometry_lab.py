"""Explicit LAB-only legacy geometry trial admission.

This is NOT a new solver result and NEVER proves intrinsics lineage or field
accuracy. It permits controlled laboratory trials with documented uncertainty.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from manager.services import site_registry
from manager.services.site_lifecycle_v2 import (
    EDITABLE, _active, _read, _registry, _protected_site,
    check_revision_source_integrity, ensure_site_write,
)
from manager.services.wizard_store import CANDIDATE_DIR, load_state, save_candidate
from manager.services.revision_engine import REVISION_ROOT

FILENAME = 'legacy_geometry_lab_trial.json'
MODEL = 'calibrated-global-raw-ray-rotation'
STATUS = 'PASS_CANDIDATE_NOT_INSTALLED'
INPUTS = ('camera_intrinsics.json','distance_global.json','site.json','preset_rotation.json')


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _path(base, name):
    p = Path(base) / name
    if p.is_symlink() or not p.is_file():
        raise ValueError('missing/unsafe calibration evidence: '+name)
    return p


def _inputs(root, wizard):
    files = {}
    for name in INPUTS:
        files[name] = _sha(_path(root, name))
    camera_file = _path(root, 'camera_connection.json')
    camera = _read(camera_file)
    if camera.get('tested') is not True or (wizard.get('camera_connection') or {}).get('tested') is not True:
        raise ValueError('camera_test_not_passed')
    files['camera_connection.json'] = _sha(camera_file)
    captures = (wizard.get('captures') or {}).get('main') or {}
    for i in range(1, 10):
        if (captures.get(str(i)) or {}).get('ok') is not True:
            raise ValueError('ptz_capture_not_passed: '+str(i))
        name = f'ptz_captures/main/preset_{i}.jpg'
        p = _path(root, name)
        if p.stat().st_size < 1024:
            raise ValueError('ptz_image_too_small: '+str(i))
        files[name] = _sha(p)
    return files


def published_lab_repair_allowed(site_id, working=None):
    """LAB_REPUBLISH_214: read-only gate for exactly one incomplete publication."""
    try:
        site_id = site_registry._validate_site_id(site_id)
        site = _registry(site_id)
        working = working if working is not None else (site.get('working_copy') or {})
        if (str(site.get('mode') or '').upper() != 'LAB' or
            working.get('state') != 'PUBLISHED' or
            working.get('recovery') is not True or
            working.get('parent_revision') != 'rev-20260928T051638Z-126de0e979b3' or
            working.get('published_revision') != 'rev-20261009T043930Z-604e3b59f090' or
            site_id != 'current-site-20260921' or
            site_id == _active()[0] or _protected_site(site_id)):
            return False
        rev = REVISION_ROOT / site_id / working['published_revision']
        check_revision_source_integrity(site_id, working['published_revision'])
        meta = _read(rev / 'revision.json')
        if meta.get('status') != 'VALIDATED_CANDIDATE' or meta.get('candidate_ready') is not True:
            return False
        manifest = _read(rev / 'manifest.json')
        expected = {'camera_connection.json','camera_intrinsics.json',
                    'distance_global.json','legacy_geometry_lab_trial.json',
                    'preset_rotation.json','site.json'}
        if {x.get('path') for x in manifest.get('files', [])} != expected:
            return False
        if revision_lab_trial_guard(rev, site_id, 'LAB', 'LAB') != 'legacy_lab_trial_missing_artifact':
            return False
        # Published artifact values must be unchanged in Candidate.
        for name in expected:
            if _sha(_path(rev / 'artifacts', name)) != _sha(_path(CANDIDATE_DIR / site_id, name)):
                return False
        return True
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, PermissionError):
        return False


def _evidence(site_id):
    site_id = site_registry._validate_site_id(site_id)
    record = _registry(site_id)
    mode = str(record.get('mode') or 'LAB').upper()
    if mode != 'LAB':
        raise ValueError('LEGACY_LAB_ONLY: Production requires a current solver and field validation')
    working = record.get('working_copy') or {}
    if working.get('recovery') is not True or (working.get('state') not in EDITABLE and not published_lab_repair_allowed(site_id, working)):
        raise ValueError('legacy_recovery_draft_required')
    parent_id = working.get('parent_revision')
    if not parent_id:
        raise ValueError('missing_parent_revision')
    if site_id == _active()[0] or _protected_site(site_id):
        raise ValueError('active_runtime_protected')
    check_revision_source_integrity(site_id, parent_id)
    src = REVISION_ROOT / site_id / parent_id / 'artifacts'
    dst = CANDIDATE_DIR / site_id
    if dst.is_symlink():
        raise ValueError('unsafe_candidate_dir')
    for name in INPUTS:
        if _sha(_path(src, name)) != _sha(_path(dst, name)):
            raise ValueError('recovered_calibration_changed: '+name)
    geo = _read(_path(dst, 'preset_rotation.json'))
    intr = _read(_path(dst, 'camera_intrinsics.json'))
    gate = geo.get('independent_holdout_gate') or {}
    pairs = gate.get('pairs') or {}
    if (geo.get('model') != MODEL or geo.get('status') != STATUS or
        not isinstance(geo.get('presets'), dict) or len(geo['presets']) < 9 or
        gate.get('passed') is not True or not isinstance(pairs, dict) or
        len(pairs) < 8 or not all(x is True for x in pairs.values()) or
        geo.get('operator_override')):
        raise ValueError('legacy_geometry_criteria_not_met')
    if (intr.get('status') != 'intrinsics_calibrated' or
        intr.get('valid_for_production') is not True or
        (intr.get('frame_width'),intr.get('frame_height')) != (1280,720)):
        raise ValueError('intrinsics_not_qualified')
    wizard = load_state(site_id)
    return {
        'site_id': site_id, 'parent_revision': parent_id,
        'mode': 'LAB', 'holdout_pairs': len(pairs),
        'files_sha256': _inputs(dst, wizard),
        'intrinsics_lineage_proven': False,
    }


def _active_settings_trial_preview(site_id):
    """V24B: carry an *unchanged* LAB waiver into a settings-only draft.

    This never authorizes fresh calibration, camera or Telegram edits.  The
    approved evidence stays tied to its original immutable revision; absence
    of intrinsic lineage stays explicitly unproven.
    """
    try:
        site_id = site_registry._validate_site_id(site_id)
        active_site, active_rev = _active()
        if site_id != active_site or not active_rev:
            return None
        record = _registry(site_id)
        working = record.get('working_copy') or {}
        if (str(record.get('mode') or '').upper() != 'LAB' or
            working.get('state') not in {'EDITING', 'READY_FOR_VERIFICATION'} or
            working.get('recovery') is True or
            working.get('parent_revision') != active_rev or
            working.get('camera_test_required') is True):
            return None

        parent = REVISION_ROOT / site_id / active_rev
        artifacts = parent / 'artifacts'
        candidate = CANDIDATE_DIR / site_id
        if (parent.is_symlink() or artifacts.is_symlink() or
            candidate.is_symlink() or not candidate.is_dir()):
            return None
        integrity = check_revision_source_integrity(site_id, active_rev)
        if integrity.get('ok') is not True:
            return None
        meta = _read(parent / 'revision.json')
        if meta.get('status') != 'VALIDATED_CANDIDATE' or meta.get('candidate_ready') is not True:
            return None
        if revision_lab_trial_guard(parent, site_id, 'LAB', 'LAB') is not None:
            return None

        manifest = _read(parent / 'manifest.json')
        entries = manifest.get('files') or []
        names = [item.get('path') for item in entries if isinstance(item, dict)]
        required = set(INPUTS) | {'camera_connection.json', 'telegram.json', FILENAME} | {
            f'ptz_captures/main/preset_{i}.jpg' for i in range(1,10)
        }
        settings_file = 'site_detection_settings.json'
        # No other source evidence or data types may be inherited via this gate.
        if (len(names) != len(entries) or len(names) != len(set(names)) or
            set(names) not in (required, required | {settings_file})):
            return None
        candidate_files = set()
        for path in candidate.rglob('*'):
            if path.is_symlink():
                return None
            if path.is_file():
                candidate_files.add(path.relative_to(candidate).as_posix())
        if candidate_files != (set(names) | {settings_file}):
            return None
        for name in required:
            if _sha(_path(artifacts, name)) != _sha(_path(candidate, name)):
                return None

        # Prevent Wizard-only edits bypassing the Geometry solver or Camera test.
        old_wizard = _read(parent / 'wizard_state.json')
        new_wizard = load_state(site_id)
        ignored = {'draft_parent_revision', 'draft_started_at', 'calibration_mode', 'updated_at'}
        if ({k:v for k,v in old_wizard.items() if k not in ignored} !=
            {k:v for k,v in new_wizard.items() if k not in ignored}):
            return None
        if new_wizard.get('draft_parent_revision') != active_rev:
            return None

        from manager.services.site_settings_v24 import resolve_artifact
        settings = _read(_path(candidate, settings_file))
        values = resolve_artifact(settings)
        if not values:
            return None
        waiver = _read(_path(candidate, FILENAME))
        if (waiver.get('schema_version') != 1 or
            waiver.get('site_id') != site_id or waiver.get('mode') != 'LAB' or
            waiver.get('explicit_lab_only_ack') is not True or
            waiver.get('same_hardware_ack') is not True or
            waiver.get('unknown_intrinsics_lineage_ack') is not True or
            waiver.get('intrinsics_lineage_proven') is not False):
            return None
        digests = waiver.get('files_sha256') or {}
        expected_digests = set(INPUTS) | {'camera_connection.json'} | {
            f'ptz_captures/main/preset_{i}.jpg' for i in range(1,10)
        }
        if set(digests) != expected_digests:
            return None
        for name, expected_sha in digests.items():
            if _sha(_path(candidate, name)) != expected_sha:
                return None
        geometry = _read(_path(candidate, 'preset_rotation.json'))
        gate = geometry.get('independent_holdout_gate') or {}
        pairs = gate.get('pairs') or {}
        if (gate.get('passed') is not True or len(pairs) < 8 or
            not all(flag is True for flag in pairs.values())):
            return None
        return {
            'ok': True, 'eligible': True, 'accepted': True,
            'site_id': site_id, 'parent_revision': active_rev,
            'holdout_pairs': len(pairs), 'ptz_captures': 9,
            'lab_only': True, 'intrinsics_lineage_proven': False,
            'inherited_active_lab_trial': True,
            'settings_only': True,
            'warning': ('LAB settings-only inheritance from verified active revision. '
                        'Historical holdout is NOT fresh calibration proof; '
                        'intrinsics lineage and field accuracy remain unproven.'),
        }
    except (ValueError, KeyError, TypeError, OSError, RuntimeError,
            PermissionError, AttributeError):
        return None


def preview(site_id):
    """Read-only preview after existing wizard state is present."""
    try:
        evidence = _evidence(site_id)
    except (ValueError, KeyError, FileNotFoundError, PermissionError, RuntimeError, OSError) as exc:
        inherited = _active_settings_trial_preview(site_id)
        if inherited is not None:
            return inherited
        return {'ok': True, 'eligible': False, 'accepted': False,
                'site_id': site_id, 'reason': str(exc), 'lab_only': True,
                'intrinsics_lineage_proven': False}
    saved = CANDIDATE_DIR / site_id / FILENAME
    accepted = False
    if saved.is_file() and not saved.is_symlink():
        try:
            record = _read(saved)
            accepted = (
                record.get('schema_version') == 1 and
                record.get('site_id') == site_id and
                record.get('parent_revision') == evidence['parent_revision'] and
                record.get('mode') == 'LAB' and
                record.get('files_sha256') == evidence['files_sha256'] and
                record.get('intrinsics_lineage_proven') is False and
                record.get('explicit_lab_only_ack') is True and
                record.get('same_hardware_ack') is True and
                record.get('unknown_intrinsics_lineage_ack') is True
            )
        except (ValueError, OSError):
            pass
    return {'ok': True, 'eligible': True, 'accepted': accepted,
            'site_id': site_id, 'parent_revision': evidence['parent_revision'],
            'holdout_pairs': evidence['holdout_pairs'], 'ptz_captures': 9,
            'lab_only': True, 'intrinsics_lineage_proven': False,
            'warning': 'Historical holdout is not new calibration validation. '
                       'Intrinsics lineage unproven. LAB trial only; not certified for fire-safety operations.'}


def accept(site_id, payload):
    """Record informed LAB-only exception; never write a fake solver PASS."""
    ensure_site_write(site_id)
    if payload.get('confirm_site_id') != site_id or any(payload.get(k) is not True for k in (
        'same_hardware_ack','unknown_intrinsics_lineage_ack','explicit_lab_only_ack'
    )):
        raise ValueError('typed_site_id_and_three_acknowledgements_required')
    data = _evidence(site_id)  # re-evaluate immediately before write
    record = {'schema_version': 1, **data, 'accepted_at': datetime.now(timezone.utc).isoformat(),
              'same_hardware_ack': True, 'unknown_intrinsics_lineage_ack': True,
              'explicit_lab_only_ack': True,
              'review_type': 'OPERATOR_ACCEPTED_LEGACY_LAB_TRIAL_NOT_SOLVER'}
    save_candidate(site_id, FILENAME, record)
    # Maintenance Camera Test may have been performed from the Wizard rather
    # than the CRUD button. Reconcile its actual verified result into registry.
    def reconcile(registry):
        working = registry['sites'][site_id].get('working_copy') or {}
        if working.get('recovery') is not True or working.get('state') not in EDITABLE:
            raise ValueError('recovery_working_copy_changed')
        working['camera_test_required'] = False
        working['camera_test_passed'] = True
        working['state'] = 'READY_FOR_VERIFICATION'
        registry['sites'][site_id]['working_copy'] = working
    site_registry._with_registry(reconcile)
    from manager.services.runtime_site_crud import _audit
    _audit('legacy_geometry_lab_trial_accepted', site_id=site_id,
           parent_revision=data['parent_revision'], holdout_pairs=data['holdout_pairs'])
    return preview(site_id)


def revision_lab_trial_guard(revision_dir, site_id, site_mode, current_mode):
    """Fail closed for archived LAB-only evidence if promoted or modified."""
    root = Path(revision_dir) / 'artifacts'
    file = root / FILENAME
    if not file.exists():
        return None
    if file.is_symlink() or site_mode != 'LAB' or current_mode != 'LAB':
        return 'legacy_lab_trial_not_allowed_in_production'
    try:
        record = _read(file)
        if (record.get('site_id') != site_id or record.get('mode') != 'LAB' or
            record.get('intrinsics_lineage_proven') is not False or
            record.get('explicit_lab_only_ack') is not True):
            return 'legacy_lab_trial_invalid'
        expected = set(INPUTS) | {'camera_connection.json'} | {
            f'ptz_captures/main/preset_{i}.jpg' for i in range(1,10)
        }
        digests = record.get('files_sha256') or {}
        if set(digests) != expected:
            return 'legacy_lab_trial_missing_dependency_digest'
        for name, digest in digests.items():
            if (not isinstance(digest, str) or len(digest) != 64 or
                _sha(_path(root, name)) != digest):
                return 'legacy_lab_trial_dependency_changed'
    except (OSError, ValueError, KeyError):
        return 'legacy_lab_trial_missing_artifact'
    return None
