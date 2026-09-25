from __future__ import annotations

from pathlib import Path


ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

PYTHON = (
    ROOT
    / "venv"
    / "bin"
    / "python"
)


TOOLS = {

    # ========================================================
    # Safe / inspection
    # ========================================================

    "preflight.offline": {
        "label": "Offline Preflight",
        "category": "verification",
        "kind": "cli",
        "script": "preflight.py",
        "args": ["--offline"],
        "requires_detection_stopped": False,
        "hardware_motion": False,
        "heavy": False,
        "runtime_write": False,
        "description":
            "ตรวจ config, calibration และ dependencies "
            "โดยไม่ใช้กล้องจริง",
    },

    "model.inspect": {
        "label": "Inspect AI Model",
        "category": "verification",
        "kind": "cli",
        "script": "inspect_model.py",
        "args": [],
        "requires_detection_stopped": True,
        "hardware_motion": False,
        "heavy": True,
        "runtime_write": False,
        "description":
            "ตรวจ model artifact และ class contract",
    },


    # ========================================================
    # Existing hardware tests
    # ========================================================

    "camera.test": {
        "label": "Camera Test",
        "category": "camera",
        "kind": "cli",
        "script": "test_camera.py",
        "args": [],
        "requires_detection_stopped": True,
        "hardware_motion": False,
        "heavy": False,
        "runtime_write": False,
        "description":
            "ใช้ Camera Test เดิม ตรวจ RTSP และ fresh frames",
    },

    "ptz.test": {
        "label": "PTZ Preset Test",
        "category": "ptz",
        "kind": "cli",
        "script": "test_ptz.py",
        "args": [],
        "requires_detection_stopped": True,
        "hardware_motion": True,
        "heavy": False,
        "runtime_write": False,
        "description":
            "ใช้ PTZ Test เดิม เดิน preset ตาม sweep sequence",
    },

    "ptz.frame_sync": {
        "label": "PTZ Frame Sync Test",
        "category": "ptz",
        "kind": "cli",
        "script": "test_ptz_frame_sync.py",
        "args": [],
        "requires_detection_stopped": True,
        "hardware_motion": True,
        "heavy": False,
        "runtime_write": False,
        "description":
            "ตรวจ fresh/stable frame หลัง PTZ เคลื่อน",
    },

    "telegram.test": {
        "label": "Telegram Test",
        "category": "notification",
        "kind": "cli",
        "script": "test_telegram.py",
        "args": [],
        "requires_detection_stopped": False,
        "hardware_motion": False,
        "heavy": False,
        "runtime_write": False,
        "description":
            "ใช้ระบบแจ้งเตือน Telegram เดิม",
    },

    "full_sweep": {
        "label": "Full Sweep Test",
        "category": "verification",
        "kind": "cli",
        "script": "test_full_sweep.py",
        "args": ["--cycles", "1"],
        "requires_detection_stopped": True,
        "hardware_motion": True,
        "heavy": True,
        "runtime_write": False,
        "description":
            "ใช้ Full Sweep เดิม PTZ + AI + consensus",
    },


    # ========================================================
    # Existing calibration engines exposed through Web UI
    # ========================================================

    "intrinsics.calibrate": {
        "label": "Camera Intrinsics",
        "category": "calibration",
        "kind": "ui_adapter",
        "script": "calibrate_intrinsics.py",
        "route": "/setup-wizard",
        "runtime_write": False,
        "description":
            "นำ Intrinsics Calibration เดิมมาใช้ผ่าน Wizard",
    },

    "distance.calibrate": {
        "label": "Distance Calibration",
        "category": "calibration",
        "kind": "ui_adapter",
        "script": "calibrate_distance.py",
        "route": "/setup-wizard",
        "engine": [
            "calibration.fit_distance_model",
            "calibration.save_distance_model",
        ],
        "runtime_write": False,
        "description":
            "Capture + Mark Y ผ่านเว็บ "
            "แต่ใช้ Distance Engine เดิม",
    },

    "distance.verify": {
        "label": "Distance Verification",
        "category": "calibration",
        "kind": "ui_adapter",
        "script": "verify_distance.py",
        "route": "/setup-wizard",
        "runtime_write": False,
        "description":
            "Verify model ระยะทางด้วย workflow เดิม",
    },

    "bearing.calibrate": {
        "label": "True North / Bearing",
        "category": "calibration",
        "kind": "ui_adapter",
        "script": "calibrate_bearing.py",
        "route": "/setup-wizard",
        "engine": [
            "calibration.save_site_calibration",
        ],
        "runtime_write": False,
        "description":
            "ใช้ Bearing Calibration format เดิม",
    },

    "bearing.verify": {
        "label": "Bearing Verification",
        "category": "calibration",
        "kind": "ui_adapter",
        "script": "verify_bearing.py",
        "route": "/setup-wizard",
        "runtime_write": False,
        "description":
            "Verification ของ Bearing/True North",
    },

    "geometry.mark": {
        "label": "Cross-Preset Landmark",
        "category": "geometry",
        "kind": "ui_adapter",
        "script": "refine_overlap_marks_v3.py",
        "route": "/setup-wizard",
        "runtime_write": False,
        "description":
            "Mark landmark เดียวกันข้าม preset ผ่าน Browser",
    },
}


GEOMETRY_SOLVERS = [
    "solve_final_mixed_rotation_AB_v3.py",
    "fit_preset_geometry_v3_1.py",
    "fit_preset_geometry_v3.py",
]


def _script_info(
    script,
):

    path = (
        ROOT
        / script
    )

    return {
        "path":
            str(
                path
            ),

        "exists":
            path.exists(),
    }


def get_catalog():

    output = {}


    for tool_id, spec in (
        TOOLS.items()
    ):

        item = dict(
            spec
        )

        script = item.get(
            "script"
        )


        if script:

            item.update(
                _script_info(
                    script
                )
            )


        if item.get(
            "kind"
        ) == "cli":

            item[
                "command"
            ] = [
                str(
                    PYTHON
                ),
                str(
                    ROOT
                    /
                    item[
                        "script"
                    ]
                ),
                *item.get(
                    "args",
                    [],
                ),
            ]


        output[
            tool_id
        ] = item


    geometry = []


    for filename in (
        GEOMETRY_SOLVERS
    ):

        path = (
            ROOT
            / filename
        )

        geometry.append({
            "name":
                filename,

            "path":
                str(
                    path
                ),

            "exists":
                path.exists(),
        })


    return {
        "tools":
            output,

        "geometry_solver_candidates":
            geometry,
    }


def get_tool(
    tool_id,
):

    catalog = (
        get_catalog()[
            "tools"
        ]
    )


    if tool_id not in catalog:

        raise KeyError(
            f"Unknown tool: {tool_id}"
        )


    return catalog[
        tool_id
    ]
