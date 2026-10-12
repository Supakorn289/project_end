"""Per-revision, non-secret alert/fusion tunables.

This module deliberately excludes locked detection/model calibration parameters;
the installed frozen model contract controls those parameters. Mutations are
active-site working-copy only and cannot directly affect live Detection.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

DEFAULTS = {
    "ALERT_COOLDOWN_SEC": "30",
    "ALERT_DEDUP_IOU_THRESHOLD": "0.5",
    "FUSION_ANCHOR_MAX_AGE_SEC": "15",
    "FUSION_PENDING_SAFETY_SEC": "90",
}
RANGES = {
    "ALERT_COOLDOWN_SEC": (0.0, 3600.0),
    "ALERT_DEDUP_IOU_THRESHOLD": (0.0, 1.0),
    "FUSION_ANCHOR_MAX_AGE_SEC": (1.0, 120.0),
    "FUSION_PENDING_SAFETY_SEC": (1.0, 600.0),
}
FILENAME = "site_detection_settings.json"


def normalize(raw):
    """Strict, deterministic schema for API/editor, plan, and Agent."""
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise ValueError("site_settings_keys_must_match_schema")
    result = {}
    for key, bounds in RANGES.items():
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("invalid_site_setting_type:" + key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("invalid_site_setting:" + key) from None
        if not math.isfinite(number) or not bounds[0] <= number <= bounds[1]:
            raise ValueError("site_setting_out_of_range:" + key)
        result[key] = f"{number:.10g}"
    if float(result["FUSION_PENDING_SAFETY_SEC"]) < float(result["FUSION_ANCHOR_MAX_AGE_SEC"]):
        raise ValueError("pending_safety_must_be_at_least_anchor_age")
    return result


def resolve_artifact(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid_site_settings_artifact")
    return normalize(value.get("runtime_env"))


def _read_json(path):
    if path.is_symlink():
        raise RuntimeError("settings_symlink_rejected")
    if not path.is_file():
        return None
    if path.stat().st_size > 16384:
        raise RuntimeError("settings_file_too_large")
    value = json.loads(path.read_text(encoding="utf-8"))
    return resolve_artifact(value)


def digest(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _active_revision():
    from manager.services.site_store import get_active_site
    active = get_active_site() or {}
    site, revision = active.get("site_id"), active.get("revision_id")
    if not site or not revision:
        raise RuntimeError("no_active_revision")
    return site, revision


def snapshot():
    from manager.services.revision_engine import REVISION_ROOT
    from manager.services.wizard_store import CANDIDATE_DIR
    from manager.services.site_registry import list_registered_sites
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity
    site, rev = _active_revision()
    check_revision_source_integrity(site, rev)
    record = (list_registered_sites().get("sites") or {}).get(site) or {}
    working = record.get("working_copy") or {}
    editable = working.get("state") in {"EDITING", "READY_FOR_VERIFICATION", "CAMERA_CHANGED", "CAMERA_TEST_FAILED"} and working.get("parent_revision") == rev
    artifact = REVISION_ROOT / site / rev / "artifacts" / FILENAME
    source = "ACTIVE_REVISION" if artifact.is_file() else "BUILTIN_DEFAULTS"
    values = _read_json(artifact) if artifact.is_file() else dict(DEFAULTS)
    if editable:
        draft = CANDIDATE_DIR / site / FILENAME
        if draft.is_file():
            values = _read_json(draft)
            source = "WORKING_COPY"
    return {"ok": True, "site_id":site, "revision_id":rev, "editable":bool(editable),
            "working_state":working.get("state"), "source":source,
            "values":values, "expected_digest":digest(values),
            "locked_keys":["FIRE_THRESHOLD","SMOKE_THRESHOLD","CONSENSUS_IOU_THRESHOLD","FRAMES_PER_SCAN","MIN_CONFIRM_FRAMES"],
            "runtime_changed":False,
            "warning":"Values become active only after Final Verification, new immutable Revision, and Activation. Built-in defaults apply to older revisions missing this artifact."}


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError("settings_symlink_rejected")
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-draft-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(payload):
    from manager.services.runtime_site_crud import _require_editable_working_copy, _audit
    from manager.services.wizard_store import CANDIDATE_DIR
    from manager.services.hardware_lock import hardware_lock
    if not isinstance(payload, dict):
        raise ValueError("invalid_settings_payload")
    site, rev = _active_revision()
    if (payload.get("site_id"), payload.get("revision_id")) != (site, rev):
        raise PermissionError("active_site_identity_mismatch")
    desired = normalize(payload.get("values"))
    with hardware_lock("phase45:site-settings", timeout=3):
        if _active_revision() != (site, rev):
            raise PermissionError("active_site_changed")
        working = _require_editable_working_copy(site)
        if working.get("parent_revision") != rev or working.get("recovery"):
            raise PermissionError("active_revision_draft_required")
        path = CANDIDATE_DIR / site / FILENAME
        current = _read_json(path) if path.is_file() else dict(DEFAULTS)
        if payload.get("expected_digest") != digest(current):
            raise RuntimeError("draft_changed_refresh_required")
        artifact = {"schema_version":1,"runtime_env":desired,
                    "note":"Validated per-site non-secret tunables; applied only by revision activation"}
        data = (json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        _atomic_write(path,data)
        _audit("phase45_site_settings_update", site_id=site, revision_id=rev,
               changed_keys=sorted(k for k in DEFAULTS if desired[k] != current[k]))
    return {"ok":True,"site_id":site,"revision_id":rev,"values":desired,
            "expected_digest":digest(desired),"runtime_changed":False,
            "next":"final_verify_publish_activate"}
