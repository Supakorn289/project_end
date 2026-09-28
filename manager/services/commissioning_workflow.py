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
        "title": "ตั้งค่าการเชื่อมต่อ Camera",
        "kind": "page",
        "route": "/setup-wizard#camera-connection",
    },

    {
        "id": "camera",
        "title": "ตรวจ Camera / RTSP Candidate",
        "kind": "page",
        "route": "/setup-wizard#camera-connection",
    },

    {
        "id": "ptz",
        "title": "PTZ Presets / Frame Sync",
        "kind": "tools",
        "tools": [
            "ptz.test",
            "ptz.frame_sync",
        ],

        # Preset positions are configured externally.
        # Manager only documents and verifies them.
        "external_setup": True,
        "external_app": "CamFinder",

        "note": (
            "ตั้ง P1-P9 ผ่าน CamFinder ก่อน "
            "แล้วใช้ Manager ตรวจ PTZ และ Frame Sync"
        ),

        "preset_guide": [
            {
                "preset": "P1",
                "relative_deg": 0.0,
                "label": "Reference / Front",
            },
            {
                "preset": "P2",
                "relative_deg": 45.0,
                "label": "Right 45°",
            },
            {
                "preset": "P3",
                "relative_deg": 90.0,
                "label": "Right 90°",
            },
            {
                "preset": "P4",
                "relative_deg": 135.0,
                "label": "Right 135°",
            },
            {
                "preset": "P5",
                "relative_deg": 177.5,
                "label": "Rear / Right side",
            },
            {
                "preset": "P6",
                "relative_deg": -45.0,
                "label": "Left 45°",
            },
            {
                "preset": "P7",
                "relative_deg": -90.0,
                "label": "Left 90°",
            },
            {
                "preset": "P8",
                "relative_deg": -135.0,
                "label": "Left 135°",
            },
            {
                "preset": "P9",
                "relative_deg": -177.5,
                "label": "Rear / Left side",
            },
        ],
    },

    {
        "id": "intrinsics",
        "title": "Camera Intrinsics",
        "kind": "page",
        "route": "/setup-wizard#intrinsics",
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
        "title": "ตั้งค่า / ทดสอบ Telegram",
        "kind": "page",
        "route": "/setup-wizard#telegram",
    },

    {
        "id": "final_verification",
        "title": "Final Candidate Verification",
        "kind": "page",
        "route": "/setup-wizard#final-verification",
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
