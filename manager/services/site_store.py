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


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None

        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except Exception:
        return None


def _resolved(path: Path) -> str | None:
    try:
        if not path.exists() and not path.is_symlink():
            return None

        return str(path.resolve(strict=False))

    except Exception:
        return None


def discover_active_site_dir() -> Path | None:
    """
    หา Active Site จาก preset_rotation_ACTIVE.json

    ตัวอย่าง:
      calibration/preset_rotation_ACTIVE.json
        ->
      calibration/sites/current-site-20260921/preset_rotation.json
    """

    target = _resolved(ACTIVE_ROTATION)

    if not target:
        return None

    target_path = Path(target)

    try:
        target_path.relative_to(SITES_ROOT)
    except ValueError:
        return None

    return target_path.parent


def get_active_site() -> dict:
    site_dir = discover_active_site_dir()

    return {
        "site_id": site_dir.name if site_dir else None,

        "site_dir": (
            str(site_dir)
            if site_dir
            else None
        ),

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
            "data": _read_json(SITE_FILE),
        },
    }


def list_sites() -> list[dict]:
    if not SITES_ROOT.exists():
        return []

    active_dir = discover_active_site_dir()

    sites = []

    for site_dir in sorted(SITES_ROOT.iterdir()):
        if not site_dir.is_dir():
            continue

        sites.append({
            "site_id": site_dir.name,
            "path": str(site_dir),

            "active": (
                active_dir is not None
                and site_dir == active_dir
            ),

            "artifacts": {
                "preset_rotation":
                    (site_dir / "preset_rotation.json").exists(),

                "distance_global":
                    (site_dir / "distance_global.json").exists(),

                "site":
                    (site_dir / "site.json").exists(),

                "camera":
                    (site_dir / "camera.json").exists(),

                "validation":
                    (site_dir / "validation.json").exists(),
            },
        })

    return sites


def get_calibration_status() -> dict:
    active = get_active_site()

    if active["site_dir"]:
        site_dir = Path(active["site_dir"])
    else:
        site_dir = None

    rotation = None
    distance = None

    if site_dir:
        rotation = _read_json(
            site_dir / "preset_rotation.json"
        )

        distance = _read_json(
            site_dir / "distance_global.json"
        )

    return {
        "active_site": active["site_id"],

        "rotation": {
            "loaded": rotation is not None,

            "status": (
                rotation.get("status")
                if rotation
                else None
            ),

            "holdout": (
                rotation.get("holdout")
                if rotation
                else None
            ),

            "model": (
                rotation.get("model")
                if rotation
                else None
            ),

            "runtime_path":
                active["rotation"]["resolved"],
        },

        "distance": {
            "loaded": distance is not None,

            "points": (
                distance.get("points")
                if distance
                else None
            ),

            "pixel_rmse": (
                distance.get("pixel_rmse")
                if distance
                else None
            ),

            "min_distance_m": (
                distance.get("min_distance_m")
                if distance
                else None
            ),

            "max_distance_m": (
                distance.get("max_distance_m")
                if distance
                else None
            ),

            "runtime_path":
                active["distance"]["resolved"],
        },

        "manager": {
            "mode": "READ_ONLY_DISCOVERY",

            "revision_engine": False,
            "activation_engine": False,
            "invalidation_engine": False,
        },
    }
