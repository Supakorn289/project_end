from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from manager.config import (
    ACTIVE_DISTANCE,
    ACTIVE_ROTATION,
    SITE_FILE,
    SITES_ROOT,
)


def _read_json(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _resolved(path: Path) -> str | None:
    try:
        if not path.exists() and not path.is_symlink():
            return None
        return str(path.resolve(strict=False))
    except Exception:
        return None


def _active_runtime_identity() -> dict:
    target = _resolved(ACTIVE_ROTATION)
    result = {
        "site_id": None,
        "revision_id": None,
        "site_dir": None,
        "revision_dir": None,
        "rotation_resolved": target,
    }
    if not target:
        return result

    target_path = Path(target)
    try:
        relative = target_path.relative_to(SITES_ROOT)
    except ValueError:
        return result

    parts = relative.parts
    if not parts:
        return result

    site_id = parts[0]
    site_dir = SITES_ROOT / site_id

    if len(parts) >= 4 and parts[1] == "revisions":
        revision_id = parts[2]
        revision_dir = site_dir / "revisions" / revision_id
    else:
        revision_id = None
        revision_dir = target_path.parent

    result.update({
        "site_id": site_id,
        "revision_id": revision_id,
        "site_dir": str(site_dir),
        "revision_dir": str(revision_dir),
    })
    return result


def discover_active_site_dir() -> Path | None:
    value = _active_runtime_identity().get("site_dir")
    return Path(value) if value else None


def discover_active_revision_dir() -> Path | None:
    value = _active_runtime_identity().get("revision_dir")
    return Path(value) if value else None


def get_active_site() -> dict:
    identity = _active_runtime_identity()
    return {
        "site_id": identity.get("site_id"),
        "revision_id": identity.get("revision_id"),
        "site_dir": identity.get("site_dir"),
        "revision_dir": identity.get("revision_dir"),
        "rotation": {
            "path": str(ACTIVE_ROTATION),
            "exists": ACTIVE_ROTATION.exists(),
            "is_symlink": ACTIVE_ROTATION.is_symlink(),
            "resolved": _resolved(ACTIVE_ROTATION),
        },
        "distance": {
            "path": str(ACTIVE_DISTANCE),
            "exists": ACTIVE_DISTANCE.exists(),
            "is_symlink": ACTIVE_DISTANCE.is_symlink(),
            "resolved": _resolved(ACTIVE_DISTANCE),
        },
        "site_file": {
            "path": str(SITE_FILE),
            "exists": SITE_FILE.exists(),
            "is_symlink": SITE_FILE.is_symlink(),
            "resolved": _resolved(SITE_FILE),
            "data": _read_json(SITE_FILE),
        },
    }


def _revision_artifacts(path: Path | None) -> dict:
    if path is None or not path.is_dir():
        return {
            "preset_rotation": False,
            "distance_global": False,
            "site": False,
            "camera": False,
            "validation": False,
        }
    return {
        "preset_rotation": (path / "preset_rotation.json").exists(),
        "distance_global": (path / "distance_global.json").exists(),
        "site": (path / "site.json").exists(),
        "camera": (path / "camera.json").exists(),
        "validation": (path / "validation.json").exists(),
    }


def list_sites() -> list[dict]:
    if not SITES_ROOT.exists():
        return []

    active = get_active_site()
    active_site_id = active.get("site_id")
    active_revision_id = active.get("revision_id")
    sites = []

    for site_dir in sorted(SITES_ROOT.iterdir()):
        if not site_dir.is_dir():
            continue

        revisions = []
        revision_root = site_dir / "revisions"
        if revision_root.is_dir():
            for revision_dir in sorted(revision_root.iterdir()):
                if not revision_dir.is_dir():
                    continue
                revisions.append({
                    "revision_id": revision_dir.name,
                    "path": str(revision_dir),
                    "active": (
                        site_dir.name == active_site_id
                        and revision_dir.name == active_revision_id
                    ),
                    "artifacts": _revision_artifacts(revision_dir),
                })

        site_active = site_dir.name == active_site_id
        legacy_artifacts = _revision_artifacts(site_dir)

        active_artifacts = legacy_artifacts
        if site_active and active.get("revision_dir"):
            active_artifacts = _revision_artifacts(
                Path(active["revision_dir"])
            )

        sites.append({
            "site_id": site_dir.name,
            "path": str(site_dir),
            "active": site_active,
            "active_revision_id": (
                active_revision_id if site_active else None
            ),
            "artifacts": active_artifacts,
            "legacy_artifacts": legacy_artifacts,
            "revisions": revisions,
        })

    return sites


def get_calibration_status() -> dict:
    active = get_active_site()

    rotation_path = active.get("rotation", {}).get("resolved")
    distance_path = active.get("distance", {}).get("resolved")
    site_path = active.get("site_file", {}).get("resolved")

    rotation = _read_json(rotation_path)
    distance = _read_json(distance_path)
    site_payload = _read_json(site_path)

    artifact_status = rotation.get("status") if rotation else None
    override = (
        (rotation.get("operator_override", {}) or {})
        if rotation else {}
    )

    forced = bool(
        rotation
        and (
            str(artifact_status or "").upper().startswith("FORCED_")
            or override.get("enabled") is True
        )
    )

    if rotation is None:
        display_status = None
    elif forced:
        display_status = "FORCED_ACTIVE"
    else:
        display_status = "ACTIVE"

    holdout_gate = (
        (
            rotation.get("independent_holdout_gate")
            or rotation.get("holdout")
            or {}
        )
        if rotation else {}
    )

    return {
        "active_site": active.get("site_id"),
        "active_revision": active.get("revision_id"),
        "rotation": {
            "loaded": rotation is not None,
            "status": display_status,
            "artifact_status": artifact_status,
            "forced": forced,
            "operator_override": override,
            "holdout": holdout_gate,
            "holdout_passed": (
                holdout_gate.get("passed")
                if isinstance(holdout_gate, dict)
                else None
            ),
            "model": rotation.get("model") if rotation else None,
            "runtime_path": rotation_path,
        },
        "distance": {
            "loaded": distance is not None,
            "status": "ACTIVE" if distance else None,
            "points": distance.get("points") if distance else None,
            "pixel_rmse": distance.get("pixel_rmse") if distance else None,
            "min_distance_m": (
                distance.get("min_distance_m") if distance else None
            ),
            "max_distance_m": (
                distance.get("max_distance_m") if distance else None
            ),
            "runtime_path": distance_path,
        },
        "site": {
            "loaded": site_payload is not None,
            "runtime_path": site_path,
            "data": site_payload,
        },
        "manager": {
            "mode": "COMMISSIONING_MANAGER",
            "revision_engine": True,
            "activation_engine": True,
            "invalidation_engine": False,
        },
    }
