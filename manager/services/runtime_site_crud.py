from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
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
        and
        working.get("state")
    )

    return {
        "exists": exists,
        "state": working.get("state"),
        "parent_revision": working.get("parent_revision"),
        "published_revision": working.get("published_revision"),
        "started_at": working.get("started_at"),
        "camera_test_required": working.get("camera_test_required"),
        "camera_test_passed": working.get("camera_test_passed"),
        "camera": (
            _camera_summary_from_file(camera)
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
    return {
        **data,
        "active": is_active,
        "deletable": not is_active,
        "source_exists": source.exists(),
        "deployment_exists": deployed.exists(),
        "camera": _camera_summary(camera_file) if camera_file.exists() else {"configured": False},
        "geometry": _geometry_summary(rotation_file) if rotation_file.exists() else {},
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
                revisions.append({
                    "revision_id": path.name,
                    "status": "DEPLOYED_ONLY",
                    "candidate_ready": False,
                    "active": active,
                    "deletable": not active,
                    "source_exists": False,
                    "deployment_exists": True,
                    "camera": {"configured": False},
                    "geometry": {},
                })

        is_active = site_id == active_site
        sites.append({
            "site_id": site_id,
            "display_name": record.get("display_name") or site_id,
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
            "deletable": not is_active,
            "site_id_mutable": False,
            "working_copy": _working_copy_info(site_id, record),
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
    normalized = _normalized_update(site_id, payload)
    preview = preview_site_update(site_id, payload)

    def mutate(registry: dict):
        site = registry["sites"].get(site_id)
        if not site:
            raise KeyError("site not registered")

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


def create_working_copy(
    site_id: str,
    revision_id: str,
    *,
    overwrite=False,
) -> dict:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    source = _source_revision_dir(site_id, revision_id)
    if not source.exists():
        raise FileNotFoundError("revision not found")

    artifacts = source / "artifacts"
    if not artifacts.is_dir():
        raise RuntimeError("revision artifacts missing")

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


def update_working_camera(site_id: str, payload: dict) -> dict:
    site_id = _site_id(site_id)
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
            "การเปลี่ยน IP/credential ไม่ทำลาย calibration แต่ต้อง Test Camera/RTSP ใหม่",
        ],
    }


def test_working_camera(site_id: str) -> dict:
    site_id = _site_id(site_id)
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
    registry = site_registry.list_registered_sites()
    site = registry.get("sites", {}).get(site_id, {})
    working = site.get("working_copy", {}) or {}

    if not working:
        raise RuntimeError("working copy not found")
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


def discard_working_copy(site_id: str) -> dict:
    site_id = _site_id(site_id)
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


def revision_delete_preview(site_id: str, revision_id: str) -> dict:
    site_id = _site_id(site_id)
    revision_id = _revision_id(revision_id)
    active_site, active_revision = _active_identity()
    active = site_id == active_site and revision_id == active_revision
    source = _source_revision_dir(site_id, revision_id)
    deployed = _deployment_revision_dir(site_id, revision_id)
    exists = source.exists() or deployed.exists()

    return {
        "ok": True,
        "site_id": site_id,
        "revision_id": revision_id,
        "exists": bool(exists),
        "active": active,
        "deletable": bool(exists and not active),
        "source_exists": source.exists(),
        "deployment_exists": deployed.exists(),
        "delete_mode": "MOVE_TO_TRASH",
        "confirm_value": revision_id,
        "warnings": (
            ["Active Revision ห้ามลบ ให้ Activate Revision อื่นก่อน"]
            if active
            else [
                "Revision จะถูกย้ายไป Trash ไม่ใช่ rm -rf",
                "การลบไม่กระทบ Active Runtime ถ้า Revision นี้ไม่ได้ Active",
            ]
        ),
        "runtime_changed": False,
    }


def delete_revision(site_id: str, revision_id: str, confirm_value: str) -> dict:
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
        / f"{_stamp()}-{revision_id}"
    )
    trash.mkdir(parents=True, exist_ok=False)
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
    active = site_id == active_site
    registry = site_registry.list_registered_sites()
    registered = site_id in (registry.get("sites", {}) or {})
    revisions = REVISION_ROOT / site_id
    deployed = DEPLOY_ROOT / site_id
    candidate = CANDIDATE_DIR / site_id
    wizard = STATE_DIR / f"{site_id}.json"
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
        "deletable": bool(exists and not active),
        "revision_count": revision_count,
        "has_candidate": candidate.exists(),
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
    site_id = _site_id(site_id)
    preview = site_delete_preview(site_id)
    if confirm_value != site_id:
        raise ValueError("confirmation mismatch")
    if not preview.get("deletable"):
        raise RuntimeError("site is active or not found")

    trash = TRASH_ROOT / "sites" / f"{_stamp()}-{site_id}"
    trash.mkdir(parents=True, exist_ok=False)
    paths = [
        (REVISION_ROOT / site_id, trash / "revisions"),
        (DEPLOY_ROOT / site_id, trash / "deployment"),
        (CANDIDATE_DIR / site_id, trash / "candidate"),
        (STATE_DIR / f"{site_id}.json", trash / "wizard_state.json"),
    ]
    moved = []

    try:
        for source, destination in paths:
            if not source.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((destination, source))

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
