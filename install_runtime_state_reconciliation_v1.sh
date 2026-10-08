#!/usr/bin/env bash
set -euo pipefail
cd /opt/smart-fire-detection-v2

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="calibration/.manager/patch-backups/runtime-state-${STAMP}"
mkdir -p "$BACKUP"
cp -a manager/services/site_store.py "$BACKUP/"
cp -a manager/services/site_registry.py "$BACKUP/"
cp -a manager/activation_api.py "$BACKUP/"
[ -f deploy/install-manager-stack.sh ] && cp -a deploy/install-manager-stack.sh "$BACKUP/"

cat > manager/services/site_store.py <<'PY'
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
PY

python3 - <<'PY'
from pathlib import Path

p = Path("manager/services/site_registry.py")
text = p.read_text(encoding="utf-8")

start = text.index("def _rotation_validation_state(\n")
end = text.index("\ndef adopt_current_site(\n", start)

replacement = r'''def _rotation_validation_state(
    raw_status: str | None,
) -> str:
    value = (raw_status or "").upper()

    if "FORCED" in value:
        return "FORCED"

    if (
        value == "ACTIVE"
        or value.startswith("PASS_")
        or "VALIDATED" in value
        or value == "PASS"
    ):
        return "VALIDATED"

    if "CANDIDATE" in value:
        return "CANDIDATE"

    return "UNKNOWN"


def _overlay_runtime_state(registry: dict) -> dict:
    active = get_active_site()
    calibration = get_calibration_status()

    active_id = active.get("site_id")
    active_revision = active.get("revision_id")
    sites = registry.get("sites", {})

    for site_id, site in sites.items():
        is_active = bool(active_id and site_id == active_id)
        site["runtime_active"] = is_active

        if is_active:
            site["lifecycle"] = "ACTIVE"
            site["site_dir"] = active.get("site_dir")
            site["active_revision_id"] = active_revision

            rotation = calibration.get("rotation", {}) or {}
            distance = calibration.get("distance", {}) or {}

            raw_status = (
                rotation.get("artifact_status")
                or rotation.get("status")
            )

            site["rotation_metadata_status"] = raw_status
            site["validation_state"] = _rotation_validation_state(
                raw_status
            )

            components = (
                site.get("components")
                or _default_components(site.get("mode", "LAB"))
            )

            if rotation.get("loaded"):
                components["preset_geometry"] = (
                    "FORCED_ACTIVE"
                    if rotation.get("forced")
                    else "ACTIVE"
                )
                components["cross_preset"] = "ACTIVE"

            if distance.get("loaded"):
                components["distance"] = "CALIBRATED_UNVERIFIED"

            site["components"] = components

            warnings = list(site.get("warnings") or [])
            warning = (
                "Active runtime uses FORCED geometry; "
                "independent holdout did not pass."
            )
            if rotation.get("forced") and warning not in warnings:
                warnings.append(warning)
            site["warnings"] = warnings

        else:
            site.pop("active_revision_id", None)

            if str(site.get("lifecycle", "")).upper() == "ACTIVE":
                site["lifecycle"] = (
                    "DRAFT"
                    if site.get("validation_state") == "DRAFT"
                    else "INACTIVE"
                )

    return registry


def list_registered_sites() -> dict:
    registry = _with_registry()
    return _overlay_runtime_state(registry)


def reconcile_active_runtime() -> dict:
    def mutate(registry: dict):
        return _overlay_runtime_state(registry)

    registry = _with_registry(mutate)
    active = get_active_site()

    return {
        "ok": True,
        "active_site": active.get("site_id"),
        "active_revision": active.get("revision_id"),
        "registry": registry,
    }

'''

p.write_text(
    text[:start] + replacement + text[end:],
    encoding="utf-8",
)

print("SITE_REGISTRY_RECONCILIATION=PATCHED")
PY

python3 - <<'PY'
from pathlib import Path

p = Path("manager/activation_api.py")
text = p.read_text(encoding="utf-8")

if "reconcile_active_runtime" not in text:
    anchor = '''from manager.services.ops_agent import (
    activate_revision,
)
'''
    insert = anchor + '''

from manager.services.site_registry import (
    reconcile_active_runtime,
)
'''
    if anchor not in text:
        raise SystemExit("activation_api import anchor not found")
    text = text.replace(anchor, insert, 1)

if "registry_reconciled" not in text:
    anchor = '''        result = activate_revision(
            site_id,
            revision_id,
        )


        return jsonify(
            result
        ), (
'''
    replacement = '''        result = activate_revision(
            site_id,
            revision_id,
        )


        if result.get(
            "ok"
        ):
            try:
                reconcile_active_runtime()
                result[
                    "registry_reconciled"
                ] = True

            except Exception as exc:
                result[
                    "registry_reconciled"
                ] = False
                result[
                    "registry_warning"
                ] = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )


        return jsonify(
            result
        ), (
'''
    if anchor not in text:
        raise SystemExit("activation_api execution anchor not found")
    text = text.replace(anchor, replacement, 1)

p.write_text(text, encoding="utf-8")
print("ACTIVATION_REGISTRY_RECONCILE=PATCHED")
PY

if [ -f deploy/install-manager-stack.sh ]; then
python3 - <<'PY'
from pathlib import Path

p = Path("deploy/install-manager-stack.sh")
text = p.read_text(encoding="utf-8")

if "Runtime output directory ownership" not in text:
    marker = '''chown -R \\
fire:fire \\
"$PROJECT_ROOT"


# ------------------------------------------------------------
# Venv
# ------------------------------------------------------------
'''
    replacement = '''chown -R \\
fire:fire \\
"$PROJECT_ROOT"


# ------------------------------------------------------------
# Runtime output directory ownership
# ------------------------------------------------------------
if id smartfire >/dev/null 2>&1; then
    install -d \\
        -o smartfire \\
        -g smartfire \\
        -m 0755 \\
        "$PROJECT_ROOT/static"

    chown -R \\
        smartfire:smartfire \\
        "$PROJECT_ROOT/static"

    find "$PROJECT_ROOT/static" \\
        -type d -exec chmod 0755 {} \\;

    find "$PROJECT_ROOT/static" \\
        -type f -exec chmod 0644 {} \\;
fi


# ------------------------------------------------------------
# Venv
# ------------------------------------------------------------
'''
    if marker not in text:
        raise SystemExit("installer ownership anchor not found")
    text = text.replace(marker, replacement, 1)

p.write_text(text, encoding="utf-8")
print("INSTALLER_STATIC_OWNERSHIP=PATCHED")
PY
fi

mkdir -p deploy/systemd/smart-fire-manager-agent.service.d
cat > deploy/systemd/smart-fire-manager-agent.service.d/30-privilege-drop.conf <<'EOF'
[Service]
AmbientCapabilities=CAP_SETUID CAP_SETGID
EOF

if id smartfire >/dev/null 2>&1; then
    sudo chown -R smartfire:smartfire /opt/smart-fire-detection-v2/static
    sudo find /opt/smart-fire-detection-v2/static -type d -exec chmod 0755 {} \;
    sudo find /opt/smart-fire-detection-v2/static -type f -exec chmod 0644 {} \;
fi

./venv/bin/python -m py_compile \
    manager/services/site_store.py \
    manager/services/site_registry.py \
    manager/activation_api.py

bash -n deploy/install-manager-stack.sh

git diff --check -- \
    manager/services/site_store.py \
    manager/services/site_registry.py \
    manager/activation_api.py \
    deploy/install-manager-stack.sh \
    deploy/systemd/smart-fire-manager-agent.service.d/30-privilege-drop.conf

PYTHONPATH="$PWD" ./venv/bin/python - <<'PY'
import json
from manager.services.site_store import get_active_site, get_calibration_status
from manager.services.site_registry import reconcile_active_runtime

print("=== ACTIVE RUNTIME ===")
print(json.dumps(get_active_site(), indent=2, ensure_ascii=False))

print("\n=== CALIBRATION ===")
print(json.dumps(get_calibration_status(), indent=2, ensure_ascii=False))

print("\n=== REGISTRY ===")
r = reconcile_active_runtime()
print(json.dumps({
    "ok": r.get("ok"),
    "active_site": r.get("active_site"),
    "active_revision": r.get("active_revision"),
}, indent=2, ensure_ascii=False))
PY

sudo systemctl restart smart-fire-manager.service

echo
echo "=== SERVICES ==="
systemctl is-active \
    smart-fire-manager.service \
    smart-fire-detection.service \
    smart-fire-dashboard.service \
    smart-fire-manager-agent.service

echo
echo "=== ACTIVE API ==="
curl -fsS http://127.0.0.1:5050/api/site/active \
| ./venv/bin/python -m json.tool

echo
echo "=== CALIBRATION API ==="
curl -fsS http://127.0.0.1:5050/api/calibration/status \
| ./venv/bin/python -m json.tool

echo
echo "=== OVERVIEW SUMMARY ==="
curl -fsS http://127.0.0.1:5050/api/overview \
| ./venv/bin/python -c '
import json,sys
d=json.load(sys.stdin)
x=d["discovery"]
s=d["setup"]
print(json.dumps({
  "installation":x["installation"],
  "rotation":x["calibration"]["rotation"],
  "distance":x["calibration"]["distance"],
  "dynamic_geometry":x["runtime_core"]["dynamic_geometry"],
  "setup_ready":s["ready"],
  "blocker_count":s["blocker_count"],
},indent=2,ensure_ascii=False))
'

echo
echo "RUNTIME_STATE_RECONCILIATION=COMPLETE"
echo "Backup: $BACKUP"
