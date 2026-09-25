from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
from typing import Any

from manager.config import (
    ACTIVE_DISTANCE,
    ACTIVE_ROTATION,
    CALIBRATION_ROOT,
    PROJECT_ROOT,
    SITE_FILE,
)

from manager.services.site_store import (
    get_active_site,
    get_calibration_status,
)

from manager.services.site_registry import (
    list_registered_sites,
)

from manager.services.system_info import (
    get_system_info,
)


from manager.services.runtime_settings import (
    get_runtime_settings,
)


INTRINSICS_FILE = (
    CALIBRATION_ROOT
    / "camera_intrinsics.json"
)


def _module(name: str):

    try:
        return importlib.import_module(
            name
        )

    except Exception:
        return None


def _attr(
    module,
    name: str,
    default=None,
):

    if module is None:
        return default

    return getattr(
        module,
        name,
        default,
    )


def _intrinsics_hfov():
    """
    Read calibrated horizontal FOV from camera intrinsics.

    Preferred:
        explicit hfov field

    Fallback:
        derive from camera matrix:
            HFOV = 2 * atan(width / (2 * fx))
    """

    try:

        data = json.loads(
            INTRINSICS_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


    for key in (
        "hfov_deg",
        "horizontal_fov_deg",
        "calibrated_hfov_deg",
        "hfov",
    ):

        value = data.get(
            key
        )

        if value is not None:

            try:
                return float(
                    value
                )

            except (
                TypeError,
                ValueError,
            ):
                pass


    try:

        matrix = data[
            "camera_matrix"
        ]

        fx = float(
            matrix[0][0]
        )

        width = float(
            data[
                "frame_width"
            ]
        )

        if (
            fx > 0
            and width > 0
        ):

            return math.degrees(
                2.0
                * math.atan(
                    width
                    /
                    (
                        2.0
                        * fx
                    )
                )
            )

    except Exception:
        pass


    return None



def _exists(
    path: Path,
) -> bool:

    return bool(
        path.exists()
        or path.is_symlink()
    )


def _source_contains(
    relative: str,
    needle: str,
) -> bool:

    try:

        text = (
            PROJECT_ROOT
            / relative
        ).read_text(
            encoding="utf-8"
        )

        return needle in text

    except Exception:
        return False


def _preset_bearings(
    config_module,
) -> dict[str, float]:

    raw = _attr(
        config_module,
        "PRESET_BEARING_DEG",
        {},
    )

    if not isinstance(
        raw,
        dict,
    ):
        return {}

    result = {}

    for key, value in raw.items():

        try:
            result[
                str(int(key))
            ] = float(value)

        except Exception:
            continue

    return result


def _overlap_pairs() -> list[list[int]]:

    fusion = _module(
        "cross_preset_fusion"
    )

    raw = _attr(
        fusion,
        "OVERLAP_PAIRS",
        set(),
    )

    result = []

    try:

        for pair in raw:

            values = sorted(
                int(v)
                for v in pair
            )

            if len(values) == 2:
                result.append(
                    values
                )

    except Exception:
        return []

    result.sort()

    return result


def get_discovery_snapshot() -> dict[str, Any]:

    config_module = _module(
        "config"
    )

    fusion_module = _module(
        "cross_preset_fusion"
    )

    finalizer_module = _module(
        "alert_finalizer"
    )


    active = get_active_site()

    calibration = (
        get_calibration_status()
    )

    registry = (
        list_registered_sites()
    )

    system = (
        get_system_info()
    )


    site_id = active.get(
        "site_id"
    )


    manager_site = None

    try:

        manager_site = (
            registry
            .get(
                "sites",
                {}
            )
            .get(
                site_id
            )
        )

    except Exception:
        manager_site = None


    preset_bearings = (
        _preset_bearings(
            config_module
        )
    )


    sweep_sequence = _attr(
        config_module,
        "SWEEP_SEQUENCE",
        [],
    )

    try:
        sweep_sequence = [
            int(v)
            for v in sweep_sequence
        ]
    except Exception:
        sweep_sequence = []


    runtime_settings = (
        get_runtime_settings()
    )

    runtime_values = (
        runtime_settings.get(
            "values",
            {},
        )
        if runtime_settings.get(
            "ok"
        )
        else {}
    )


    camera_ip = (
        runtime_values.get(
            "CAMERA_IP"
        )
        or
        _attr(
            config_module,
            "CAMERA_IP",
            None,
        )
    )


    camera_http_port = int(
        runtime_values.get(
            "CAMERA_HTTP_PORT"
        )
        or
        _attr(
            config_module,
            "CAMERA_HTTP_PORT",
            81,
        )
    )


    rtsp_port = int(
        runtime_values.get(
            "RTSP_PORT"
        )
        or
        _attr(
            config_module,
            "RTSP_PORT",
            10554,
        )
    )


    rtsp_path = (
        runtime_values.get(
            "RTSP_PATH"
        )
        or
        _attr(
            config_module,
            "RTSP_PATH",
            None,
        )
    )


    frame_width = _attr(
        config_module,
        "FRAME_WIDTH",
        None,
    )

    frame_height = _attr(
        config_module,
        "FRAME_HEIGHT",
        None,
    )

    calibrated_hfov = (
        _intrinsics_hfov()
    )


    if calibrated_hfov is not None:

        hfov = float(
            calibrated_hfov
        )

        hfov_source = (
            "camera_intrinsics.json"
        )

    else:

        hfov = _attr(
            config_module,
            "HFOV_DEG",
            None,
        )

        hfov_source = (
            "config.py"
        )


    anchor_max_age = float(
        runtime_values.get(
            "FUSION_ANCHOR_MAX_AGE_SEC"
        )
        or
        _attr(
            fusion_module,
            "ANCHOR_MAX_AGE_SEC",
            15.0,
        )
    )


    safety_timeout = float(
        runtime_values.get(
            "FUSION_PENDING_SAFETY_SEC"
        )
        or
        _attr(
            finalizer_module,
            "DEFAULT_PENDING_SEC",
            90.0,
        )
    )


    preset_aware = (
        _source_contains(
            "main.py",
            "PRESET_AWARE",
        )
        and
        hasattr(
            finalizer_module,
            "mark_preset_scanned",
        )
        is False
    )

    # mark_preset_scanned belongs to class,
    # so source verification is the authoritative
    # lightweight discovery check here.
    preset_aware = (
        _source_contains(
            "main.py",
            "Pending verification complete",
        )
        and
        _source_contains(
            "alert_finalizer.py",
            "mark_preset_scanned",
        )
    )


    installation_kind = (
        "EXISTING"
        if (
            site_id
            and
            _exists(
                ACTIVE_ROTATION
            )
        )
        else "NEW"
    )


    return {

        "installation": {
            "detected":
                installation_kind,

            "active_site":
                site_id,

            "manager_registered":
                manager_site
                is not None,

            "mode": (
                manager_site.get(
                    "mode"
                )
                if manager_site
                else None
            ),

            "lifecycle": (
                manager_site.get(
                    "lifecycle"
                )
                if manager_site
                else None
            ),
        },


        "system":
            system,


        "camera": {
            "configured":
                bool(camera_ip),

            "ip":
                camera_ip,

            "http_port":
                camera_http_port,

            "rtsp_port":
                rtsp_port,

            "rtsp_path":
                rtsp_path,

            "frame_width":
                frame_width,

            "frame_height":
                frame_height,

            "hfov_deg":
                hfov,

            "hfov_source":
                hfov_source,
        },


        "ptz": {
            "preset_count":
                len(
                    preset_bearings
                ),

            "preset_bearings":
                preset_bearings,

            "sweep_sequence":
                sweep_sequence,

            "overlap_pairs":
                _overlap_pairs(),
        },


        "calibration": {
            "intrinsics": {
                "exists":
                    _exists(
                        INTRINSICS_FILE
                    ),

                "path":
                    str(
                        INTRINSICS_FILE
                    ),
            },

            "rotation": (
                calibration.get(
                    "rotation",
                    {}
                )
            ),

            "distance": (
                calibration.get(
                    "distance",
                    {}
                )
            ),

            "site_bearing": {
                "exists":
                    _exists(
                        SITE_FILE
                    ),

                "path":
                    str(
                        SITE_FILE
                    ),
            },
        },


        "runtime_core": {
            "dynamic_geometry":
                bool(
                    calibration
                    .get(
                        "rotation",
                        {}
                    )
                    .get(
                        "loaded"
                    )
                ),

            "cross_preset_fusion":
                len(
                    _overlap_pairs()
                ) > 0,

            "anchor_max_age_sec":
                anchor_max_age,

            "pending_mode": (
                "PRESET_AWARE"
                if preset_aware
                else "UNKNOWN"
            ),

            "pending_safety_sec":
                safety_timeout,

            "temporal_consensus": {
                "frames_per_scan":
                    _attr(
                        config_module,
                        "FRAMES_PER_SCAN",
                        None,
                    ),

                "minimum_confirm":
                    _attr(
                        config_module,
                        "MIN_CONFIRM_FRAMES",
                        None,
                    ),
            },
        },
    }
