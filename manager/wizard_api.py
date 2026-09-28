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
    send_file,
)

from manager.security import (
    require_manager_session,
)

from manager.services.calibration_lease import (
    CalibrationLeaseBusy,
    CalibrationLeaseExpired,
    CalibrationLeaseMissing,
    create_lease,
    read_lease,
    release_lease,
    renew_lease,
)


from manager.services.calibration_worker_client import (
    capture_preset,
    worker_health,
)


from manager.services.calibration_adapter import (
    build_distance_candidate,
    verify_distance_candidate,
)

from manager.services.runtime_settings import (
    detection_status,
    start_detection,
    stop_detection,
)

from manager.services.site_registry import (
    create_site,
    list_registered_sites,
    set_site_location,
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

            installation_location=
                data.get(
                    "installation_location"
                ),

            latitude=
                data.get(
                    "latitude"
                ),

            longitude=
                data.get(
                    "longitude"
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

    try:

        lease = create_lease(
            site_id
        )


    except (
        CalibrationLeaseBusy,
        CalibrationLeaseExpired,
    ) as exc:

        return jsonify({
            "ok":
                False,

            "error":
                str(
                    exc
                ),

            "lease":
                read_lease(),
        }), 409


    stopped = stop_detection()


    if not stopped.get(
        "ok"
    ):

        release_lease(
            site_id,
            force=True,
        )


        return jsonify(
            stopped
        ), 500


    worker = worker_health()


    if not worker.get(
        "ok"
    ):

        start_detection()

        release_lease(
            site_id,
            force=True,
        )


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

    state[
        "calibration_lease"
    ] = {
        "expires_at":
            lease[
                "expires_at"
            ],

        "ttl_sec":
            lease[
                "ttl_sec"
            ],
    }


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

        lease=lease,
    )


@wizard_bp.post(
    "/api/wizard/<site_id>/calibration/heartbeat"
)
@require_manager_session
def wizard_calibration_heartbeat(
    site_id,
):

    state = load_state(
        site_id
    )


    if (
        state.get(
            "calibration_mode"
        )
        is not True
    ):

        return jsonify({
            "ok":
                False,

            "error":
                "calibration_mode_not_active",
        }), 409


    try:

        lease = renew_lease(
            site_id
        )


    except (
        CalibrationLeaseBusy,
        CalibrationLeaseExpired,
        CalibrationLeaseMissing,
    ) as exc:

        return jsonify({
            "ok":
                False,

            "error":
                str(
                    exc
                ),

            "lease":
                read_lease(),
        }), 409


    state[
        "calibration_lease"
    ] = {
        "expires_at":
            lease[
                "expires_at"
            ],

        "ttl_sec":
            lease[
                "ttl_sec"
            ],
    }


    save_state(
        site_id,
        state,
    )


    return ok(
        lease=lease
    )


@wizard_bp.get(
    "/api/wizard/<site_id>/calibration/lease"
)
@require_manager_session
def wizard_calibration_lease(
    site_id,
):

    lease = read_lease()


    if (
        lease
        and
        lease.get(
            "site_id"
        )
        != site_id
    ):

        return ok(
            active=False,
            lease=None,
        )


    return ok(
        active=bool(
            lease
        ),

        lease=lease,
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


    if started.get(
        "ok"
    ):

        state[
            "calibration_mode"
        ] = False

        state.pop(
            "calibration_lease",
            None,
        )


        release_lease(
            site_id,
            force=True,
        )


    else:

        # Keep state/lease alive for watchdog recovery.
        state[
            "calibration_finish_error"
        ] = started


    save_state(
        site_id,
        state,
    )


    return jsonify({
        **started,

        "state":
            state,

        "lease":
            read_lease(),
    }), (
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


    try:

        # ====================================================
        # EXISTING PROJECT ENGINE
        # calibration.fit_distance_model()
        # ====================================================

        candidate = (
            build_distance_candidate(
                points,

                preset=data.get(
                    "preset"
                ),

                site_id=
                    site_id,
            )
        )


        candidate_file = (
            save_candidate(
                site_id,
                "distance_global.json",
                candidate,
            )
        )


        state = load_state(
            site_id
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
            engine=(
                "calibration."
                "fit_distance_model"
            ),

            candidate=
                candidate,

            candidate_file=str(
                candidate_file
            ),

            runtime_changed=
                False,
        )


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }), 400


@wizard_bp.post(
    "/api/wizard/<site_id>/distance/verify"
)
@require_manager_session
def wizard_distance_verify(
    site_id,
):

    data = payload()


    try:

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

            raise ValueError(
                "ยังไม่มี distance candidate"
            )


        # ====================================================
        # EXISTING PROJECT ENGINE
        # calibration.DistanceModel.estimate()
        # ====================================================

        verification = (
            verify_distance_candidate(
                candidate,

                y_px=data[
                    "y_px"
                ],

                actual_distance_m=data[
                    "actual_distance_m"
                ],
            )
        )


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
            engine=(
                "calibration."
                "DistanceModel.estimate"
            ),

            verification=
                verification,

            runtime_changed=
                False,
        )


    except Exception as exc:

        return jsonify({
            "ok": False,

            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }), 400


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


@wizard_bp.post(
    "/api/wizard/<site_id>/site-location"
)
@require_manager_session
def wizard_site_location(
    site_id,
):

    data = payload()


    try:

        site = set_site_location(
            site_id,

            installation_location=
                data.get(
                    "installation_location"
                ),

            latitude=
                data.get(
                    "latitude"
                ),

            longitude=
                data.get(
                    "longitude"
                ),
        )


        state = load_state(
            site_id
        )


        state[
            "site_location"
        ] = site.get(
            "location"
        )


        save_state(
            site_id,
            state,
        )


        return ok(
            site=site,
            state=state,
            runtime_changed=False,
        )


    except Exception as exc:

        return jsonify({
            "ok": False,
            "error":
                f"{type(exc).__name__}: {exc}",
        }), 400


@wizard_bp.get(
    "/api/wizard/<site_id>/"
    "capture-image/<capture_set>/<filename>"
)
@require_manager_session
def wizard_capture_image(
    site_id,
    capture_set,
    filename,
):

    from manager.services.wizard_store import (
        CANDIDATE_DIR,
        safe_site_id,
    )


    site_id = safe_site_id(
        site_id
    )


    if capture_set not in {
        "main",
        "holdout",
    }:

        return jsonify({
            "ok": False,
            "error":
                "invalid_capture_set",
        }), 400


    if (
        not filename.startswith(
            "preset_"
        )
        or
        not filename.endswith(
            ".jpg"
        )
    ):

        return jsonify({
            "ok": False,
            "error":
                "invalid_filename",
        }), 400


    number = (
        filename[
            len("preset_"):
            -len(".jpg")
        ]
    )


    if (
        not number.isdigit()
        or
        not (
            1
            <= int(number)
            <= 9
        )
    ):

        return jsonify({
            "ok": False,
            "error":
                "invalid_preset",
        }), 400


    path = (
        CANDIDATE_DIR
        / site_id
        / "ptz_captures"
        / capture_set
        / filename
    )


    if not path.exists():

        return jsonify({
            "ok": False,
            "error":
                "capture_not_found",
        }), 404


    response = send_file(
        path,
        mimetype="image/jpeg",
        conditional=True,
    )


    response.headers[
        "Cache-Control"
    ] = (
        "private, no-store, max-age=0"
    )


    return response
