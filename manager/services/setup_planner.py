from __future__ import annotations

import json
import math
from pathlib import Path

from manager.config import (
    CALIBRATION_ROOT,
    SITE_FILE,
)
from manager.services.discovery import (
    get_discovery_snapshot,
)
from manager.services.site_registry import (
    list_registered_sites,
)
from manager.services.wizard_store import (
    load_state,
)


def _item(
    key: str,
    label: str,
    status: str,
    detail: str,
) -> dict:

    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
    }


def get_setup_plan(
    requested_mode: str | None = None,
) -> dict:

    discovery = (
        get_discovery_snapshot()
    )


    detected_mode = (
        discovery
        .get(
            "installation",
            {}
        )
        .get(
            "mode"
        )
    )


    mode = (
        requested_mode
        or detected_mode
        or "LAB"
    )

    mode = str(
        mode
    ).upper()


    if mode not in {
        "LAB",
        "PRODUCTION",
    }:

        mode = "LAB"


    camera = discovery[
        "camera"
    ]

    ptz = discovery[
        "ptz"
    ]

    calibration = discovery[
        "calibration"
    ]

    core = discovery[
        "runtime_core"
    ]


    checklist = []


    checklist.append(
        _item(
            "camera",
            "Camera configuration",
            (
                "READY"
                if camera[
                    "configured"
                ]
                else "REQUIRED"
            ),
            (
                f"Camera IP: "
                f"{camera['ip']}"
                if camera[
                    "configured"
                ]
                else
                "Camera configuration is missing."
            ),
        )
    )


    rtsp_ready = bool(
        camera.get(
            "rtsp_path"
        )
        and
        camera.get(
            "rtsp_port"
        )
    )

    checklist.append(
        _item(
            "rtsp",
            "RTSP stream",
            (
                "READY"
                if rtsp_ready
                else "REQUIRED"
            ),
            (
                f"Port "
                f"{camera.get('rtsp_port')} "
                f"{camera.get('rtsp_path')}"
                if rtsp_ready
                else
                "RTSP configuration is incomplete."
            ),
        )
    )


    presets_ready = (
        ptz[
            "preset_count"
        ]
        >= 9
        and
        len(
            ptz[
                "sweep_sequence"
            ]
        )
        > 0
    )

    checklist.append(
        _item(
            "ptz",
            "PTZ presets",
            (
                "READY"
                if presets_ready
                else "REQUIRED"
            ),
            (
                f"{ptz['preset_count']} presets "
                f"| sweep "
                f"{ptz['sweep_sequence']}"
            ),
        )
    )


    checklist.append(
        _item(
            "intrinsics",
            "Camera intrinsics",
            (
                "READY"
                if calibration[
                    "intrinsics"
                ][
                    "exists"
                ]
                else "REQUIRED"
            ),
            (
                "Calibration file detected."
                if calibration[
                    "intrinsics"
                ][
                    "exists"
                ]
                else
                "Camera intrinsics required."
            ),
        )
    )


    rotation_ready = bool(
        calibration[
            "rotation"
        ].get(
            "loaded"
        )
    )

    checklist.append(
        _item(
            "geometry",
            "Preset geometry",
            (
                "READY"
                if rotation_ready
                else "REQUIRED"
            ),
            (
                calibration[
                    "rotation"
                ].get(
                    "model"
                )
                or
                "Preset rotation calibration required."
            ),
        )
    )


    fusion_ready = bool(
        core[
            "cross_preset_fusion"
        ]
        and
        core[
            "pending_mode"
        ]
        == "PRESET_AWARE"
    )

    checklist.append(
        _item(
            "fusion",
            "Cross-preset fusion",
            (
                "READY"
                if fusion_ready
                else "REQUIRED"
            ),
            (
                f"Pending="
                f"{core['pending_mode']} "
                f"| anchor="
                f"{core['anchor_max_age_sec']}s"
            ),
        )
    )


    active_site = (
        discovery
        .get("installation", {})
        .get("active_site")
    )

    distance_loaded = bool(
        calibration[
            "distance"
        ].get(
            "loaded"
        )
    )

    if mode == "LAB":

        distance_status = (
            "AVAILABLE_UNVERIFIED"
            if distance_loaded
            else "DEFERRED"
        )
        distance_detail = (
            "Calibration loaded; "
            "field accuracy not yet validated."
            if distance_loaded
            else
            "Distance calibration is not loaded."
        )

    else:

        wizard_state = {}
        if active_site:
            try:
                wizard_state = load_state(active_site)
            except Exception:
                wizard_state = {}

        verifications = (
            wizard_state
            .get("distance", {})
            .get("verifications", [])
        )

        if distance_loaded and len(verifications) > 0:
            distance_status = "READY"
            distance_detail = (
                f"Calibration verified "
                f"({len(verifications)} field points)."
            )
        elif distance_loaded:
            distance_status = "FIELD_VALIDATION_REQUIRED"
            distance_detail = (
                "Calibration loaded; "
                "field accuracy not yet validated."
            )
        else:
            distance_status = "REQUIRED"
            distance_detail = (
                "Distance calibration is not loaded."
            )


    checklist.append(
        _item(
            "distance",
            "Distance calibration",
            distance_status,
            distance_detail,
        )
    )


    if mode == "LAB":

        checklist.append(
            _item(
                "north",
                "True North",
                "DEFERRED",
                "Skipped in LAB mode.",
            )
        )

        checklist.append(
            _item(
                "gps",
                "GPS",
                "DISABLED",
                "Skipped in LAB mode.",
            )
        )

    else:

        north_ready = False
        north_detail = (
            "Production verification required."
        )
        site_file_candidates = [
            SITE_FILE,
        ]
        if active_site:
            site_file_candidates.append(
                CALIBRATION_ROOT
                / ".manager"
                / "candidates"
                / active_site
                / "site.json"
            )
            site_file_candidates.append(
                CALIBRATION_ROOT
                / "sites"
                / active_site
                / "site.json"
            )

        for s_file in site_file_candidates:
            if s_file and s_file.exists():
                try:
                    s_data = json.loads(
                        s_file.read_text(
                            encoding="utf-8"
                        )
                    )
                    offset = s_data.get(
                        "north_offset_deg"
                    )
                    if (
                        offset is not None
                        and math.isfinite(float(offset))
                    ):
                        north_ready = True
                        north_detail = (
                            f"Bearing offset calibrated: "
                            f"{float(offset):.1f}°"
                        )
                        break
                except Exception:
                    pass

        checklist.append(
            _item(
                "north",
                "True North",
                (
                    "READY"
                    if north_ready
                    else "REQUIRED"
                ),
                north_detail,
            )
        )

        gps_ready = False
        gps_detail = (
            "Production verification required."
        )
        lat = None
        lon = None

        if active_site:
            try:
                registry = list_registered_sites()
                site_rec = (
                    registry
                    .get("sites", {})
                    .get(active_site, {})
                )
                loc = site_rec.get("location", {})
                lat = loc.get("latitude")
                lon = loc.get("longitude")
            except Exception:
                pass

        if lat is None or lon is None:
            loc_candidates = []
            if active_site:
                loc_candidates.append(
                    CALIBRATION_ROOT
                    / ".manager"
                    / "candidates"
                    / active_site
                    / "location.json"
                )
            loc_candidates.append(
                CALIBRATION_ROOT / "location.json"
            )
            for l_file in loc_candidates:
                if l_file and l_file.exists():
                    try:
                        l_data = json.loads(
                            l_file.read_text(
                                encoding="utf-8"
                            )
                        )
                        lat = (
                            l_data.get("camera_lat")
                            or l_data.get("latitude")
                        )
                        lon = (
                            l_data.get("camera_lon")
                            or l_data.get("longitude")
                        )
                        if lat is not None and lon is not None:
                            break
                    except Exception:
                        pass

        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if (
                    math.isfinite(lat_f)
                    and math.isfinite(lon_f)
                    and -90.0 <= lat_f <= 90.0
                    and -180.0 <= lon_f <= 180.0
                ):
                    gps_ready = True
                    gps_detail = (
                        f"Coordinates: "
                        f"{lat_f:.5f}, {lon_f:.5f}"
                    )
            except (TypeError, ValueError):
                pass

        checklist.append(
            _item(
                "gps",
                "GPS",
                (
                    "READY"
                    if gps_ready
                    else "REQUIRED"
                ),
                gps_detail,
            )
        )


    blocking_statuses = {
        "REQUIRED",
        "FIELD_VALIDATION_REQUIRED",
        "MISSING",
        "INVALID",
        "NOT_TESTED",
        "STALE",
        "FAIL",
        "FAILED",
        "BLOCKED",
    }


    hard_blockers = [
        item
        for item
        in checklist
        if str(
            item.get(
                "status",
                ""
            )
        ).upper()
        in blocking_statuses
    ]


    ready = (
        len(
            hard_blockers
        )
        == 0
    )


    return {
        "mode":
            mode,

        "installation":
            discovery[
                "installation"
            ],

        "ready":
            ready,

        "blocker_count":
            len(
                hard_blockers
            ),

        "checklist":
            checklist,

        "next_step": (
            "REUSE_EXISTING_SITE"
            if (
                discovery[
                    "installation"
                ][
                    "detected"
                ]
                == "EXISTING"
                and ready
            )
            else
            "CONTINUE_SETUP"
        ),
    }
