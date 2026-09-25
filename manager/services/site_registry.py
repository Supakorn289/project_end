from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manager.config import CALIBRATION_ROOT
from manager.services.site_store import (
    get_active_site,
    get_calibration_status,
)


STATE_DIR = CALIBRATION_ROOT / ".manager"

REGISTRY_FILE = STATE_DIR / "sites.json"

LOCK_FILE = STATE_DIR / "sites.lock"


VALID_MODES = {
    "LAB",
    "PRODUCTION",
}


SITE_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _empty_registry() -> dict:
    return {
        "schema_version": 1,
        "updated_at": _now(),
        "sites": {},
    }


def _load_registry_unlocked() -> dict:
    if not REGISTRY_FILE.exists():
        return _empty_registry()

    try:
        payload = json.loads(
            REGISTRY_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload.get("sites"),
            dict
        ):
            return _empty_registry()

        return payload

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return _empty_registry()


def _atomic_write(payload: dict) -> None:

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload["updated_at"] = _now()

    fd, temp_path = tempfile.mkstemp(
        prefix="sites.",
        suffix=".tmp",
        dir=STATE_DIR,
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                payload,
                file,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )

            file.write("\n")

            file.flush()

            os.fsync(
                file.fileno()
            )

        os.replace(
            temp_path,
            REGISTRY_FILE,
        )

    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def _with_registry(mutator=None):

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK_FILE.open(
        "a+",
        encoding="utf-8",
    ) as lock:

        fcntl.flock(
            lock.fileno(),
            fcntl.LOCK_EX,
        )

        registry = (
            _load_registry_unlocked()
        )

        if mutator:
            result = mutator(registry)

            _atomic_write(
                registry
            )

        else:
            result = registry

        fcntl.flock(
            lock.fileno(),
            fcntl.LOCK_UN,
        )

        return result


def _validate_mode(
    mode: str,
) -> str:

    normalized = (
        str(mode)
        .strip()
        .upper()
    )

    if normalized not in VALID_MODES:
        raise ValueError(
            "mode must be LAB or PRODUCTION"
        )

    return normalized


def _validate_site_id(
    site_id: str,
) -> str:

    value = str(site_id).strip()

    if not SITE_ID_PATTERN.fullmatch(
        value
    ):
        raise ValueError(
            "invalid site_id"
        )

    return value


def _default_components(
    mode: str,
) -> dict:

    if mode == "LAB":
        return {
            "camera": "UNKNOWN",
            "intrinsics": "UNKNOWN",
            "preset_geometry": "UNKNOWN",
            "cross_preset": "UNKNOWN",

            "distance":
                "DEFERRED",

            "site_bearing":
                "DEFERRED",

            "gps":
                "DISABLED",
        }

    return {
        "camera": "UNKNOWN",
        "intrinsics": "REQUIRED",
        "preset_geometry": "REQUIRED",
        "cross_preset": "REQUIRED",
        "distance": "REQUIRED",
        "site_bearing": "REQUIRED",
        "gps": "REQUIRED",
    }


def _rotation_validation_state(
    raw_status: str | None,
) -> str:

    value = (
        raw_status or ""
    ).upper()

    if "CANDIDATE" in value:
        return "CANDIDATE"

    if (
        "VALIDATED" in value
        or value == "PASS"
    ):
        return "VALIDATED"

    return "UNKNOWN"


def list_registered_sites() -> dict:

    registry = _with_registry()

    return registry


def adopt_current_site(
    mode: str = "LAB",
    display_name: str | None = None,
) -> dict:

    mode = _validate_mode(mode)

    active = get_active_site()

    calibration = (
        get_calibration_status()
    )

    site_id = active.get(
        "site_id"
    )

    if not site_id:
        raise RuntimeError(
            "active site could not be discovered"
        )

    site_id = _validate_site_id(
        site_id
    )

    rotation = (
        calibration.get(
            "rotation",
            {}
        )
    )

    distance = (
        calibration.get(
            "distance",
            {}
        )
    )

    raw_rotation_status = (
        rotation.get("status")
    )

    validation_state = (
        _rotation_validation_state(
            raw_rotation_status
        )
    )

    components = (
        _default_components(mode)
    )

    if rotation.get("loaded"):
        components[
            "preset_geometry"
        ] = "ACTIVE"

        components[
            "cross_preset"
        ] = "ACTIVE"

    if distance.get("loaded"):
        components[
            "distance"
        ] = "CALIBRATED_UNVERIFIED"

    if mode == "LAB":
        components[
            "site_bearing"
        ] = "DEFERRED"

        components[
            "gps"
        ] = "DISABLED"

    warnings: list[str] = []

    if (
        raw_rotation_status
        and
        "NOT_INSTALLED"
        in raw_rotation_status.upper()
    ):
        warnings.append(
            "Rotation is runtime-active "
            "but legacy metadata says "
            "NOT_INSTALLED."
        )

    def mutate(registry: dict):

        sites = registry["sites"]

        previous = sites.get(
            site_id,
            {}
        )

        created_at = previous.get(
            "created_at",
            _now(),
        )

        record = {
            "site_id": site_id,

            "display_name": (
                display_name
                or previous.get(
                    "display_name"
                )
                or site_id
            ),

            "mode": mode,

            "lifecycle": "ACTIVE",

            "runtime_active": True,

            "validation_state":
                validation_state,

            "source":
                "LEGACY_RUNTIME_IMPORT",

            "site_dir":
                active.get(
                    "site_dir"
                ),

            "rotation_metadata_status":
                raw_rotation_status,

            "components":
                components,

            "warnings":
                warnings,

            "created_at":
                created_at,

            "updated_at":
                _now(),
        }

        sites[
            site_id
        ] = record

        return record

    return _with_registry(
        mutate
    )


def create_site(
    site_id: str,
    mode: str,
    display_name: str | None = None,
) -> dict:

    site_id = _validate_site_id(
        site_id
    )

    mode = _validate_mode(
        mode
    )

    def mutate(registry: dict):

        sites = registry["sites"]

        if site_id in sites:
            raise ValueError(
                "site already exists"
            )

        record = {
            "site_id": site_id,

            "display_name": (
                display_name
                or site_id
            ),

            "mode": mode,

            "lifecycle": "DRAFT",

            "runtime_active": False,

            "validation_state":
                "DRAFT",

            "source":
                "MANAGER",

            "site_dir":
                None,

            "rotation_metadata_status":
                None,

            "components":
                _default_components(
                    mode
                ),

            "warnings": [],

            "created_at":
                _now(),

            "updated_at":
                _now(),
        }

        sites[
            site_id
        ] = record

        return record

    return _with_registry(
        mutate
    )


def set_site_mode(
    site_id: str,
    mode: str,
) -> dict:

    site_id = _validate_site_id(
        site_id
    )

    mode = _validate_mode(
        mode
    )

    def mutate(registry: dict):

        sites = registry["sites"]

        if site_id not in sites:
            raise KeyError(
                "site not registered"
            )

        site = sites[
            site_id
        ]

        previous_mode = site[
            "mode"
        ]

        site["mode"] = mode

        components = site[
            "components"
        ]

        if (
            previous_mode == "LAB"
            and mode == "PRODUCTION"
        ):

            if components.get(
                "distance"
            ) == "DEFERRED":
                components[
                    "distance"
                ] = "REQUIRED"

            if components.get(
                "site_bearing"
            ) in {
                "DEFERRED",
                "DISABLED",
            }:
                components[
                    "site_bearing"
                ] = "REQUIRED"

            if components.get(
                "gps"
            ) in {
                "DEFERRED",
                "DISABLED",
            }:
                components[
                    "gps"
                ] = "REQUIRED"

        elif (
            previous_mode == "PRODUCTION"
            and mode == "LAB"
        ):

            if components.get(
                "distance"
            ) == "REQUIRED":
                components[
                    "distance"
                ] = "DEFERRED"

            if components.get(
                "site_bearing"
            ) == "REQUIRED":
                components[
                    "site_bearing"
                ] = "DEFERRED"

            if components.get(
                "gps"
            ) == "REQUIRED":
                components[
                    "gps"
                ] = "DISABLED"

        site[
            "updated_at"
        ] = _now()

        return site

    return _with_registry(
        mutate
    )


INVALIDATION_RULES = {

    "camera_ip": [],

    "camera_credentials": [],

    "camera_hardware": [
        "intrinsics",
        "preset_geometry",
        "cross_preset",
        "distance",
    ],

    "resolution": [
        "intrinsics",
        "preset_geometry",
        "cross_preset",
        "distance",
    ],

    "hfov": [
        "intrinsics",
        "preset_geometry",
        "cross_preset",
        "distance",
    ],

    "preset_positions": [
        "preset_geometry",
        "cross_preset",
    ],

    "camera_mount": [
        "preset_geometry",
        "cross_preset",
        "distance",
        "site_bearing",
        "gps",
    ],

    "site_location": [
        "distance",
        "site_bearing",
        "gps",
    ],
}


def preview_invalidation(
    change: str,
) -> dict:

    key = str(change).strip()

    if key not in INVALIDATION_RULES:
        raise ValueError(
            "unknown change type"
        )

    affected = (
        INVALIDATION_RULES[
            key
        ]
    )

    return {
        "change": key,

        "affected":
            affected,

        "preserved": (
            "ALL"
            if not affected
            else None
        ),

        "write_performed":
            False,
    }
