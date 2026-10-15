from __future__ import annotations

import fcntl
import hashlib
import uuid
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from manager.services import site_registry
from manager.services.activation_plan import build_activation_plan
from manager.services.camera_setup import save_camera_candidate, test_camera_candidate
from manager.services.hardware_lock import hardware_lock
from manager.services.ops_agent import activate_revision
from manager.services.revision_engine import create_revision, list_revisions
from manager.services.site_store import get_active_site
from manager.services.wizard_store import (
    CANDIDATE_DIR,
    STATE_DIR,
    load_state,
    save_state,
)

PROJECT_ROOT = Path("/opt/smart-fire-detection-v2")
CALIBRATION_ROOT = PROJECT_ROOT / "calibration"
MANAGER_ROOT = CALIBRATION_ROOT / ".manager"
REVISION_ROOT = MANAGER_ROOT / "revisions"
DEPLOY_ROOT = CALIBRATION_ROOT / "sites"
TRASH_ROOT = MANAGER_ROOT / "trash"
RESTORE_MANIFEST = ".sf-trash-restore-v1.json"
RESTORE_ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,170}$")
AUDIT_DIR = MANAGER_ROOT / "audit"
AUDIT_FILE = AUDIT_DIR / "runtime_site_crud.jsonl"
AUDIT_LOCK = AUDIT_DIR / ".runtime_site_crud.lock"
REVISION_RE = re.compile(r"^rev-[A-Za-z0-9TZ._-]{8,100}$")
SECRET_ARTIFACTS = {"camera_connection.json", "telegram.json"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _audit(action: str, **fields) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_LOCK.touch(exist_ok=True)
    record = {"time": _now(), "action": action, **fields}
    with AUDIT_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with AUDIT_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _site_id(value) -> str:
    return site_registry._validate_site_id(value)


def _revision_id(value) -> str:
    value = str(value or "").strip()
    if not REVISION_RE.fullmatch(value):
        raise ValueError("invalid revision_id")
    return value


def _source_revision_dir(site_id: str, revision_id: str) -> Path:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    path = (REVISION_ROOT / site_id / revision_id).resolve()
    parent = (REVISION_ROOT / site_id).resolve()
    if path.parent != parent:
        raise ValueError("revision path escape")
    return path


def _deployment_revision_dir(site_id: str, revision_id: str) -> Path:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    path = (DEPLOY_ROOT / site_id / "revisions" / revision_id).resolve()
    parent = (DEPLOY_ROOT / site_id / "revisions").resolve()
    if path.parent != parent:
        raise ValueError("deployment path escape")
    return path


def _mask_user(username):
    text = str(username or "")
    if not text:
        return None
    if len(text) <= 2:
        return "••"
    return text[0] + "•••" + text[-1]


def _camera_summary(path: Path) -> dict:
    data = _read_json(path, {})
    env = data.get("runtime_env", {}) if isinstance(data, dict) else {}
    return {
        "configured": bool(env.get("CAMERA_IP")),
        "tested": bool(data.get("tested", False)) if isinstance(data, dict) else False,
        "camera_ip": env.get("CAMERA_IP"),
        "camera_port": env.get("CAMERA_PORT") or env.get("CAMERA_HTTP_PORT"),
        "camera_user_hint": _mask_user(env.get("CAMERA_USER")),
        "password_configured": bool(env.get("CAMERA_PWD")),
        "rtsp_port": env.get("RTSP_PORT"),
        "rtsp_path": env.get("RTSP_PATH"),
    }


def _geometry_summary(path: Path) -> dict:
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return {}
    status = data.get("status")
    override = data.get("operator_override", {}) or {}
    gate = data.get("independent_holdout_gate", {}) or {}
    return {
        "status": status,
        "forced": bool(
            override.get("enabled")
            or "FORCED" in str(status or "").upper()
        ),
        "holdout_passed": gate.get("passed"),
    }


def _active_identity() -> tuple[str | None, str | None]:
    active = get_active_site() or {}
    return active.get("site_id"), active.get("revision_id")


def _working_copy_info(
    site_id: str,
) -> dict:

    candidate = CANDIDATE_DIR / site_id
    camera = candidate / "camera_connection.json"

    registry = site_registry.list_registered_sites()

    record = (
        registry
        .get("sites", {})
        .get(site_id, {})
    )

    working = (
        record.get("working_copy", {})
        or {}
    )

    exists = bool(
        working
        and working.get("state") in {
            "EDITING", "CAMERA_CHANGED", "READY_FOR_VERIFICATION",
            "CAMERA_TEST_FAILED", "RECOVERY_EDITING", OFFLINE_CAMERA_STATE,
        }
    )

    return {
        "exists": exists,
        "candidate_exists": bool(candidate.exists() and any(candidate.iterdir())),
        "state": working.get("state"),
        "offline_only": working.get("offline_only") is True,
        "parent_revision": working.get("parent_revision"),
        "published_revision": working.get("published_revision"),
        "started_at": working.get("started_at"),
        "camera_test_required": working.get("camera_test_required"),
        "camera_test_passed": working.get("camera_test_passed"),
        "camera": (
            _camera_summary(camera)
            if exists and camera.exists()
            else {"configured": False}
        ),
    }

def _revision_entry(site_id: str, data: dict, active_site, active_revision) -> dict:
    revision_id = str(data.get("revision_id") or "")
    source = _source_revision_dir(site_id, revision_id)
    deployed = _deployment_revision_dir(site_id, revision_id)
    artifacts = source / "artifacts"
    camera_file = artifacts / "camera_connection.json"
    rotation_file = artifacts / "preset_rotation.json"
    is_active = site_id == active_site and revision_id == active_revision
    try:
        permission = revision_delete_preview(site_id, revision_id)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        permission = {"deletable": False, "blocked_reason": "revision_integrity_check_failed"}
    return {
        **data,
        "active": is_active,
        "deletable": permission["deletable"],
        "blocked_reason": permission["blocked_reason"],
        "source_exists": source.exists(),
        "deployment_exists": deployed.exists(),
        "camera": _camera_summary(camera_file) if camera_file.exists() else {"configured": False},
        "geometry": (
            {**_geometry_summary(rotation_file),
             "runtime_status": (
                 "FORCED_ACTIVE" if is_active and _geometry_summary(rotation_file).get("forced")
                 else "ACTIVE" if is_active else "INACTIVE"
             )}
            if rotation_file.exists() else {}
        ),
    }


def inventory() -> dict:
    registry = site_registry.list_registered_sites()
    registered = registry.get("sites", {}) or {}
    active_site, active_revision = _active_identity()
    site_ids = set(registered.keys())

    for root in (REVISION_ROOT, DEPLOY_ROOT):
        if root.exists():
            for path in root.iterdir():
                if path.is_dir():
                    site_ids.add(path.name)

    sites = []
    for site_id in sorted(site_ids):
        record = dict(registered.get(site_id, {}))
        revisions = []
        try:
            rows = list_revisions(site_id)
        except Exception:
            rows = []

        for row in rows:
            try:
                revisions.append(_revision_entry(site_id, row, active_site, active_revision))
            except Exception:
                continue

        known = {x.get("revision_id") for x in revisions}
        deploy_revisions = DEPLOY_ROOT / site_id / "revisions"
        if deploy_revisions.exists():
            for path in sorted(deploy_revisions.iterdir(), reverse=True):
                if not path.is_dir() or path.name in known:
                    continue
                active = site_id == active_site and path.name == active_revision
                try:
                    deletion = revision_delete_preview(site_id, path.name)
                except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                    deletion = {"deletable": False, "blocked_reason": "revision_integrity_check_failed"}
                revisions.append({
                    "revision_id": path.name,
                    "status": "DEPLOYED_ONLY",
                    "candidate_ready": False,
                    "active": active,
                    "deletable": deletion["deletable"],
                    "blocked_reason": deletion["blocked_reason"],
                    "source_exists": False,
                    "deployment_exists": True,
                    "camera": {"configured": False},
                    "geometry": {},
                })

        is_active = site_id == active_site
        try:
            deletion = site_delete_preview(site_id)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError):
            deletion = {"deletable": False, "blocked_reason": "site_integrity_check_failed"}
        sites.append({
            "site_id": site_id,
            "display_name": record.get("display_name") or site_id,
            "updated_at": record.get("updated_at"),
            "mode": record.get("mode") or "UNKNOWN",
            "lifecycle": record.get("lifecycle") or ("ACTIVE" if is_active else "UNREGISTERED"),
            "validation_state": record.get("validation_state"),
            "source": record.get("source"),
            "location": record.get("location", {}) or {},
            "components": record.get("components", {}) or {},
            "warnings": record.get("warnings", []) or [],
            "configuration_state": record.get("configuration_state", "CLEAN"),
            "active": is_active,
            "active_revision_id": active_revision if is_active else None,
            "deletable": deletion["deletable"],
            "blocked_reason": deletion["blocked_reason"],
            "site_id_mutable": False,
            "working_copy": _working_copy_info(site_id),
            "revisions": revisions,
        })

    return {
        "ok": True,
        "active_site": active_site,
        "active_revision": active_revision,
        "site_count": len(sites),
        "sites": sites,
        "delete_policy": "soft_delete_to_trash",
        "revision_policy": "immutable_create_new_revision_on_runtime_edit",
    }


def create_site_record(payload: dict) -> dict:
    record = site_registry.create_site(
        site_id=payload.get("site_id", ""),
        mode=payload.get("mode", "LAB"),
        display_name=payload.get("display_name"),
        installation_location=payload.get("installation_location"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
    )
    load_state(record["site_id"], record.get("mode", "LAB"))
    _audit("site_create", site_id=record["site_id"], mode=record.get("mode"))
    return {"ok": True, "site": record, "runtime_changed": False}


def _normalized_update(site_id: str, payload: dict) -> dict:
    site_id = _site_id(site_id)
    registry = site_registry.list_registered_sites()
    current = registry.get("sites", {}).get(site_id)
    if not current:
        raise KeyError("site not registered")

    result = {
        "site_id": site_id,
        "display_name": current.get("display_name") or site_id,
        "mode": current.get("mode", "LAB"),
        "location": dict(current.get("location", {}) or {}),
    }
    changed = []

    if "display_name" in payload:
        name = str(payload.get("display_name") or "").strip()
        if not name or len(name) > 120 or "\n" in name or "\r" in name:
            raise ValueError("display_name invalid")
        if name != result["display_name"]:
            changed.append("display_name")
        result["display_name"] = name

    if "mode" in payload:
        mode = site_registry._validate_mode(payload.get("mode"))
        if mode != result["mode"]:
            changed.append("mode")
        result["mode"] = mode

    if {"installation_location", "latitude", "longitude"} & payload.keys():
        previous = result["location"]
        location = site_registry._site_location(
            installation_location=payload.get(
                "installation_location",
                previous.get("installation_location"),
            ),
            latitude=payload.get("latitude", previous.get("latitude")),
            longitude=payload.get("longitude", previous.get("longitude")),
        )
        if (
            result["mode"] == "PRODUCTION"
            and (location.get("latitude") is None or location.get("longitude") is None)
        ):
            raise ValueError("PRODUCTION ต้องกำหนด Latitude / Longitude")
        if location.get("installation_location") != previous.get("installation_location"):
            changed.append("installation_location")
        if (
            location.get("latitude") != previous.get("latitude")
            or location.get("longitude") != previous.get("longitude")
        ):
            changed.append("coordinates")
        result["location"] = location

    result["changed"] = list(dict.fromkeys(changed))
    return result


def preview_site_update(site_id: str, payload: dict) -> dict:
    normalized = _normalized_update(site_id, payload)
    affected = []
    if "mode" in normalized["changed"]:
        affected += ["commissioning_requirements", "final_verification"]
    if "coordinates" in normalized["changed"]:
        affected += site_registry.INVALIDATION_RULES["site_location"]
    affected = list(dict.fromkeys(affected))
    warnings = []
    if affected:
        warnings += [
            "การเปลี่ยนค่านี้ไม่แก้ Active Revision เดิมโดยตรง",
            "ต้องตรวจ/สร้าง Revision ใหม่ก่อนนำค่าที่เปลี่ยนไปใช้จริง",
        ]
    elif "display_name" in normalized["changed"]:
        warnings.append("Display name เป็น metadata เท่านั้น ไม่กระทบ Runtime")
    return {
        "ok": True,
        "write_performed": False,
        "site_id": normalized["site_id"],
        "changed": normalized["changed"],
        "affected": affected,
        "risk": "HIGH" if affected else "LOW",
        "warnings": warnings,
        "runtime_changed": False,
    }


def update_site_record(site_id: str, payload: dict) -> dict:
    site_id = _site_id(site_id)
    from manager.services.site_lifecycle_v2 import _active, _registry
    source = REVISION_ROOT / site_id
    is_inactive_recorded = (
        site_id != _active()[0] and source.is_dir()
        and any(p.is_dir() for p in source.iterdir())
    )
    # A nonactive site with saved revisions cannot edit calibration/location.
    # Only its human-readable label is metadata and may be changed offline.
    if is_inactive_recorded:
        if set(payload) != {"display_name", "expected_updated_at"}:
            raise PermissionError("inactive_site_only_display_name_can_change")
        if not isinstance(payload.get("expected_updated_at"), str) or not payload["expected_updated_at"]:
            raise RuntimeError("site_registry_refresh_required")
        if source.is_symlink():
            raise PermissionError("unsafe_site_revision_path")
    normalized = _normalized_update(site_id, payload)
    preview = preview_site_update(site_id, payload)
    if is_inactive_recorded and (preview["risk"] != "LOW" or preview["affected"]):
        raise PermissionError("inactive_site_calibration_protected")
    if preview.get("risk") == "HIGH":
        record = site_registry.list_registered_sites().get("sites", {}).get(site_id, {})
        working = record.get("working_copy") or {}
        if working.get("state") not in {
            "EDITING", "CAMERA_CHANGED", "READY_FOR_VERIFICATION", "CAMERA_TEST_FAILED",
        }:
            raise PermissionError("High-risk Site metadata requires Active Working Copy")

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            raise KeyError("site not registered")
        expected_stamp = payload.get("expected_updated_at")
        if is_inactive_recorded or expected_stamp is not None:
            if (not isinstance(expected_stamp, str) or not expected_stamp
                    or expected_stamp != site.get("updated_at")):
                raise RuntimeError("site_registry_stale_reload_required")
        # Recheck while holding the registry write lock; activation may have
        # changed since the operator loaded the page.
        if is_inactive_recorded and site_id == _active()[0]:
            raise RuntimeError("site_activation_changed_reload_required")

        old_mode = site.get("mode", "LAB")
        new_mode = normalized["mode"]
        site["display_name"] = normalized["display_name"]
        site["mode"] = new_mode
        site["location"] = normalized["location"]
        components = site.get("components", {}) or {}

        if old_mode != new_mode:
            if new_mode == "PRODUCTION":
                for key in ("distance", "site_bearing", "gps"):
                    if components.get(key) in {None, "DEFERRED", "DISABLED", "UNKNOWN"}:
                        components[key] = "REQUIRED"
            else:
                if components.get("site_bearing") == "REQUIRED":
                    components["site_bearing"] = "DEFERRED"
                if components.get("gps") == "REQUIRED":
                    components["gps"] = "DISABLED"

        if "coordinates" in normalized["changed"]:
            for key in site_registry.INVALIDATION_RULES["site_location"]:
                components[key] = "REQUIRED_REVALIDATION"

        site["components"] = components
        if preview["affected"]:
            site["configuration_state"] = "PENDING_REVISION"
            site["pending_changes"] = {
                "changed": normalized["changed"],
                "affected": preview["affected"],
                "updated_at": _now(),
            }
        site["updated_at"] = _now()
        return dict(site)

    record = site_registry._with_registry(mutate)
    _audit(
        "site_update",
        site_id=site_id,
        changed=normalized["changed"],
        affected=preview["affected"],
    )
    return {"ok": True, "site": record, "preview": preview, "runtime_changed": False}


def revision_detail(site_id: str, revision_id: str) -> dict:
    source = _source_revision_dir(site_id, revision_id)
    if not source.exists():
        raise FileNotFoundError("revision not found")

    revision = _read_json(source / "revision.json", {})
    verification = _read_json(source / "final_verification.json", {})
    site_record = _read_json(source / "site_record.json", {})
    artifacts = source / "artifacts"
    camera_file = artifacts / "camera_connection.json"
    rotation_file = artifacts / "preset_rotation.json"
    active_site, active_revision = _active_identity()

    return {
        "ok": True,
        "site_id": site_id,
        "revision_id": revision_id,
        "active": site_id == active_site and revision_id == active_revision,
        "revision": revision,
        "site_record": {
            "display_name": site_record.get("display_name"),
            "mode": site_record.get("mode"),
            "location": site_record.get("location"),
        },
        "verification": {
            "candidate_ready": verification.get("candidate_ready"),
            "blocker_count": verification.get("blocker_count"),
            "warning_count": verification.get("warning_count"),
            "mode": verification.get("mode"),
        },
        "camera": _camera_summary(camera_file) if camera_file.exists() else {"configured": False},
        "geometry": _geometry_summary(rotation_file) if rotation_file.exists() else {},
        "immutable": True,
        "edit_policy": "create_working_copy_then_publish_new_revision",
    }


def _archive_existing_candidate(site_id: str) -> str | None:
    target = CANDIDATE_DIR / site_id
    if not target.exists() or not any(target.iterdir()):
        return None

    archive = TRASH_ROOT / "working-copies" / site_id / _stamp()
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(archive))
    return str(archive)


# STAGE_3C2C_OFFLINE_CAMERA_DRAFT: inactive-site edits never use the camera worker.
OFFLINE_CAMERA_STATE = "OFFLINE_CAMERA_DRAFT"


def _camera_digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("offline_camera_missing_or_unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_camera_atomic(path: Path, raw: bytes) -> None:
    if path.is_symlink() or not path.is_file():
        raise PermissionError("unsafe_offline_camera_file")
    fd, temporary = tempfile.mkstemp(prefix=".offline-camera-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Best effort directory persistence, without altering other files.
        dfd = os.open(str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_inactive_offline_copy(site_id: str, revision_id: str, expected_updated_at: str) -> dict:
    site_id, revision_id = _site_id(site_id), _revision_id(revision_id)
    if not isinstance(expected_updated_at, str) or not expected_updated_at:
        raise RuntimeError("site_registry_refresh_required")
    with hardware_lock("offline-copy:" + site_id, timeout=3.0):
        active_site, active_rev = _active_identity()
        if not active_site or not active_rev or site_id == active_site:
            raise PermissionError("offline_copy_requires_inactive_site")
        registry = site_registry.list_registered_sites()
        record = (registry.get("sites") or {}).get(site_id)
        if not isinstance(record, dict) or record.get("updated_at") != expected_updated_at:
            raise RuntimeError("site_registry_stale_reload_required")
        if record.get("working_copy"):
            raise RuntimeError("working_copy_exists_no_overwrite")
        candidate = CANDIDATE_DIR / site_id
        if candidate.exists() or candidate.is_symlink():
            raise RuntimeError("candidate_exists_no_overwrite_manual_review")
        source_path = REVISION_ROOT / site_id / revision_id
        if source_path.is_symlink() or (REVISION_ROOT / site_id).is_symlink():
            raise PermissionError("revision_source_symlink_denied")
        source = _source_revision_dir(site_id, revision_id)
        from manager.services.site_lifecycle_v2 import check_revision_source_integrity
        verified = check_revision_source_integrity(site_id, revision_id)
        if verified.get("ok") is not True:
            raise RuntimeError("revision_integrity_not_confirmed")
        artifacts = source / "artifacts"
        if not artifacts.is_dir() or artifacts.is_symlink():
            raise RuntimeError("revision_artifacts_unsafe")
        for p in artifacts.rglob("*"):
            if p.is_symlink() or (not p.is_file() and not p.is_dir()):
                raise PermissionError("unsafe_artifact_in_revision")
        if not (artifacts / "camera_connection.json").is_file():
            raise RuntimeError("revision_camera_missing")
        CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
        if CANDIDATE_DIR.is_symlink():
            raise PermissionError("candidate_root_symlink_denied")
        staging = CANDIDATE_DIR / (".offline-" + site_id + "-" + uuid.uuid4().hex)
        committed = False
        try:
            shutil.copytree(artifacts, staging, symlinks=False)
            for p in staging.rglob("*"):
                if p.is_file():
                    p.chmod(0o600 if p.name in SECRET_ARTIFACTS else 0o640)
            # Pin copied data to the immutable source before publishing it as Draft.
            for p in artifacts.rglob("*"):
                if p.is_file():
                    counterpart = staging / p.relative_to(artifacts)
                    if not counterpart.is_file() or hashlib.sha256(p.read_bytes()).digest() != hashlib.sha256(counterpart.read_bytes()).digest():
                        raise RuntimeError("offline_copy_digest_mismatch")
            if _active_identity() != (active_site, active_rev) or candidate.exists():
                raise RuntimeError("active_identity_or_candidate_changed")
            staging.rename(candidate)
            committed = True
            def mutate(reg):
                target = (reg.get("sites") or {}).get(site_id)
                if not target or target.get("updated_at") != expected_updated_at or target.get("working_copy"):
                    raise RuntimeError("site_registry_stale_reload_required")
                if _active_identity() != (active_site, active_rev):
                    raise RuntimeError("active_identity_changed")
                target["working_copy"] = {
                    "parent_revision": revision_id,
                    "state": OFFLINE_CAMERA_STATE,
                    "offline_only": True,
                    "camera_test_required": True,
                    "camera_test_passed": False,
                    "started_at": _now(),
                }
                target["configuration_state"] = "OFFLINE_EDITING_NOT_TESTED"
                target["updated_at"] = _now()
                return None
            site_registry._with_registry(mutate)
        except Exception:
            if committed:
                shutil.rmtree(candidate)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        _audit("offline_copy_create", site_id=site_id, parent_revision=revision_id)
        return {"ok": True, "site_id": site_id, "parent_revision": revision_id,
                "offline_only": True, "runtime_changed": False,
                "camera": _camera_summary(candidate / "camera_connection.json")}


def update_inactive_offline_camera(site_id: str, payload: dict) -> dict:
    site_id = _site_id(site_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid_camera_payload")
    stamp = payload.get("expected_updated_at")
    digest = payload.get("expected_camera_sha256")
    if not isinstance(stamp, str) or not stamp or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("offline_camera_refresh_required")
    with hardware_lock("offline-camera-update:" + site_id, timeout=3.0):
        active_site, active_rev = _active_identity()
        if not active_site or not active_rev or site_id == active_site:
            raise PermissionError("offline_camera_requires_inactive_site")
        record = (site_registry.list_registered_sites().get("sites") or {}).get(site_id) or {}
        working = record.get("working_copy") or {}
        if (record.get("updated_at") != stamp or working.get("state") != OFFLINE_CAMERA_STATE
                or working.get("offline_only") is not True):
            raise RuntimeError("offline_draft_changed_refresh_required")
        parent = _revision_id(working.get("parent_revision"))
        if not (REVISION_ROOT / site_id / parent).is_dir():
            raise RuntimeError("parent_revision_missing")
        path = CANDIDATE_DIR / site_id / "camera_connection.json"
        current_sha = _camera_digest(path)
        if current_sha != digest:
            raise RuntimeError("offline_camera_stale_digest")
        old = path.read_bytes()
        old_obj = json.loads(old)
        if not isinstance(old_obj, dict) or not isinstance(old_obj.get("runtime_env"), dict):
            raise ValueError("invalid_camera_candidate")
        env = old_obj["runtime_env"]
        from manager.services.camera_setup import validate_camera_settings
        def take(field, key, preserve_blank=False):
            if key not in payload or (preserve_blank and not payload[key]):
                return env.get(field)
            return payload[key]
        validated = validate_camera_settings(
            camera_ip=take("CAMERA_IP", "camera_ip"),
            camera_port=take("CAMERA_PORT", "camera_port"),
            camera_user=take("CAMERA_USER", "camera_user", preserve_blank=True),
            camera_password=take("CAMERA_PWD", "camera_password", preserve_blank=True),
            rtsp_port=take("RTSP_PORT", "rtsp_port"),
            rtsp_path=take("RTSP_PATH", "rtsp_path"),
        )
        if validated == env:
            return {"ok": True, "unchanged": True, "runtime_changed": False, "camera": _camera_summary(path)}
        next_value = {"version": 1, "status": "OFFLINE_DRAFT_UNTESTED", "tested": False,
                      "runtime_env": validated, "runtime_changed": False}
        raw = (json.dumps(next_value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if _active_identity() != (active_site, active_rev) or _camera_digest(path) != digest:
            raise RuntimeError("offline_camera_concurrent_change")
        _safe_camera_atomic(path, raw)
        try:
            def mutate(reg):
                target = (reg.get("sites") or {}).get(site_id)
                if not target or target.get("updated_at") != stamp:
                    raise RuntimeError("site_registry_stale_reload_required")
                w = target.get("working_copy") or {}
                if (w.get("state") != OFFLINE_CAMERA_STATE or w.get("offline_only") is not True
                        or w.get("parent_revision") != parent or _active_identity() != (active_site, active_rev)):
                    raise RuntimeError("offline_draft_or_active_identity_changed")
                w["camera_test_required"] = True
                w["camera_test_passed"] = False
                w["offline_settings_changed_at"] = _now()
                target["working_copy"] = w
                target["configuration_state"] = "OFFLINE_REQUIRES_COMMISSIONING"
                target["updated_at"] = _now()
            site_registry._with_registry(mutate)
        except Exception:
            _safe_camera_atomic(path, old)
            raise
        _audit("offline_camera_update", site_id=site_id, parent_revision=parent)
        return {"ok": True, "offline_only": True, "runtime_changed": False,
                "requires": ["camera_test", "intrinsics_review", "ptz_capture_review",
                             "distance_review", "geometry_review", "final_verification"],
                "camera": _camera_summary(path)}



# Stage 3C.2D: non-destructive evidence review for an inactive Offline Draft.
# It does not declare calibration valid, edit source evidence, or grant activation.
_OFFLINE_REVIEW_FILE = ".offline-calibration-review.json"


def _offline_review_context(site_id: str):
    site_id = _site_id(site_id)
    active = _active_identity()
    if not all(active) or site_id == active[0]:
        raise PermissionError("offline_review_requires_inactive_site")
    record = (site_registry.list_registered_sites().get("sites") or {}).get(site_id) or {}
    working = record.get("working_copy") or {}
    if working.get("offline_only") is not True or working.get("state") != OFFLINE_CAMERA_STATE:
        raise PermissionError("offline_review_requires_offline_draft")
    parent = _revision_id(working.get("parent_revision"))
    candidate = CANDIDATE_DIR / site_id
    if not candidate.is_dir() or candidate.is_symlink() or (CANDIDATE_DIR.is_symlink()):
        raise PermissionError("unsafe_offline_candidate")
    if not (REVISION_ROOT / site_id / parent).is_dir():
        raise RuntimeError("offline_parent_revision_missing")
    return active, record, working, candidate, parent


def _offline_review_inventory(site_id: str) -> dict:
    active, record, working, candidate, parent = _offline_review_context(site_id)
    # Only fixed paths are inspected. No untrusted paths from API parameters.
    intrinsics = candidate / "camera_intrinsics.json"
    geometry = candidate / "preset_rotation.json"
    camera = candidate / "camera_connection.json"
    entries = [("intrinsics_model", intrinsics), ("ptz_rotation_model", geometry)]
    for i in range(1, 10):
        entries.append((f"ptz_main_{i}", candidate / "ptz_captures" / "main" / f"preset_{i}.jpg"))
    captures = candidate / "intrinsics_workspace" / "captures"
    for directory in (candidate / "ptz_captures", candidate / "ptz_captures" / "main",
                      candidate / "intrinsics_workspace", captures):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise PermissionError("unsafe_calibration_evidence_directory")
    if captures.is_dir():
        for img in sorted(captures.iterdir()):
            if img.is_symlink():
                raise PermissionError("unsafe_intrinsics_capture_entry")
            if img.is_file() and re.fullmatch(r"calib_[0-9]{3}\.jpg", img.name):
                entries.append(("intrinsics_capture_" + img.stem, img))
    findings = []
    for key, path in entries:
        if path.is_symlink():
            raise PermissionError("unsafe_calibration_artifact")
        if not path.exists():
            findings.append({"key": key, "exists": False})
        elif path.is_file():
            raw = path.read_bytes()
            findings.append({"key": key, "exists": True, "bytes": len(raw),
                             "sha256": hashlib.sha256(raw).hexdigest()})
        else:
            raise PermissionError("unsafe_calibration_artifact_type")
    camera_sha = _camera_digest(camera)
    evidence_digest = hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()
    reviewfile = candidate / _OFFLINE_REVIEW_FILE
    if reviewfile.is_symlink():
        raise PermissionError("unsafe_review_manifest")
    review_raw = reviewfile.read_bytes() if reviewfile.is_file() else b""
    review = json.loads(review_raw) if review_raw else None
    if review is not None and not isinstance(review, dict):
        raise RuntimeError("offline_review_manifest_invalid")
    review_current = bool(review and review.get("camera_sha256") == camera_sha
                          and review.get("evidence_sha256") == evidence_digest
                          and review.get("parent_revision") == parent)
    return {"ok": True, "site_id": site_id, "parent_revision": parent,
            "offline_only": True, "runtime_changed": False,
            "expected_updated_at": record.get("updated_at"),
            "camera_sha256": camera_sha, "evidence_sha256": evidence_digest,
            "review_sha256": hashlib.sha256(review_raw).hexdigest(),
            "intrinsics_model_present": any(x["key"] == "intrinsics_model" and x["exists"] for x in findings),
            "ptz_model_present": any(x["key"] == "ptz_rotation_model" and x["exists"] for x in findings),
            "ptz_main_captures": sum(1 for x in findings if x["key"].startswith("ptz_main_") and x["exists"]),
            "intrinsics_captures": sum(1 for x in findings if x["key"].startswith("intrinsics_capture_") and x["exists"]),
            "evidence": findings, "review_current": review_current,
            "review": ({"intrinsics": review.get("intrinsics"), "ptz": review.get("ptz"),
                        "notes": review.get("notes", "")} if review_current else None),
            "requires_hardware_commissioning": True,
            "candidate_ready_for_activation": False}


def offline_calibration_review(site_id: str) -> dict:
    return _offline_review_inventory(site_id)


def save_offline_calibration_review(site_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("invalid_offline_review_payload")
    site_id = _site_id(site_id)
    if payload.get("confirm_site_id") != site_id:
        raise ValueError("offline_review_confirmation_mismatch")
    if payload.get("intrinsics") not in {"reference_only", "recapture_required"}:
        raise ValueError("invalid_intrinsics_review_decision")
    if payload.get("ptz") not in {"reference_only", "recapture_required"}:
        raise ValueError("invalid_ptz_review_decision")
    notes = payload.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 500 or any(ord(c) < 32 and c not in "\n\t" for c in notes):
        raise ValueError("invalid_review_notes")
    with hardware_lock("offline-calibration-review:" + site_id, timeout=3.0):
        current = _offline_review_inventory(site_id)
        for field in ("expected_updated_at", "camera_sha256", "evidence_sha256", "review_sha256"):
            if not isinstance(payload.get(field), str) or payload[field] != current[field]:
                raise RuntimeError("offline_review_stale_refresh_required:" + field)
        active_before = _active_identity()
        candidate = CANDIDATE_DIR / site_id
        data = {"schema_version": 1, "site_id": site_id, "parent_revision": current["parent_revision"],
                "camera_sha256": current["camera_sha256"], "evidence_sha256": current["evidence_sha256"],
                "intrinsics": payload["intrinsics"], "ptz": payload["ptz"],
                "notes": notes, "requires_hardware_commissioning": True,
                "saved_at": _now()}
        raw = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        path = candidate / _OFFLINE_REVIEW_FILE
        if path.exists() and not path.is_file() or path.is_symlink():
            raise PermissionError("unsafe_review_file")
        if _active_identity() != active_before:
            raise RuntimeError("active_identity_changed")
        fd, tmp = tempfile.mkstemp(prefix=".offline-review-", dir=str(candidate))
        try:
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(raw); f.flush(); os.fsync(f.fileno())
            if _offline_review_inventory(site_id)["review_sha256"] != payload["review_sha256"]:
                raise RuntimeError("offline_review_concurrent_write")
            if _active_identity() != active_before:
                raise RuntimeError("active_identity_changed")
            os.replace(tmp, path)
            dfd = os.open(str(candidate), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        _audit("offline_calibration_review_saved", site_id=site_id,
               parent_revision=current["parent_revision"], intrinsics=data["intrinsics"], ptz=data["ptz"])
        return {"ok": True, "offline_only": True, "runtime_changed": False,
                "review_saved": True, "requires_hardware_commissioning": True,
                "candidate_ready_for_activation": False}


def discard_inactive_offline_copy(site_id: str, expected_updated_at: str, confirm_site_id: str) -> dict:
    site_id = _site_id(site_id)
    if confirm_site_id != site_id:
        raise ValueError("offline_discard_confirmation_mismatch")
    if not isinstance(expected_updated_at, str) or not expected_updated_at:
        raise RuntimeError("offline_discard_refresh_required")
    with hardware_lock("offline-discard:" + site_id, timeout=3.0):
        active_site, active_rev = _active_identity()
        if not active_site or not active_rev or active_site == site_id:
            raise PermissionError("offline_discard_requires_inactive_site")
        reg = site_registry.list_registered_sites()
        current = (reg.get("sites") or {}).get(site_id) or {}
        working = current.get("working_copy") or {}
        if (current.get("updated_at") != expected_updated_at or
                working.get("state") != OFFLINE_CAMERA_STATE or working.get("offline_only") is not True):
            raise RuntimeError("offline_discard_stale_or_not_offline")
        candidate = CANDIDATE_DIR / site_id
        if not candidate.is_dir() or candidate.is_symlink():
            raise RuntimeError("offline_candidate_missing_or_unsafe")
        archive = TRASH_ROOT / "working-copies" / site_id / ("offline-" + _stamp() + "-" + uuid.uuid4().hex)
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            raise RuntimeError("offline_archive_collision")
        candidate.rename(archive)
        try:
            def mutate(registry):
                record = (registry.get("sites") or {}).get(site_id)
                if not record or record.get("updated_at") != expected_updated_at:
                    raise RuntimeError("offline_discard_registry_stale")
                check = record.get("working_copy") or {}
                if (check.get("state") != OFFLINE_CAMERA_STATE or check.get("offline_only") is not True or
                        _active_identity() != (active_site, active_rev)):
                    raise RuntimeError("offline_discard_identity_changed")
                record.pop("working_copy", None)
                record["configuration_state"] = "CLEAN"
                record["updated_at"] = _now()
            site_registry._with_registry(mutate)
        except Exception:
            archive.rename(candidate)
            raise
        _audit("offline_copy_discard", site_id=site_id, archive=str(archive))
        return {"ok": True, "site_id": site_id, "archived": True, "runtime_changed": False}


def create_working_copy(
    site_id: str,
    revision_id: str,
    *,
    overwrite=False,
    offline_only=False,
    expected_updated_at=None,
) -> dict:
    if offline_only is True:
        if overwrite:
            raise PermissionError("offline_copy_overwrite_forbidden")
        return create_inactive_offline_copy(site_id, revision_id, expected_updated_at)
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    from manager.services.site_lifecycle_v2 import _active
    if (site_id, revision_id) != _active():
        raise PermissionError("only_the_current_active_revision_can_be_edited")
    source = _source_revision_dir(site_id, revision_id)
    if not source.exists():
        raise FileNotFoundError("revision not found")

    artifacts = source / "artifacts"
    if not artifacts.is_dir():
        raise RuntimeError("revision artifacts missing")
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity
    check_revision_source_integrity(site_id, revision_id)
    if not (artifacts / "camera_connection.json").is_file():
        raise RuntimeError("revision camera config missing: use Setup Wizard")
    if site_id not in site_registry.list_registered_sites().get("sites", {}):
        raise KeyError("site not registered")

    candidate = CANDIDATE_DIR / site_id
    if candidate.exists() and any(candidate.iterdir()) and not overwrite:
        raise RuntimeError(
            "working_copy_exists: use overwrite=true after operator confirmation"
        )

    archived = None
    if candidate.exists() and any(candidate.iterdir()):
        archived = _archive_existing_candidate(site_id)

    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(artifacts, candidate)

    for path in candidate.rglob("*"):
        if not path.is_file():
            continue
        path.chmod(0o600 if path.name in SECRET_ARTIFACTS else 0o640)

    snapshot = source / "wizard_state.json"
    wizard_path = STATE_DIR / f"{site_id}.json"
    if wizard_path.exists():
        wizard_backup_dir = TRASH_ROOT / "wizard-backups" / site_id
        wizard_backup_dir.mkdir(parents=True, exist_ok=True)
        wizard_backup = wizard_backup_dir / f"{_stamp()}-{os.getpid()}.json"
        shutil.copy2(wizard_path, wizard_backup)
        wizard_backup.chmod(0o600)
    state = _read_json(snapshot, {}) if snapshot.exists() else load_state(site_id)
    state["draft_parent_revision"] = revision_id
    state["draft_started_at"] = _now()
    state["calibration_mode"] = False
    save_state(site_id, state)

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            raise KeyError("site not registered")
        site["working_copy"] = {
            "parent_revision": revision_id,
            "started_at": _now(),
            "state": "EDITING",
        }
        site["configuration_state"] = "EDITING_WORKING_COPY"
        site["updated_at"] = _now()
        return dict(site)

    site_registry._with_registry(mutate)
    _audit(
        "working_copy_create",
        site_id=site_id,
        parent_revision=revision_id,
        archived_previous=archived,
    )

    camera_file = candidate / "camera_connection.json"
    return {
        "ok": True,
        "site_id": site_id,
        "parent_revision": revision_id,
        "archived_previous": archived,
        "camera": _camera_summary(camera_file) if camera_file.exists() else {"configured": False},
        "runtime_changed": False,
        "warning": (
            "Immutable Revision เดิมไม่ถูกแก้ไข "
            "การเปลี่ยนค่าจะอยู่ใน Working Copy จนกว่าจะ Publish + Activate Revision ใหม่"
        ),
    }


def _require_editable_working_copy(site_id: str) -> dict:
    record = site_registry.list_registered_sites().get("sites", {}).get(site_id)
    if not record:
        raise KeyError("site not registered")
    working = record.get("working_copy") or {}
    if working.get("state") not in {
        "EDITING", "CAMERA_CHANGED", "READY_FOR_VERIFICATION",
        "CAMERA_TEST_FAILED", "RECOVERY_EDITING",
    }:
        raise RuntimeError("working_copy_not_editable: create a working copy first")
    from manager.services.site_lifecycle_v2 import _active
    if site_id != _active()[0] and not working.get("recovery"):
        raise PermissionError("inactive site draft is now read-only")
    return working


def get_working_copy_detail(site_id: str) -> dict:
    site_id = _site_id(site_id)
    record = (site_registry.list_registered_sites().get("sites") or {}).get(site_id) or {}
    working = record.get("working_copy") or {}
    if working.get("offline_only") is True and working.get("state") == OFFLINE_CAMERA_STATE:
        if site_id == _active_identity()[0]:
            raise PermissionError("offline_draft_now_active")
        camera = CANDIDATE_DIR / site_id / "camera_connection.json"
        return {"ok": True, "site_id": site_id, "parent_revision": working.get("parent_revision"),
                "state": OFFLINE_CAMERA_STATE, "offline_only": True,
                "expected_updated_at": record.get("updated_at"),
                "camera_sha256": _camera_digest(camera),
                "camera": _camera_summary(camera), "runtime_changed": False,
                "requires_hardware_commissioning": True}
    working = _require_editable_working_copy(site_id)
    camera = CANDIDATE_DIR / site_id / "camera_connection.json"
    return {
        "ok": True,
        "site_id": site_id,
        "parent_revision": working.get("parent_revision"),
        "state": working.get("state"),
        "camera_test_required": working.get("camera_test_required"),
        "camera_test_passed": working.get("camera_test_passed"),
        "camera": _camera_summary(camera) if camera.exists() else {"configured": False},
        "runtime_changed": False,
    }

def update_working_camera(site_id: str, payload: dict) -> dict:
    site_id = _site_id(site_id)
    record = (site_registry.list_registered_sites().get("sites") or {}).get(site_id) or {}
    working = record.get("working_copy") or {}
    if working.get("offline_only") is True or working.get("state") == OFFLINE_CAMERA_STATE:
        return update_inactive_offline_camera(site_id, payload)
    _require_editable_working_copy(site_id)
    candidate = CANDIDATE_DIR / site_id / "camera_connection.json"
    if not candidate.exists():
        raise RuntimeError("working copy camera configuration missing")

    current = _read_json(candidate, {})
    env = current.get("runtime_env", {}) or {}

    def choose(key, payload_key, *, preserve_blank=False):
        if payload_key not in payload:
            return env.get(key)
        value = payload.get(payload_key)
        if preserve_blank and (value is None or str(value) == ""):
            return env.get(key)
        return value

    previous_ip = env.get("CAMERA_IP")
    result = save_camera_candidate(
        site_id,
        camera_ip=choose("CAMERA_IP", "camera_ip"),
        camera_port=(
            choose("CAMERA_PORT", "camera_port")
            or env.get("CAMERA_HTTP_PORT")
        ),
        camera_user=choose("CAMERA_USER", "camera_user", preserve_blank=True),
        camera_password=choose("CAMERA_PWD", "camera_password", preserve_blank=True),
        rtsp_port=choose("RTSP_PORT", "rtsp_port"),
        rtsp_path=choose("RTSP_PATH", "rtsp_path"),
    )
    changed_ip = result.get("camera_ip") != previous_ip

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            raise KeyError("site not registered")
        working = site.get("working_copy", {}) or {}
        working.update({
            "state": "CAMERA_CHANGED",
            "camera_test_required": True,
            "camera_test_passed": False,
            "updated_at": _now(),
        })
        site["working_copy"] = working
        site["configuration_state"] = "PENDING_CAMERA_TEST"
        site["updated_at"] = _now()
        return None

    site_registry._with_registry(mutate)
    _audit(
        "working_copy_camera_update",
        site_id=site_id,
        camera_ip_changed=changed_ip,
        previous_camera_ip=previous_ip,
        current_camera_ip=result.get("camera_ip"),
    )

    return {
        "ok": True,
        "status": result,
        "invalidation": {
            "camera_ip": (
                site_registry.preview_invalidation("camera_ip")
                if changed_ip
                else None
            )
        },
        "runtime_changed": False,
        "requires": [
            "camera_test",
            "final_verification",
            "new_revision",
            "activation",
        ],
        "warnings": [
            "Active Runtime ยังไม่เปลี่ยนจนกว่าจะ Activate Revision ใหม่",
            "ถ้าเปลี่ยนเฉพาะ IP ของกล้องเดิม ให้ Test Camera/RTSP ใหม่; ถ้าเปลี่ยนตัวกล้อง เลนส์หรือตำแหน่งติดตั้ง ต้อง Recalibrate Intrinsics, Geometry และ Distance ตามผลกระทบ",
        ],
    }


def test_working_camera(site_id: str) -> dict:
    site_id = _site_id(site_id)
    _require_editable_working_copy(site_id)
    with hardware_lock(f"runtime-site-crud:camera-test:{site_id}", timeout=1.0):
        result = test_camera_candidate(site_id)

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            return None
        working = site.get("working_copy", {}) or {}
        passed = bool(result.get("ok"))
        working.update({
            "camera_test_passed": passed,
            "camera_test_required": not passed,
            "camera_tested_at": _now(),
            "state": "READY_FOR_VERIFICATION" if passed else "CAMERA_TEST_FAILED",
        })
        site["working_copy"] = working
        site["configuration_state"] = (
            "PENDING_REVISION" if passed else "CAMERA_TEST_FAILED"
        )
        site["updated_at"] = _now()
        return None

    site_registry._with_registry(mutate)
    _audit("working_copy_camera_test", site_id=site_id, ok=bool(result.get("ok")))
    return result


def publish_working_copy(site_id: str) -> dict:
    site_id = _site_id(site_id)
    # LAB_REPUBLISH_GUARD_V214: only repair a known validated, incomplete
    # immutable trial. All other PUBLISHED working copies remain read-only.
    from manager.services.legacy_geometry_lab import published_lab_repair_allowed
    source = site_registry.list_registered_sites().get('sites', {}).get(site_id) or {}
    published_repair = published_lab_repair_allowed(site_id, source.get('working_copy') or {})
    if published_repair:
        working = source['working_copy']
    else:
        working = _require_editable_working_copy(site_id)
    if working.get("camera_test_required") is True:
        raise RuntimeError("camera test required before publish")

    result = create_revision(site_id)
    if result.get("candidate_ready") is not True:
        return {
            **result,
            "published": False,
            "warning": (
                "Revision ถูกสร้างแต่ยังไม่ผ่าน Final Verification "
                "จึง Activate ไม่ได้"
            ),
        }

    revision_id = result.get("revision_id")
    if published_repair:
        from manager.services.legacy_geometry_lab import revision_lab_trial_guard
        from manager.services.revision_engine import REVISION_ROOT
        new_revision = REVISION_ROOT / site_id / revision_id
        if (result.get('existing') or result.get('status') != 'VALIDATED_CANDIDATE' or
            result.get('artifact_count') != 15 or
            revision_lab_trial_guard(new_revision, site_id, 'LAB', 'LAB') is not None):
            raise RuntimeError('legacy_trial_republish_postcheck_failed')

    def mutate(registry: dict):
        target = registry["sites"].get(site_id)
        if not target:
            return None
        working_copy = target.get("working_copy", {}) or {}
        working_copy.update({
            "state": "PUBLISHED",
            "published_revision": revision_id,
            "published_at": _now(),
        })
        target["working_copy"] = working_copy
        target["configuration_state"] = "REVISION_READY"
        target["updated_at"] = _now()
        return None

    site_registry._with_registry(mutate)
    _audit("working_copy_publish", site_id=site_id, revision_id=revision_id)
    return {**result, "published": True}


def discard_working_copy(site_id: str, *, expected_updated_at=None, confirm_site_id=None) -> dict:
    site_id = _site_id(site_id)
    record = (site_registry.list_registered_sites().get("sites") or {}).get(site_id) or {}
    working = record.get("working_copy") or {}
    if working.get("offline_only") is True or working.get("state") == OFFLINE_CAMERA_STATE:
        return discard_inactive_offline_copy(site_id, expected_updated_at, confirm_site_id)
    _require_editable_working_copy(site_id)
    candidate = CANDIDATE_DIR / site_id
    archived = None
    if candidate.exists() and any(candidate.iterdir()):
        archived = _archive_existing_candidate(site_id)

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            raise KeyError("site not registered")
        site.pop("working_copy", None)
        site["configuration_state"] = "CLEAN"
        site["updated_at"] = _now()
        return None

    site_registry._with_registry(mutate)
    _audit("working_copy_discard", site_id=site_id, archived=archived)
    return {"ok": True, "archived": archived, "runtime_changed": False}


def activate_site_revision(site_id: str, revision_id: str) -> dict:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    plan = build_activation_plan(site_id, revision_id)
    if not plan.get("activatable"):
        return {
            "ok": False,
            "plan": plan,
            "error": "revision_not_activatable",
        }

    result = activate_revision(site_id, revision_id)
    if result.get("ok") and hasattr(site_registry, "reconcile_active_runtime"):
        try:
            site_registry.reconcile_active_runtime()
        except Exception:
            pass

    _audit(
        "revision_activate",
        site_id=site_id,
        revision_id=revision_id,
        ok=bool(result.get("ok")),
    )
    return {**result, "plan": plan}


def _runtime_pointer_guards() -> tuple[set[str], set[tuple[str, str]], bool]:
    """Return (protected sites, protected revisions, uncertain state)."""
    files = (
        CALIBRATION_ROOT / "preset_rotation_ACTIVE.json",
        CALIBRATION_ROOT / "camera_intrinsics.json",
        CALIBRATION_ROOT / "distance_global.json",
        CALIBRATION_ROOT / "site.json",
    )
    sites: set[str] = set()
    revisions: set[tuple[str, str]] = set()
    uncertain = False
    for file in files:
        if not file.is_symlink():
            if file.exists():
                # An old regular runtime file is not an active revision pointer.
                continue
            # Missing required active pointer: do not delete managed calibration.
            uncertain = True
            continue
        if not file.exists():
            uncertain = True
            continue
        resolved = file.resolve()
        try:
            parts = resolved.relative_to(DEPLOY_ROOT.resolve()).parts
        except ValueError:
            uncertain = True
            continue
        if parts:
            sites.add(parts[0])
        if len(parts) >= 4 and parts[1] == "revisions":
            revisions.add((parts[0], parts[2]))
    active_site, active_revision = _active_identity()
    if active_site:
        sites.add(active_site)
        if active_revision:
            revisions.add((active_site, active_revision))
    elif sites or revisions:
        uncertain = True
    return sites, revisions, uncertain


# Stage 3E: Never remove a saved version while any live draft or history
# still refers to it.  The active runtime pointer is NOT the only reference.
def _strict_delete_registry() -> dict:
    path = site_registry.REGISTRY_FILE
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("site_registry_unavailable")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("site_registry_unreadable") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sites"), dict):
        raise RuntimeError("site_registry_invalid")
    return raw["sites"]


def _strict_delete_wizard(site_id: str) -> dict:
    path = STATE_DIR / f"{site_id}.json"
    if path.is_symlink():
        raise RuntimeError("wizard_state_unsafe")
    if not path.exists():
        return {}
    if not path.is_file():
        raise RuntimeError("wizard_state_unsafe")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("wizard_state_unreadable") from exc
    if not isinstance(state, dict):
        raise RuntimeError("wizard_state_invalid")
    return state


def _revision_reference_reasons(site_id: str, revision_id: str) -> list[str]:
    reasons: list[str] = []
    record = _strict_delete_registry().get(site_id, {}) or {}
    if not isinstance(record, dict):
        raise RuntimeError("site_registry_record_invalid")
    working = record.get("working_copy") or {}
    if not isinstance(working, dict):
        raise RuntimeError("working_copy_invalid")
    if working.get("parent_revision") == revision_id:
        reasons.append("working_copy_parent")
    if working.get("published_revision") == revision_id:
        reasons.append("published_revision")
    # Defensive compatibility with historic lifecycle versions.
    for key in ("active_revision_id", "last_published_revision", "last_revision_id"):
        if record.get(key) == revision_id:
            reasons.append("site_registry_" + key)
    state = _strict_delete_wizard(site_id)
    if state.get("draft_parent_revision") == revision_id:
        reasons.append("wizard_draft_parent")
    latest = state.get("latest_revision") or {}
    if not isinstance(latest, dict):
        raise RuntimeError("wizard_latest_invalid")
    if latest.get("revision_id") == revision_id:
        reasons.append("wizard_latest_revision")
    # Historical marks belong to a specific source revision: do not orphan them.
    draft = MANAGER_ROOT / "legacy-mark-drafts" / site_id / revision_id
    if draft.exists() or draft.is_symlink():
        reasons.append("historical_landmark_draft")
    return list(dict.fromkeys(reasons))


def revision_delete_preview(site_id: str, revision_id: str) -> dict:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    active_site, active_revision = _active_identity()
    _, protected_revisions, uncertain = _runtime_pointer_guards()
    active = (site_id, revision_id) in protected_revisions or (
        site_id == active_site and revision_id == active_revision
    )
    source = _source_revision_dir(site_id, revision_id)
    deployed = _deployment_revision_dir(site_id, revision_id)
    exists = source.exists() or deployed.exists()
    reasons = []
    if not exists:
        reasons.append("revision_not_found")
    if active:
        reasons.append("active_revision")
    if uncertain:
        reasons.append("runtime_pointers_uncertain")
    try:
        reasons.extend(_revision_reference_reasons(site_id, revision_id))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        reasons.append("revision_reference_check_failed")
    if (REVISION_ROOT / site_id / revision_id).is_symlink() or (
        DEPLOY_ROOT / site_id / "revisions" / revision_id
    ).is_symlink():
        reasons.append("unsafe_revision_path")
    if deployed.exists() and not os.access(deployed.parent, os.W_OK):
        reasons.append("deployment_requires_privileged_cleanup")
    reasons = list(dict.fromkeys(reasons))
    return {
        "ok": True,
        "site_id": site_id,
        "revision_id": revision_id,
        "exists": bool(exists),
        "active": active,
        "deletable": not reasons,
        "blocked_reason": reasons[0] if reasons else None,
        "blocked_reasons": reasons,
        "source_exists": source.exists(),
        "deployment_exists": deployed.exists(),
        "delete_mode": "MOVE_TO_TRASH",
        "confirm_value": revision_id,
        "warnings": [
            "ไฟล์จะถูกย้ายไปถังเก็บสำรอง (Trash) ไม่ลบถาวร",
            "การลบไม่เปลี่ยนระบบตรวจจับที่กำลังทำงาน",
        ],
        "runtime_changed": False,
    }


def delete_revision(site_id: str, revision_id: str, confirm_value: str) -> dict:
    with hardware_lock(f"delete-revision:{site_id}:{revision_id}", timeout=2.0):
        return _delete_revision_locked(site_id, revision_id, confirm_value)


def _delete_revision_locked(site_id: str, revision_id: str, confirm_value: str) -> dict:
    preview = revision_delete_preview(site_id, revision_id)
    if confirm_value != revision_id:
        raise ValueError("confirmation mismatch")
    if not preview.get("deletable"):
        raise RuntimeError("revision is active or not found")

    source = _source_revision_dir(site_id, revision_id)
    deployed = _deployment_revision_dir(site_id, revision_id)
    trash = (
        TRASH_ROOT
        / "revisions"
        / site_id
        / f"{_stamp()}-{uuid.uuid4().hex[:8]}-{revision_id}"
    )
    trash.mkdir(parents=True, exist_ok=False, mode=0o700)
    moved = []

    try:
        if source.exists():
            destination = trash / "source"
            shutil.move(str(source), str(destination))
            moved.append((destination, source))

        if deployed.exists():
            destination = trash / "deployment"
            shutil.move(str(deployed), str(destination))
            moved.append((destination, deployed))
        _seal_deleted(trash, "revision", site_id, revision_id)

    except Exception:
        for src, dst in reversed(moved):
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        raise

    try:
        state = load_state(site_id)
        latest = state.get("latest_revision", {}) or {}
        if latest.get("revision_id") == revision_id:
            state["latest_revision_deleted"] = latest
            state.pop("latest_revision", None)
            save_state(site_id, state)
    except Exception:
        pass

    _audit(
        "revision_delete",
        site_id=site_id,
        revision_id=revision_id,
        trash=str(trash),
    )
    return {
        "ok": True,
        "site_id": site_id,
        "revision_id": revision_id,
        "trash": str(trash),
        "runtime_changed": False,
    }


def site_delete_preview(site_id: str) -> dict:
    site_id = _site_id(site_id)
    active_site, _ = _active_identity()
    protected_sites, _, uncertain = _runtime_pointer_guards()
    active = site_id == active_site or site_id in protected_sites
    registry_valid = True
    try:
        _strict_delete_registry()
        _strict_delete_wizard(site_id)
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        registry_valid = False
    registry = site_registry.list_registered_sites()
    registered = site_id in (registry.get("sites", {}) or {})
    revisions = REVISION_ROOT / site_id
    deployed = DEPLOY_ROOT / site_id
    candidate = CANDIDATE_DIR / site_id
    wizard = STATE_DIR / f"{site_id}.json"
    historical = MANAGER_ROOT / "legacy-mark-drafts" / site_id
    unsafe_paths = any(path.is_symlink() for path in (revisions, deployed, candidate, wizard, historical))
    exists = (
        registered
        or revisions.exists()
        or deployed.exists()
        or candidate.exists()
        or wizard.exists()
    )

    revision_count = 0
    if revisions.exists():
        revision_count = len([
            x for x in revisions.iterdir()
            if x.is_dir()
        ])

    return {
        "ok": True,
        "site_id": site_id,
        "exists": bool(exists),
        "active": active,
        "deletable": bool(
            exists and registered and not active and not uncertain and registry_valid and not unsafe_paths and
            (not deployed.exists() or os.access(deployed.parent, os.W_OK))
        ),
        "blocked_reason": (
            "active_site" if active else
            "runtime_pointers_uncertain" if uncertain else
            "site_registry_or_wizard_invalid" if not registry_valid else
            "site_unregistered_restore_unavailable" if not registered else
            "site_path_unsafe" if unsafe_paths else
            "deployment_requires_privileged_cleanup"
            if deployed.exists() and not os.access(deployed.parent, os.W_OK) else None
        ),
        "revision_count": revision_count,
        "has_candidate": candidate.exists(),
        "has_historical_draft": historical.exists(),
        "has_deployment": deployed.exists(),
        "delete_mode": "MOVE_TO_TRASH",
        "confirm_value": site_id,
        "warnings": (
            ["Active Site ห้ามลบ ต้อง Activate Site/Revision อื่นก่อน"]
            if active
            else [
                "Site, Candidate, Revisions และ Deployment จะถูกย้ายไป Trash",
                "Activation/Audit history จะคงไว้เพื่อการตรวจสอบย้อนหลัง",
            ]
        ),
        "runtime_changed": False,
    }


def delete_site(site_id: str, confirm_value: str) -> dict:
    with hardware_lock(f"delete-site:{site_id}", timeout=2.0):
        return _delete_site_locked(site_id, confirm_value)


def _delete_site_locked(site_id: str, confirm_value: str) -> dict:
    site_id = _site_id(site_id)
    preview = site_delete_preview(site_id)
    if confirm_value != site_id:
        raise ValueError("confirmation mismatch")
    if not preview.get("deletable"):
        raise RuntimeError("site is active or not found")

    trash = TRASH_ROOT / "sites" / f"{_stamp()}-{uuid.uuid4().hex[:8]}-{site_id}"
    registry_record = _strict_delete_registry().get(site_id)
    if not isinstance(registry_record, dict) or registry_record.get("site_id") != site_id:
        raise RuntimeError("site_registry_snapshot_invalid")
    trash.mkdir(parents=True, exist_ok=False, mode=0o700)
    paths = [
        (REVISION_ROOT / site_id, trash / "revisions"),
        (DEPLOY_ROOT / site_id, trash / "deployment"),
        (CANDIDATE_DIR / site_id, trash / "candidate"),
        (STATE_DIR / f"{site_id}.json", trash / "wizard_state.json"),
        (MANAGER_ROOT / "legacy-mark-drafts" / site_id, trash / "historical_landmark_drafts"),
    ]
    moved = []

    try:
        for source, destination in paths:
            if not source.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((destination, source))
        _seal_deleted(trash, "site", site_id, registry_record=registry_record)

        def mutate(registry: dict):
            registry["sites"].pop(site_id, None)
            return None

        site_registry._with_registry(mutate)

    except Exception:
        for source, destination in reversed(moved):
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
        raise

    _audit("site_delete", site_id=site_id, trash=str(trash))
    return {
        "ok": True,
        "site_id": site_id,
        "trash": str(trash),
        "runtime_changed": False,
    }


# Stage 3E.1: Restore uses ONLY archived, checksum-sealed evidence. A missing
# manifest (historic trash) must never be guessed into a live Site/Revision.
def _archive_files(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("restore_archive_unsafe")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("restore_archive_symlink")
        if path.is_file():
            if path.name == RESTORE_MANIFEST and path.parent == root:
                continue
            rel = path.relative_to(root).as_posix()
            if len(rel) > 500 or len(result) > 50000:
                raise RuntimeError("restore_archive_too_large")
            h = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(block)
            result[rel] = h.hexdigest()
        elif not path.is_dir():
            raise RuntimeError("restore_archive_not_regular")
    return result


def _seal_deleted(root: Path, kind: str, site_id: str,
                  revision_id: str | None = None, registry_record: dict | None = None):
    path = root / RESTORE_MANIFEST
    if path.exists() or path.is_symlink():
        raise RuntimeError("restore_manifest_exists")
    files = _archive_files(root)
    required = "source/revision.json" if kind == "revision" else None
    if (not files or (required and required not in files) or
        (kind == "site" and registry_record is None)):
        raise RuntimeError("restore_archive_incomplete")
    record = {
        "schema": 1, "kind": kind, "site_id": site_id,
        "revision_id": revision_id, "files": files,
        "registry_record": registry_record if kind == "site" else None,
    }
    with path.open("x", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(record, handle, ensure_ascii=False, sort_keys=True)
        handle.flush(); os.fsync(handle.fileno())


def _archive_directory(kind: str, site_id: str, archive_id: str) -> Path:
    if kind not in ("revision", "site"):
        raise ValueError("restore_invalid_type")
    site_id = _site_id(site_id)
    if not RESTORE_ARCHIVE_RE.fullmatch(str(archive_id)):
        raise ValueError("restore_invalid_archive_id")
    if kind == "revision":
        root = TRASH_ROOT / "revisions" / site_id / archive_id
    else:
        root = TRASH_ROOT / "sites" / archive_id
    # Reject symlinks on every archive ancestor, including Trash itself.
    cur = TRASH_ROOT
    for part in root.relative_to(TRASH_ROOT).parts:
        if cur.is_symlink():
            raise RuntimeError("restore_archive_symlink")
        cur = cur / part
    if cur.is_symlink() or not cur.is_dir():
        raise RuntimeError("restore_archive_missing_or_unsafe")
    return root


def _restore_destinations(kind: str, site_id: str, revision_id=None):
    if kind == "revision":
        return {
            "source": _source_revision_dir(site_id, revision_id),
            "deployment": _deployment_revision_dir(site_id, revision_id),
        }
    return {
        "revisions": REVISION_ROOT / site_id,
        "deployment": DEPLOY_ROOT / site_id,
        "candidate": CANDIDATE_DIR / site_id,
        "wizard_state.json": STATE_DIR / f"{site_id}.json",
        "historical_landmark_drafts": MANAGER_ROOT / "legacy-mark-drafts" / site_id,
    }


def _restore_guard(kind: str, site_id: str, archive_id: str) -> dict:
    site_id = _site_id(site_id)
    root = _archive_directory(kind, site_id, archive_id)
    mf = root / RESTORE_MANIFEST
    if not mf.is_file() or mf.is_symlink():
        raise RuntimeError("restore_manifest_missing_legacy_trash_manual_review")
    try:
        record = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("restore_manifest_invalid") from exc
    if (not isinstance(record, dict) or record.get("schema") != 1 or
        record.get("kind") != kind or record.get("site_id") != site_id or
        not isinstance(record.get("files"), dict)):
        raise RuntimeError("restore_manifest_identity_mismatch")
    revision_id = record.get("revision_id")
    if kind == "revision":
        revision_id = _revision_id(revision_id)
        if not str(archive_id).endswith("-" + revision_id):
            raise RuntimeError("restore_archive_name_mismatch")
    else:
        if revision_id is not None or not str(archive_id).endswith("-" + site_id):
            raise RuntimeError("restore_archive_name_mismatch")
        site_record = record.get("registry_record")
        if not isinstance(site_record, dict) or site_record.get("site_id") != site_id:
            raise RuntimeError("restore_registry_snapshot_invalid")
    actual = _archive_files(root)
    if actual != record["files"]:
        raise RuntimeError("restore_archive_integrity_mismatch")
    expected_roots = {"source", "deployment"} if kind == "revision" else {
        "revisions", "deployment", "candidate", "wizard_state.json", "historical_landmark_drafts"}
    if not actual or any(Path(name).parts[0] not in expected_roots for name in actual):
        raise RuntimeError("restore_archive_unexpected_contents")
    if kind == "revision":
        if "source/revision.json" not in actual:
            raise RuntimeError("restore_revision_metadata_missing")
        revmeta = json.loads((root / "source/revision.json").read_text(encoding="utf-8"))
        if revmeta.get("site_id") != site_id or revmeta.get("revision_id") != revision_id:
            raise RuntimeError("restore_revision_identity_mismatch")
    protected_sites, protected_revisions, uncertain = _runtime_pointer_guards()
    if uncertain:
        raise RuntimeError("restore_runtime_pointers_uncertain")
    active_site, active_revision = _active_identity()
    if kind == "site" and (site_id == active_site or site_id in protected_sites):
        raise RuntimeError("restore_site_active_conflict")
    if kind == "revision" and (site_id, revision_id) in protected_revisions:
        raise RuntimeError("restore_revision_active_conflict")
    sites = _strict_delete_registry()
    if kind == "revision" and site_id not in sites:
        raise RuntimeError("restore_parent_site_missing")
    if kind == "site" and site_id in sites:
        raise RuntimeError("restore_site_already_registered")
    targets = _restore_destinations(kind, site_id, revision_id)
    for name, target in targets.items():
        # Refuse any symlink in the destination's existing parent hierarchy.
        parent = target.parent
        while parent != parent.parent:
            if parent.is_symlink():
                raise RuntimeError("restore_destination_parent_symlink")
            parent = parent.parent
        if target.exists() or target.is_symlink():
            raise RuntimeError("restore_destination_exists:" + name)
        if (root / name).is_symlink():
            raise RuntimeError("restore_archive_symlink")
    proof = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "ok": True, "kind": kind, "site_id": site_id,
        "revision_id": revision_id, "archive_id": archive_id,
        "file_count": len(actual), "proof": proof,
        "restorable": True, "runtime_changed": False,
    }


def trash_restore_preview(kind: str, site_id: str, archive_id: str) -> dict:
    return _restore_guard(kind, site_id, archive_id)


def list_restorable_trash() -> dict:
    rows = []
    for kind, base in (("site", TRASH_ROOT / "sites"), ("revision", TRASH_ROOT / "revisions")):
        if base.is_symlink():
            raise RuntimeError("restore_trash_root_unsafe")
        if not base.exists():
            continue
        groups = [base] if kind == "site" else [p for p in base.iterdir() if p.is_dir() and not p.is_symlink()]
        for group in groups:
            if group.is_symlink():
                raise RuntimeError("restore_trash_group_unsafe")
            for root in sorted(group.iterdir()):
                if not root.is_dir() or root.is_symlink():
                    continue
                mf = root / RESTORE_MANIFEST
                if not mf.is_file() or mf.is_symlink():
                    continue  # Existing historic trash is preserved but not blindly restored.
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    site_id = _site_id(data.get("site_id"))
                    if kind == "revision" and group.name != site_id:
                        raise RuntimeError("restore_archive_wrong_site_folder")
                    checked = _restore_guard(kind, site_id, root.name)
                    rows.append(checked)
                except Exception:
                    # Fail closed per item: do not expose a restore action.
                    rows.append({"ok": True, "kind": kind, "archive_id": root.name,
                                 "restorable": False, "blocked_reason": "restore_requires_review"})
                if len(rows) > 2000:
                    raise RuntimeError("restore_archive_limit_exceeded")
    return {"ok": True, "items": rows, "runtime_changed": False}


def restore_from_trash(kind: str, site_id: str, archive_id: str,
                       confirm_value: str, expected_proof: str) -> dict:
    kind, site_id = str(kind), _site_id(site_id)
    with hardware_lock("restore-trash:" + kind + ":" + site_id, timeout=2.0):
        preview = _restore_guard(kind, site_id, archive_id)
        identity = preview["revision_id"] if kind == "revision" else site_id
        if (confirm_value != identity or expected_proof != preview["proof"]):
            raise RuntimeError("restore_confirmation_or_version_mismatch")
        root = _archive_directory(kind, site_id, archive_id)
        targets = _restore_destinations(kind, site_id, preview["revision_id"])
        registry_record = None
        if kind == "site":
            registry_record = json.loads((root / RESTORE_MANIFEST).read_text(encoding="utf-8"))["registry_record"]
        moved = []
        try:
            for name, dest in targets.items():
                src = root / name
                if src.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists() or dest.is_symlink():
                        raise RuntimeError("restore_destination_collision")
                    os.rename(src, dest)
                    moved.append((dest, src))
            if kind == "site":
                def register(registry):
                    if site_id in registry["sites"]:
                        raise RuntimeError("restore_site_registry_collision")
                    registry["sites"][site_id] = registry_record
                site_registry._with_registry(register)
        except Exception:
            for dest, src in reversed(moved):
                if dest.exists():
                    os.rename(dest, src)
            raise
        _audit("trash_restore", kind=kind, site_id=site_id,
               revision_id=preview["revision_id"], archive_id=archive_id)
        # Restored data now lives at its canonical paths; do not offer stale Trash action.
        try:
            (root / RESTORE_MANIFEST).unlink()
            root.rmdir()
        except OSError:
            pass
        return {"ok": True, "kind": kind, "site_id": site_id,
                "revision_id": preview["revision_id"], "archive_id": archive_id,
                "runtime_changed": False}


# STAGE2B_PUBLISHED_RESUME: permit a new editable draft only when the
# published Candidate is an exact byte-identical copy of the immutable
# published revision and differs from the ACTIVE baseline only in approved
# non-secret per-site settings. No file copy/delete or runtime write.
def _resume_published_evidence(site_id: str, revision_id: str) -> dict:
    import hashlib
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity
    from manager.services.site_settings_v24 import resolve_artifact, FILENAME as SETTINGS

    site_id, revision_id = _site_id(site_id), _revision_id(revision_id)
    active = _active_identity()
    if active != (site_id, revision_id):
        raise PermissionError('active_revision_changed_refresh_required')
    row = site_registry.list_registered_sites().get('sites', {}).get(site_id)
    if not row or str(row.get('mode') or '').upper() != 'LAB':
        raise PermissionError('published_resume_supported_for_validated_lab_only')
    work = row.get('working_copy') or {}
    if work.get('state') != 'PUBLISHED' or work.get('parent_revision') != revision_id or work.get('recovery'):
        raise RuntimeError('published_active_parent_required')
    pub = _revision_id(work.get('published_revision'))
    if pub == revision_id:
        raise RuntimeError('no_newer_published_revision')
    for rid in (revision_id, pub):
        if check_revision_source_integrity(site_id, rid).get('ok') is not True:
            raise RuntimeError('source_revision_integrity_failed')
    old = _source_revision_dir(site_id, revision_id)
    newer = _source_revision_dir(site_id, pub)
    pub_meta = _read_json(newer / 'revision.json')
    if (pub_meta.get('site_id'), pub_meta.get('revision_id')) != (site_id, pub):
        raise RuntimeError('published_revision_identity_mismatch')
    if pub_meta.get('status') != 'VALIDATED_CANDIDATE' or pub_meta.get('candidate_ready') is not True:
        raise RuntimeError('published_revision_not_validated')
    candidate = CANDIDATE_DIR / site_id
    if candidate.is_symlink() or not candidate.is_dir():
        raise RuntimeError('candidate_missing_or_symlink')
    def hashes(root):
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError('unsafe_artifact_root')
        result = {}
        for path in root.rglob('*'):
            if path.is_symlink():
                raise RuntimeError('unsafe_artifact_symlink')
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if not rel or '..' in Path(rel).parts or len(rel)>240:
                    raise RuntimeError('unsafe_artifact_path')
                h = hashlib.sha256()
                with path.open('rb') as handle:
                    for block in iter(lambda: handle.read(1024*1024), b''):
                        h.update(block)
                result[rel]=h.hexdigest()
        return result
    base_hash = hashes(old / 'artifacts')
    pub_hash = hashes(newer / 'artifacts')
    current_hash = hashes(candidate)
    # Source integrity checks manifest entries; also reject unmanifested extras.
    for revision_path, actual in ((old, base_hash), (newer, pub_hash)):
        manifest = _read_json(revision_path / 'manifest.json', None)
        entries = manifest.get('files') if isinstance(manifest, dict) else None
        paths = [x.get('path') for x in entries] if isinstance(entries, list) and all(isinstance(x,dict) for x in entries) else None
        if paths is None or len(paths)!=len(set(paths)) or set(paths)!=set(actual):
            raise RuntimeError('revision_manifest_extra_or_missing_artifacts')
    if current_hash != pub_hash:
        raise RuntimeError('candidate_differs_from_published_revision_preserve_and_review')
    if SETTINGS not in pub_hash or SETTINGS in base_hash:
        raise RuntimeError('expected_settings_only_publication_not_found')
    if {k:v for k,v in pub_hash.items() if k != SETTINGS} != base_hash:
        raise RuntimeError('published_calibration_differs_from_active_revision')
    settings_path = candidate / SETTINGS
    if settings_path.stat().st_size > 16384:
        raise RuntimeError('settings_artifact_too_large')
    if not resolve_artifact(_read_json(settings_path, None)):
        raise RuntimeError('published_settings_schema_invalid')
    state_path = STATE_DIR / f'{site_id}.json'
    if state_path.is_symlink() or not state_path.is_file():
        raise RuntimeError('wizard_state_missing_or_unsafe')
    wizard = _read_json(state_path, None)
    old_wizard = _read_json(old / 'wizard_state.json', None)
    if not isinstance(wizard,dict) or not isinstance(old_wizard,dict):
        raise RuntimeError('wizard_state_invalid')
    latest = wizard.get('latest_revision') or {}
    if not isinstance(latest,dict) or latest.get('revision_id') != pub:
        raise RuntimeError('wizard_latest_not_published_revision')
    if (latest.get('candidate_digest') != pub_meta.get('candidate_digest') or
        latest.get('created_at') != pub_meta.get('created_at')):
        raise RuntimeError('wizard_latest_metadata_invalid')
    if wizard.get('draft_parent_revision') != revision_id:
        raise RuntimeError('wizard_draft_parent_mismatch')
    ignored={'draft_parent_revision','draft_started_at','calibration_mode','updated_at','latest_revision'}
    if ({k:v for k,v in wizard.items() if k not in ignored} !=
        {k:v for k,v in old_wizard.items() if k not in ignored}):
        raise RuntimeError('wizard_calibration_semantic_change_detected')
    # Deterministic compare-and-swap token binds exact Candidate + wizard bytes.
    data=json.dumps({'site':site_id,'active':revision_id,'published':pub,'files':pub_hash,
                     'wizard_sha':hashlib.sha256(state_path.read_bytes()).hexdigest()},
                    sort_keys=True,separators=(',',':')).encode()
    token=hashlib.sha256(data).hexdigest()
    return {'ok':True,'eligible':True,'site_id':site_id,'active_revision':revision_id,
            'published_revision':pub,'candidate_file_count':len(current_hash),
            'settings_preserved':True,'calibration_identical_to_active':True,
            'expected_fingerprint':token,'runtime_changed':False,
            'warning':'LAB only; published Revision remains immutable; live runtime not modified.'}


def preview_resume_published(site_id: str, revision_id: str) -> dict:
    # Always return blockers without returning secret camera/telegram contents.
    try:
        return _resume_published_evidence(site_id, revision_id)
    except Exception as exc:
        return {'ok':True,'eligible':False,'reason':str(exc),'runtime_changed':False}


def resume_published_candidate(site_id: str, revision_id: str, payload: dict) -> dict:
    site_id, revision_id = _site_id(site_id), _revision_id(revision_id)
    if not isinstance(payload,dict) or payload.get('confirm_site_id') != site_id or payload.get('confirm_revision_id') != revision_id:
        raise PermissionError('exact_identity_confirmation_required')
    with hardware_lock('published-resume:'+site_id, timeout=3.0):
        preview = _resume_published_evidence(site_id, revision_id)
        if (payload.get('confirm_published_revision_id') != preview['published_revision'] or
            payload.get('expected_fingerprint') != preview['expected_fingerprint']):
            raise RuntimeError('resume_snapshot_changed_refresh_required')
        # Audit intent BEFORE changing registry, then perform one atomic registry
        # mutation. Candidate/Wizard/active pointers are not touched.
        _audit('published_candidate_resume_intent', site_id=site_id,
               parent_revision=revision_id,published_revision=preview['published_revision'],
               fingerprint=preview['expected_fingerprint'])
        def mutate(registry):
            record=(registry.get('sites') or {}).get(site_id)
            if record is None:
                raise KeyError('site_not_registered')
            working=record.get('working_copy') or {}
            if (working.get('state') != 'PUBLISHED' or
                working.get('parent_revision') != revision_id or
                working.get('published_revision') != preview['published_revision']):
                raise RuntimeError('registry_changed_during_resume')
            working['state']='EDITING'
            working['resumed_from_published_revision']=preview['published_revision']
            working['resumed_at']=_now()
            record['working_copy']=working
            record['configuration_state']='EDITING_WORKING_COPY'
            record['updated_at']=_now()
        site_registry._with_registry(mutate)
        _audit('published_candidate_resumed',site_id=site_id,
               parent_revision=revision_id,published_revision=preview['published_revision'])
        return {'ok':True,'state':'EDITING','site_id':site_id,
                'parent_revision':revision_id,'published_revision_preserved':preview['published_revision'],
                'candidate_unchanged':True,'settings_preserved':True,'runtime_changed':False,
                'next':'setup_wizard_then_reverify_publish_activate'}


def verified_published_history(site_id, working, latest):
    """Treat Wizard latest_revision as non-calibration metadata only if immutable provenance verifies."""
    try:
        if not isinstance(latest, dict) or latest.get('revision_id') != working.get('published_revision'):
            return False
        from manager.services.site_lifecycle_v2 import check_revision_source_integrity
        rid=latest['revision_id']
        if check_revision_source_integrity(site_id,rid).get('ok') is not True:
            return False
        from manager.services.revision_engine import REVISION_ROOT
        meta=_read_json(REVISION_ROOT/site_id/rid/'revision.json',None)
        return isinstance(meta,dict) and meta.get('site_id')==site_id and meta.get('revision_id')==rid and meta.get('candidate_digest')==latest.get('candidate_digest') and meta.get('created_at')==latest.get('created_at')
    except (TypeError,ValueError,KeyError,RuntimeError,OSError):
        return False
