"""Phase 4A: active-only historical editor (never mutates live revision).

All mutation requires an existing editable working copy.  No raw environment
or credential JSON is returned to browser.  Geometry edits revoke old solve.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

PAIR = re.compile(r"^[1-9]-[1-9]$")
PHASES = frozenset({"train", "holdout"})
FIELDS = ("x_a_px", "y_a_px", "x_b_px", "y_b_px")


def geometry_digest(geometry):
    obj = {p: geometry.get(p, {}) for p in PHASES}
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def clean_mark(value, width, height):
    if not isinstance(value, dict):
        raise ValueError("mark_must_be_object")
    output = {}
    for key, maximum in (("x_a_px", width), ("y_a_px", height),
                         ("x_b_px", width), ("y_b_px", height)):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("invalid_mark_coordinate:" + key)
        number = float(item)
        if not math.isfinite(number) or number < 0 or number >= maximum:
            raise ValueError("mark_outside_frame:" + key)
        output[key] = number
    return output


def mutate_marks(state, payload, *, width, height):
    """Pure mutation helper; returns changed state. No false solver PASS."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    phase, pair, action = payload.get("phase"), payload.get("pair"), payload.get("action")
    if phase not in PHASES or not isinstance(pair, str) or not PAIR.fullmatch(pair):
        raise ValueError("invalid_phase_or_pair")
    a, b = map(int, pair.split("-"))
    if a == b:
        raise ValueError("pair_must_use_distinct_presets")
    if action not in {"add", "update", "delete"}:
        raise ValueError("unsupported_action")
    result = copy.deepcopy(state)
    geom = result.setdefault("geometry", {})
    phase_data = geom.setdefault(phase, {})
    marks = phase_data.setdefault(pair, [])
    if not isinstance(marks, list):
        raise ValueError("corrupt_mark_list")
    if action == "add":
        if len(marks) >= 30:
            raise ValueError("mark_limit_exceeded")
        marks.append(clean_mark(payload.get("mark"), width, height))
    else:
        index = payload.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(marks):
            raise ValueError("mark_index_out_of_range")
        if action == "update":
            marks[index] = {**marks[index], **clean_mark(payload.get("mark"), width, height)}
        else:
            marks.pop(index)
    # Any historical solver/evidence computed from earlier marks is invalid.
    geom.pop("solver_result", None)
    geom.pop("candidate", None)
    result["phase45_geometry_dirty"] = True
    result["phase45_edit_note"] = "Landmark changed: new geometry solve/validation required"
    return result


def _safe_read(path):
    try:
        if path.is_symlink():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _sanitized_overview(revision_dir):
    artifacts = revision_dir / "artifacts"
    camera = _safe_read(artifacts / "camera_connection.json")
    camera_env = camera.get("runtime_env") or {}
    intrinsics = _safe_read(artifacts / "camera_intrinsics.json")
    distance = _safe_read(artifacts / "distance_global.json")
    geometry = _safe_read(artifacts / "preset_rotation.json")
    site_file = _safe_read(artifacts / "site.json")
    telegram = _safe_read(artifacts / "telegram.json")
    tenv = telegram.get("runtime_env") or telegram
    legacy_inputs = {}
    for label in ("positive_train", "negative_train", "positive_holdout", "negative_holdout"):
        path = artifacts / "geometry_inputs" / (label + ".json")
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 150000:
            legacy_inputs[label] = _safe_read(path)
    return {
        "legacy_geometry_input_values": legacy_inputs,
        "camera": {
            "ip": camera_env.get("CAMERA_IP"),
            "http_port": camera_env.get("CAMERA_PORT"),
            "rtsp_port": camera_env.get("RTSP_PORT"),
            "rtsp_path": camera_env.get("RTSP_PATH"),
            "credentials_configured": bool(camera_env.get("CAMERA_PWD")),
        },
        "intrinsics": {k: intrinsics.get(k) for k in (
            "status", "frame_width", "frame_height", "fx_px", "fy_px", "cx_px", "cy_px", "valid_for_production")},
        "distance": {k: distance.get(k) for k in (
            "pixel_rmse", "min_distance_m", "max_distance_m", "points", "status")},
        "geometry": {
            "model": geometry.get("model"), "status": geometry.get("status"),
            "presets": len(geometry.get("presets") or {}),
            "holdout_passed": (geometry.get("independent_holdout_gate") or {}).get("passed"),
        },
        "site": {k: site_file.get(k) for k in (
            "north_offset_deg", "measured_preset1_bearing_deg", "hfov_deg", "frame_width", "frame_height")},
        "telegram": {"configured": bool(tenv.get("TELEGRAM_TOKEN") or tenv.get("telegram_token") or tenv.get("token")),
                     "chat_configured": bool(tenv.get("TELEGRAM_CHAT_ID") or tenv.get("telegram_chat_id") or tenv.get("chat_id"))},
    }


def snapshot():
    from manager.services.site_store import get_active_site
    from manager.services.site_registry import list_registered_sites
    from manager.services.revision_engine import REVISION_ROOT
    from manager.services.wizard_store import STATE_DIR
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity

    active = get_active_site() or {}
    site, rev = active.get("site_id"), active.get("revision_id")
    if not site or not rev:
        raise RuntimeError("no_active_runtime")
    if check_revision_source_integrity(site, rev).get("ok") is not True:
        raise RuntimeError("active_revision_integrity_failed")
    base = REVISION_ROOT / site / rev
    if base.is_symlink():
        raise RuntimeError("unsafe_revision_directory")
    record = (list_registered_sites().get("sites") or {}).get(site) or {}
    working = record.get("working_copy") or {}
    editable = (working.get("state") in {"EDITING", "CAMERA_CHANGED", "READY_FOR_VERIFICATION", "CAMERA_TEST_FAILED"}
                and working.get("parent_revision") == rev and not working.get("recovery"))
    if editable:
        state = _safe_read(STATE_DIR / (site + ".json"))
        source = "WORKING_COPY"
    else:
        state = _safe_read(base / "wizard_state.json")
        source = "ACTIVE_REVISION"
    geom = state.get("geometry") or {}
    marks = {p: geom.get(p) or {} for p in ("train", "holdout")}
    sanitized = {p: {k: v for k, v in source_marks.items() if PAIR.fullmatch(k) and isinstance(v, list)}
                 for p, source_marks in marks.items()}
    return {
        "ok": True, "site_id": site, "revision_id": rev,
        "editable": editable, "source": source,
        "working_state": working.get("state"),
        "geometry_dirty": bool(state.get("phase45_geometry_dirty")),
        "geometry_digest": geometry_digest(geom),
        "marks": sanitized,
        "overview": _sanitized_overview(base),
        "runtime_changed": False,
    }


def edit_marks(payload):
    from manager.services.site_store import get_active_site
    from manager.services.runtime_site_crud import _require_editable_working_copy, _audit
    from manager.services.wizard_store import CANDIDATE_DIR, load_state, STATE_DIR, save_state
    from manager.services.hardware_lock import hardware_lock
    active = get_active_site() or {}
    site = active.get("site_id")
    if not site or payload.get("site_id") != site or payload.get("revision_id") != active.get("revision_id"):
        raise PermissionError("ACTIVE_RUNTIME_IDENTITY_MISMATCH")
    with hardware_lock("phase45:geometry-mark-edit", timeout=3.0):
        # Protect against activation during edit and against inactive-site mutation.
        now = get_active_site() or {}
        if (now.get("site_id"), now.get("revision_id")) != (site, active.get("revision_id")):
            raise PermissionError("ACTIVE_RUNTIME_CHANGED")
        working = _require_editable_working_copy(site)
        if working.get("parent_revision") != active.get("revision_id") or working.get("recovery"):
            raise PermissionError("draft_parent_must_match_active_revision")
        candidate = CANDIDATE_DIR / site
        intrinsics = _safe_read(candidate / "camera_intrinsics.json")
        width, height = intrinsics.get("frame_width"), intrinsics.get("frame_height")
        if not (isinstance(width, int) and isinstance(height, int) and 100 <= width <= 10000 and 100 <= height <= 10000):
            raise RuntimeError("missing_camera_intrinsics_dimensions")
        state = load_state(site)
        digest = geometry_digest(state.get("geometry") or {})
        if payload.get("expected_digest") != digest:
            raise RuntimeError("DRAFT_CHANGED_REFRESH_REQUIRED")
        changed = mutate_marks(state, payload, width=width, height=height)
        save_state(site, changed)
        _audit("phase45_geometry_mark_edit", site_id=site, action_type=payload.get("action"),
               phase=payload.get("phase"), pair=payload.get("pair"), index=payload.get("index"))
        return {"ok": True, "new_digest": geometry_digest(changed.get("geometry") or {}),
                "geometry_dirty": True, "runtime_changed": False,
                "warning": "Geometry must be freshly solved and validated before publishing"}

def invalidate_geometry_state(state):
    """Revoke old derived geometry, including changes through legacy Wizard UI."""
    geom = state.setdefault('geometry', {})
    geom.pop('solver_result', None)
    geom.pop('candidate', None)
    state['phase45_geometry_dirty'] = True
    state['phase45_edit_note'] = 'Landmark changed: new geometry solve/validation required'
    return state
