from __future__ import annotations

import json
import math

from pathlib import Path

import numpy as np

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)

from manager.security import (
    require_manager_session,
)

from manager.services.calibration_worker_client import (
    capture_preset,
    worker_health,
)

from manager.services.runtime_settings import (
    detection_status,
    start_detection,
    stop_detection,
)

from manager.services.site_registry import (
    create_site,
    list_registered_sites,
)

from manager.services.wizard_store import (
    load_state,
    save_candidate,
    save_state,
)


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

CALIBRATION_ROOT = (
    PROJECT_ROOT
    / "calibration"
)


wizard_bp = Blueprint(
    "manager_wizard",
    __name__,
)


def ok(
    **kwargs,
):

    output = {
        "ok": True,
    }

    output.update(
        kwargs
    )

    return jsonify(
        output
    )


def payload():

    return (
        request.get_json(
            silent=True
        )
        or {}
    )


def signed_angle(
    value,
):

    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


@wizard_bp.get(
    "/setup-wizard"
)
def wizard_page():

    return render_template(
        "wizard.html"
    )


@wizard_bp.get(
    "/api/wizard/sites"
)
def wizard_sites():

    return jsonify(
        list_registered_sites()
    )


@wizard_bp.get(
    "/api/wizard/state/<site_id>"
)
def wizard_state(
    site_id,
):

    try:

        return ok(
            state=load_state(
                site_id
            )
        )

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


@wizard_bp.post(
    "/api/wizard/site/new"
)
@require_manager_session
def wizard_new_site():

    data = payload()

    try:

        record = create_site(
            site_id=data.get(
                "site_id",
                "",
            ),

            mode=data.get(
                "mode",
                "LAB",
            ),

            display_name=data.get(
                "display_name"
            ),
        )


        state = load_state(
            record[
                "site_id"
            ],
            record[
                "mode"
            ],
        )


        state[
            "mode"
        ] = record[
            "mode"
        ]

        state[
            "step"
        ] = "DEVICE"


        save_state(
            record[
                "site_id"
            ],
            state,
        )


        return ok(
            site=record,
            state=state,
        )


    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


@wizard_bp.post(
    "/api/wizard/<site_id>/calibration/start"
)
@require_manager_session
def wizard_calibration_start(
    site_id,
):

    stopped = stop_detection()

    if not stopped.get(
        "ok"
    ):

        return jsonify(
            stopped
        ), 500


    worker = worker_health()

    if not worker.get(
        "ok"
    ):

        start_detection()

        return jsonify(
            worker
        ), 500


    state = load_state(
        site_id
    )

    state[
        "calibration_mode"
    ] = True

    state[
        "step"
    ] = "PTZ_CAPTURE"

    save_state(
        site_id,
        state,
    )


    return ok(
        state=state,
        detection=(
            detection_status()
        ),
        worker=worker,
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/calibration/finish"
)
@require_manager_session
def wizard_calibration_finish(
    site_id,
):

    started = start_detection()

    state = load_state(
        site_id
    )

    state[
        "calibration_mode"
    ] = False

    save_state(
        site_id,
        state,
    )


    return jsonify(
        started
    ), (
        200
        if started.get(
            "ok"
        )
        else 500
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/capture"
)
@require_manager_session
def wizard_capture(
    site_id,
):

    data = payload()

    capture_set = data.get(
        "capture_set",
        "main",
    )

    result = capture_preset(
        site_id,
        data.get(
            "preset"
        ),
        capture_set,
    )


    if result.get(
        "ok"
    ):

        state = load_state(
            site_id
        )

        state[
            "captures"
        ][
            capture_set
        ][
            str(
                result[
                    "preset"
                ]
            )
        ] = result


        save_state(
            site_id,
            state,
        )


    return jsonify(
        result
    ), (
        200
        if result.get(
            "ok"
        )
        else 400
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/distance/fit"
)
@require_manager_session
def wizard_distance_fit(
    site_id,
):

    data = payload()

    points = data.get(
        "points",
        [],
    )


    if len(points) < 3:

        return jsonify({
            "ok": False,
            "error":
                "ต้องมีอย่างน้อย 3 จุด",
        }), 400


    distances = np.asarray(
        [
            float(
                p[
                    "distance_m"
                ]
            )
            for p in points
        ],
        dtype=np.float64,
    )

    y_pixels = np.asarray(
        [
            float(
                p[
                    "y_px"
                ]
            )
            for p in points
        ],
        dtype=np.float64,
    )


    if np.any(
        distances <= 0
    ):

        return jsonify({
            "ok": False,
            "error":
                "distance ต้องมากกว่า 0",
        }), 400


    x = (
        1.0
        /
        distances
    )


    matrix = np.column_stack(
        [
            np.ones_like(
                x
            ),
            x,
        ]
    )


    params, _, _, _ = (
        np.linalg.lstsq(
            matrix,
            y_pixels,
            rcond=None,
        )
    )


    H = float(
        params[0]
    )

    K = float(
        params[1]
    )


    predicted_y = (
        H
        +
        K
        /
        distances
    )


    residual = (
        y_pixels
        -
        predicted_y
    )


    rmse = float(
        np.sqrt(
            np.mean(
                residual
                ** 2
            )
        )
    )


    state = load_state(
        site_id
    )


    first_capture = None

    for item in (
        state
        .get(
            "captures",
            {}
        )
        .get(
            "main",
            {}
        )
        .values()
    ):

        first_capture = item
        break


    frame_width = int(
        (
            first_capture
            or {}
        ).get(
            "width",
            1280,
        )
    )

    frame_height = int(
        (
            first_capture
            or {}
        ).get(
            "height",
            720,
        )
    )


    candidate = {
        "version": 3,
        "H": H,
        "K": K,
        "pixel_rmse": rmse,
        "frame_width":
            frame_width,
        "frame_height":
            frame_height,
        "points":
            len(points),
        "min_distance_m":
            float(
                distances.min()
            ),
        "max_distance_m":
            float(
                distances.max()
            ),
        "samples": [
            {
                "distance_m":
                    float(d),
                "y_px":
                    float(y),
            }
            for d, y
            in zip(
                distances,
                y_pixels,
            )
        ],
        "status":
            "CANDIDATE",
    }


    candidate_file = (
        save_candidate(
            site_id,
            "distance_global.json",
            candidate,
        )
    )


    state[
        "distance"
    ][
        "points"
    ] = points

    state[
        "distance"
    ][
        "candidate"
    ] = candidate

    state[
        "step"
    ] = "DISTANCE_VERIFY"


    save_state(
        site_id,
        state,
    )


    return ok(
        candidate=candidate,
        candidate_file=str(
            candidate_file
        ),
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/distance/verify"
)
@require_manager_session
def wizard_distance_verify(
    site_id,
):

    data = payload()

    state = load_state(
        site_id
    )

    candidate = (
        state[
            "distance"
        ][
            "candidate"
        ]
    )


    if not candidate:

        return jsonify({
            "ok": False,
            "error":
                "ยังไม่มี distance candidate",
        }), 400


    y_px = float(
        data[
            "y_px"
        ]
    )

    actual = float(
        data[
            "actual_distance_m"
        ]
    )


    denominator = (
        y_px
        -
        float(
            candidate[
                "H"
            ]
        )
    )


    if denominator <= 0:

        return jsonify({
            "ok": False,
            "error":
                "Y อยู่นอกช่วง model",
        }), 400


    predicted = (
        float(
            candidate[
                "K"
            ]
        )
        /
        denominator
    )


    signed_error = (
        predicted
        -
        actual
    )

    abs_error = abs(
        signed_error
    )

    percent = (
        abs_error
        /
        actual
        * 100.0
    )


    if percent <= 5.0:

        grade = "EXCELLENT"

    elif percent <= 10.0:

        grade = "GOOD"

    elif percent <= 15.0:

        grade = "FAIR"

    else:

        grade = "RECALIBRATE"


    verification = {
        "y_px": y_px,
        "actual_distance_m":
            actual,
        "predicted_distance_m":
            predicted,
        "signed_error_m":
            signed_error,
        "absolute_error_m":
            abs_error,
        "percent_error":
            percent,
        "grade":
            grade,
    }


    state[
        "distance"
    ][
        "verifications"
    ].append(
        verification
    )

    save_state(
        site_id,
        state,
    )


    return ok(
        verification=verification
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/geometry/mark"
)
@require_manager_session
def wizard_geometry_mark(
    site_id,
):

    data = payload()

    pair = str(
        data[
            "pair"
        ]
    )

    phase = str(
        data.get(
            "phase",
            "train",
        )
    )


    if phase not in {
        "train",
        "holdout",
    }:

        return jsonify({
            "ok": False,
            "error":
                "invalid phase",
        }), 400


    mark = {
        "x_a_px":
            float(
                data[
                    "x_a_px"
                ]
            ),

        "y_a_px":
            float(
                data[
                    "y_a_px"
                ]
            ),

        "x_b_px":
            float(
                data[
                    "x_b_px"
                ]
            ),

        "y_b_px":
            float(
                data[
                    "y_b_px"
                ]
            ),
    }


    state = load_state(
        site_id
    )


    state[
        "geometry"
    ][
        phase
    ].setdefault(
        pair,
        [],
    ).append(
        mark
    )


    save_state(
        site_id,
        state,
    )


    return ok(
        count=len(
            state[
                "geometry"
            ][
                phase
            ][
                pair
            ]
        ),
        mark=mark,
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/geometry/clear"
)
@require_manager_session
def wizard_geometry_clear(
    site_id,
):

    data = payload()

    phase = str(
        data.get(
            "phase",
            "train",
        )
    )

    pair = str(
        data[
            "pair"
        ]
    )

    state = load_state(
        site_id
    )

    state[
        "geometry"
    ][
        phase
    ][
        pair
    ] = []

    save_state(
        site_id,
        state,
    )

    return ok()


@wizard_bp.get(
    "/api/wizard/geometry/runtime-schema"
)
def wizard_runtime_schema():

    candidates = [
        CALIBRATION_ROOT
        / "preset_rotation_ACTIVE.json",

        CALIBRATION_ROOT
        / "sites"
        / "current-site-20260921"
        / "preset_rotation.json",
    ]


    path = next(
        (
            p
            for p in candidates
            if p.exists()
        ),
        None,
    )


    if path is None:

        return jsonify({
            "ok": False,
            "error":
                "active preset rotation not found",
        }), 404


    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


    presets = data.get(
        "presets",
        {}
    )


    schema = {
        "path":
            str(
                path.resolve()
            ),
        "top_keys":
            sorted(
                data.keys()
            ),
        "model":
            data.get(
                "model"
            ),
        "status":
            data.get(
                "status"
            ),
        "preset_keys": {},
    }


    for key, entry in (
        presets.items()
    ):

        if isinstance(
            entry,
            dict,
        ):

            matrix_fields = []

            for name, value in (
                entry.items()
            ):

                if (
                    isinstance(
                        value,
                        list,
                    )
                    and
                    len(value) == 3
                    and
                    all(
                        isinstance(
                            row,
                            list,
                        )
                        and
                        len(row) == 3
                        for row
                        in value
                    )
                ):

                    matrix_fields.append(
                        name
                    )


            schema[
                "preset_keys"
            ][
                str(key)
            ] = {
                "keys":
                    sorted(
                        entry.keys()
                    ),
                "matrix_fields":
                    matrix_fields,
            }


    return ok(
        schema=schema
    )
