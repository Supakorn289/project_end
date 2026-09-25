from __future__ import annotations


BASE = [

    {
        "id": "site",
        "title": "เลือกหรือสร้างพื้นที่",
        "kind": "page",
        "route": "/setup-wizard",
    },

    {
        "id": "device",
        "title": "ตั้งค่า Camera / IP / Protocol",
        "kind": "page",
        "route": "/settings",
    },

    {
        "id": "camera",
        "title": "ตรวจ Camera / RTSP",
        "kind": "tool",
        "tool": "camera.test",
    },

    {
        "id": "ptz",
        "title": "ตรวจ PTZ / Presets / Frame Sync",
        "kind": "tools",
        "tools": [
            "ptz.test",
            "ptz.frame_sync",
        ],
    },

    {
        "id": "intrinsics",
        "title": "Camera Intrinsics",
        "kind": "tool",
        "tool": "intrinsics.calibrate",
    },

    {
        "id": "distance",
        "title": "Calibration ระยะทาง",
        "kind": "tools",
        "tools": [
            "distance.calibrate",
            "distance.verify",
        ],
    },

    {
        "id": "geometry",
        "title": "Cross-Preset Geometry",
        "kind": "tool",
        "tool": "geometry.mark",
    },

    {
        "id": "north",
        "title": "True North / Bearing",
        "kind": "tools",
        "tools": [
            "bearing.calibrate",
            "bearing.verify",
        ],
    },

    {
        "id": "notification",
        "title": "Notification",
        "kind": "tool",
        "tool": "telegram.test",
    },

    {
        "id": "preflight",
        "title": "System Preflight",
        "kind": "tools",
        "tools": [
            "model.inspect",
            "preflight.offline",
        ],
    },

    {
        "id": "sweep",
        "title": "Full Sweep Verification",
        "kind": "tool",
        "tool": "full_sweep",
    },

    {
        "id": "activate",
        "title": "Review & Activate Site",
        "kind": "activation",
    },
]


def get_workflow(
    *,
    installation="EXISTING",
    mode="LAB",
):

    installation = str(
        installation
    ).upper()

    mode = str(
        mode
    ).upper()


    if installation not in {
        "EXISTING",
        "NEW",
    }:

        installation = (
            "EXISTING"
        )


    if mode not in {
        "LAB",
        "PRODUCTION",
    }:

        mode = "LAB"


    steps = []


    for number, source in enumerate(
        BASE,
        start=1,
    ):

        step = dict(
            source
        )

        step[
            "number"
        ] = number


        if installation == "EXISTING":

            if step[
                "id"
            ] in {
                "intrinsics",
                "distance",
                "geometry",
                "north",
            }:

                step[
                    "policy"
                ] = "REUSE_OR_RECALIBRATE"

            else:

                step[
                    "policy"
                ] = "OPTIONAL_CHECK"


        else:

            step[
                "policy"
            ] = "REQUIRED"


        if (
            mode == "LAB"
            and
            step[
                "id"
            ] in {
                "north",
            }
        ):

            step[
                "policy"
            ] = "OPTIONAL"


        if (
            mode == "LAB"
            and
            step[
                "id"
            ] in {
                "notification",
                "sweep",
            }
        ):

            step[
                "policy"
            ] = "RECOMMENDED"


        if (
            mode == "PRODUCTION"
            and
            step[
                "id"
            ] in {
                "north",
                "preflight",
                "sweep",
            }
        ):

            step[
                "policy"
            ] = "REQUIRED"


        steps.append(
            step
        )


    return {
        "installation":
            installation,

        "mode":
            mode,

        "steps":
            steps,
    }
