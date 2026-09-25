from __future__ import annotations

from manager.services.discovery import (
    get_discovery_snapshot,
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

    else:

        distance_status = (
            "FIELD_VALIDATION_REQUIRED"
            if distance_loaded
            else "REQUIRED"
        )


    checklist.append(
        _item(
            "distance",
            "Distance calibration",
            distance_status,
            (
                "Calibration loaded; "
                "field accuracy not yet validated."
                if distance_loaded
                else
                "Distance calibration is not loaded."
            ),
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

        checklist.append(
            _item(
                "north",
                "True North",
                "REQUIRED",
                "Production verification required.",
            )
        )

        checklist.append(
            _item(
                "gps",
                "GPS",
                "REQUIRED",
                "Production verification required.",
            )
        )


    hard_blockers = [
        item
        for item
        in checklist
        if item[
            "status"
        ]
        == "REQUIRED"
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
