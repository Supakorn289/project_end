from __future__ import annotations

import hashlib
import json
import math

from pathlib import Path


from manager.services.site_registry import (
    list_registered_sites,
)

from manager.services.wizard_store import (
    CANDIDATE_DIR,
    STATE_DIR,
    safe_site_id,
)


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

CALIBRATION_ROOT = (
    PROJECT_ROOT
    / "calibration"
)


ACTIVE_INTRINSICS = (
    CALIBRATION_ROOT
    / "camera_intrinsics.json"
)

ACTIVE_DISTANCE = (
    CALIBRATION_ROOT
    / "distance_global.json"
)

ACTIVE_GEOMETRY = (
    CALIBRATION_ROOT
    / "preset_rotation_ACTIVE.json"
)

ACTIVE_SITE = (
    CALIBRATION_ROOT
    / "site.json"
)


# ============================================================
# Helpers
# ============================================================

def _read_json(
    path,
):

    path = Path(
        path
    )


    if not path.exists():

        return None


    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


def _sha256(
    path,
):

    digest = hashlib.sha256()


    with Path(
        path
    ).open(
        "rb"
    ) as handle:

        while True:

            block = handle.read(
                1024 * 1024
            )


            if not block:
                break


            digest.update(
                block
            )


    return digest.hexdigest()


def _wizard_state(
    site_id,
):

    path = (
        STATE_DIR
        / f"{site_id}.json"
    )


    data = _read_json(
        path
    )


    if isinstance(
        data,
        dict,
    ):

        return data


    return {}


def _candidate_path(
    site_id,
    filename,
):

    return (
        CANDIDATE_DIR
        / site_id
        / filename
    )


def _candidate_json(
    site_id,
    filename,
):

    return _read_json(
        _candidate_path(
            site_id,
            filename,
        )
    )


def _valid_coordinates(
    latitude,
    longitude,
):

    try:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

    except (
        TypeError,
        ValueError,
    ):

        return False


    return bool(
        math.isfinite(
            latitude
        )
        and
        math.isfinite(
            longitude
        )
        and
        -90.0
        <= latitude
        <= 90.0
        and
        -180.0
        <= longitude
        <= 180.0
    )


def _valid_intrinsics(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return False


    return bool(
        data.get(
            "status"
        )
        ==
        "intrinsics_calibrated"

        and

        data.get(
            "valid_for_production"
        )
        is True

        and

        isinstance(
            data.get(
                "camera_matrix"
            ),
            list,
        )

        and

        isinstance(
            data.get(
                "distortion_coefficients"
            ),
            list,
        )
    )


def _valid_distance(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return False


    try:

        H = float(
            data[
                "H"
            ]
        )

        K = float(
            data[
                "K"
            ]
        )

        rmse = float(
            data[
                "pixel_rmse"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        return False


    return bool(
        math.isfinite(
            H
        )
        and
        math.isfinite(
            K
        )
        and
        math.isfinite(
            rmse
        )
        and
        K > 0
        and
        rmse >= 0
    )


def _valid_geometry(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return False


    presets = data.get(
        "presets"
    )


    return bool(
        data.get(
            "model"
        )
        ==
        "calibrated-global-raw-ray-rotation"

        and

        isinstance(
            presets,
            dict,
        )

        and

        len(
            presets
        )
        >= 9
    )


def _valid_north(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return False


    try:

        value = float(
            data[
                "north_offset_deg"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        return False


    return math.isfinite(
        value
    )


# ============================================================
# Verification
# ============================================================

def verify_site_candidate(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )


    registry = (
        list_registered_sites()
    )


    sites = (
        registry.get(
            "sites",
            {}
        )
    )


    record = sites.get(
        site_id
    )


    state = _wizard_state(
        site_id
    )


    mode = str(
        (
            record
            or {}
        ).get(
            "mode"
        )
        or
        state.get(
            "mode"
        )
        or
        "LAB"
    ).upper()


    if mode not in {
        "LAB",
        "PRODUCTION",
    }:

        mode = "LAB"


    existing_active = bool(
        (
            record
            or {}
        ).get(
            "runtime_active",
            False,
        )
    )


    checks = []
    blockers = []
    warnings = []


    def add(
        key,
        label,
        *,
        required,
        ok,
        detail,
        source=None,
        status=None,
    ):

        if status is None:

            if ok:
                status = "PASS"

            elif required:
                status = "BLOCKED"

            else:
                status = "WARN"


        item = {
            "key":
                key,

            "label":
                label,

            "required":
                bool(
                    required
                ),

            "ok":
                bool(
                    ok
                ),

            "status":
                status,

            "detail":
                str(
                    detail
                ),

            "source":
                source,
        }


        checks.append(
            item
        )


        if (
            required
            and
            not ok
        ):

            blockers.append(
                item
            )


        elif (
            status
            ==
            "WARN"
        ):

            warnings.append(
                item
            )


        return item


    # ========================================================
    # Site registration
    # ========================================================

    add(
        "site",
        "Site registration",

        required=True,

        ok=(
            record
            is not None
        ),

        detail=(
            (
                f"{site_id} | "
                f"{mode}"
            )
            if record
            else
            "Site ยังไม่ได้ลงทะเบียน"
        ),

        source=
            "manager-registry",
    )


    # ========================================================
    # Location metadata
    # ========================================================

    location = (
        (
            record
            or {}
        ).get(
            "location"
        )
        or
        state.get(
            "site_location"
        )
        or
        {}
    )


    location_name = str(
        location.get(
            "installation_location"
        )
        or ""
    ).strip()


    add(
        "location_name",
        "Installation location",

        required=False,

        ok=bool(
            location_name
        ),

        detail=(
            location_name
            if location_name
            else
            "ยังไม่ได้กรอกชื่อ/รายละเอียดสถานที่"
        ),

        source=
            "site-registry",
    )


    coordinates_ok = (
        _valid_coordinates(
            location.get(
                "latitude"
            ),

            location.get(
                "longitude"
            ),
        )
    )


    add(
        "gps_location",
        "GPS location",

        required=(
            mode
            ==
            "PRODUCTION"
        ),

        ok=
            coordinates_ok,

        detail=(
            "Latitude / Longitude พร้อม"
            if coordinates_ok
            else
            "ยังไม่มี Latitude / Longitude ที่ถูกต้อง"
        ),

        source=
            "site-registry",
    )


    # ========================================================
    # Camera
    # ========================================================

    camera_candidate = (
        _candidate_json(
            site_id,
            "camera_connection.json",
        )
    )


    camera_state = (
        state.get(
            "camera_connection",
            {}
        )
        or {}
    )


    camera_env = (
        (
            camera_candidate
            or {}
        ).get(
            "runtime_env",
            {}
        )
        or {}
    )


    camera_configured = bool(
        camera_env.get(
            "CAMERA_IP"
        )
        and
        camera_env.get(
            "CAMERA_USER"
        )
        and
        camera_env.get(
            "CAMERA_PWD"
        )
        and
        camera_env.get(
            "RTSP_PORT"
        )
        and
        camera_env.get(
            "RTSP_PATH"
        )
    )


    if (
        not camera_configured
        and
        existing_active
    ):

        add(
            "camera_config",
            "Camera configuration",

            required=True,

            ok=True,

            status="WARN",

            detail=(
                "ใช้ Active Runtime เดิม "
                "เพราะ Site นี้กำลัง Active อยู่"
            ),

            source=
                "active-runtime",
        )

    else:

        add(
            "camera_config",
            "Camera configuration",

            required=True,

            ok=
                camera_configured,

            detail=(
                "Camera Candidate พร้อม"
                if camera_configured
                else
                "ยังไม่มี Camera Candidate ที่ครบ"
            ),

            source=
                "candidate",
        )


    camera_tested = bool(
        camera_state.get(
            "tested"
        )
    )


    add(
        "camera_test",
        "Camera / RTSP test",

        required=True,

        ok=
            camera_tested,

        detail=(
            "Camera Candidate ผ่านการทดสอบ"
            if camera_tested
            else
            "ยังไม่ได้ Test Camera Candidate"
        ),

        source=
            "wizard-state",
    )


    # ========================================================
    # Intrinsics
    # ========================================================

    intrinsics_candidate_path = (
        _candidate_path(
            site_id,
            "camera_intrinsics.json",
        )
    )


    intrinsics_candidate = (
        _read_json(
            intrinsics_candidate_path
        )
    )


    intrinsics_source = None
    intrinsics_path = None
    intrinsics_data = None


    if _valid_intrinsics(
        intrinsics_candidate
    ):

        intrinsics_source = (
            "candidate"
        )

        intrinsics_path = (
            intrinsics_candidate_path
        )

        intrinsics_data = (
            intrinsics_candidate
        )


    elif (
        existing_active
        and
        _valid_intrinsics(
            _read_json(
                ACTIVE_INTRINSICS
            )
        )
    ):

        intrinsics_source = (
            "active-runtime"
        )

        intrinsics_path = (
            ACTIVE_INTRINSICS
        )

        intrinsics_data = (
            _read_json(
                ACTIVE_INTRINSICS
            )
        )


    intrinsics_ok = bool(
        intrinsics_data
    )


    add(
        "intrinsics",
        "Camera Intrinsics",

        required=True,

        ok=
            intrinsics_ok,

        detail=(
            (
                "Intrinsics พร้อม | "
                f"{intrinsics_source}"
            )
            if intrinsics_ok
            else
            "ยังไม่มี Intrinsics ที่ผ่าน validation"
        ),

        source=
            intrinsics_source,
    )


    intrinsics_hash = None


    if (
        intrinsics_path
        and
        intrinsics_path.exists()
    ):

        try:

            intrinsics_hash = (
                _sha256(
                    intrinsics_path
                )
            )

        except OSError:
            pass


    # ========================================================
    # PTZ preset evidence
    # ========================================================

    main_captures = (
        state.get(
            "captures",
            {}
        )
        .get(
            "main",
            {}
        )
        or {}
    )


    captured_presets = {
        str(
            key
        )
        for key
        in main_captures.keys()
    }


    expected_presets = {
        str(
            value
        )
        for value
        in range(
            1,
            10,
        )
    }


    ptz_capture_ok = (
        expected_presets
        <=
        captured_presets
    )


    if (
        not ptz_capture_ok
        and
        existing_active
    ):

        add(
            "ptz_presets",
            "PTZ P1-P9 evidence",

            required=False,

            ok=True,

            status="WARN",

            detail=(
                "Existing Active Site: "
                "ไม่บังคับ Capture P1-P9 ซ้ำ "
                "แต่ Full Sweep จะตรวจอีกครั้งตอน Activation"
            ),

            source=
                "active-runtime",
        )

    else:

        add(
            "ptz_presets",
            "PTZ P1-P9 evidence",

            required=True,

            ok=
                ptz_capture_ok,

            detail=(
                (
                    "Capture P1-P9 ครบ"
                )
                if ptz_capture_ok
                else
                (
                    f"พบ {len(captured_presets)}/9 presets"
                )
            ),

            source=
                "wizard-captures",
        )


    # ========================================================
    # Distance model
    # ========================================================

    distance_candidate = (
        _candidate_json(
            site_id,
            "distance_global.json",
        )
    )


    distance_source = None
    distance_data = None


    if _valid_distance(
        distance_candidate
    ):

        distance_source = (
            "candidate"
        )

        distance_data = (
            distance_candidate
        )


    elif (
        existing_active
        and
        _valid_distance(
            _read_json(
                ACTIVE_DISTANCE
            )
        )
    ):

        distance_source = (
            "active-runtime"
        )

        distance_data = (
            _read_json(
                ACTIVE_DISTANCE
            )
        )


    add(
        "distance",
        "Distance calibration",

        required=True,

        ok=bool(
            distance_data
        ),

        detail=(
            (
                "Distance model พร้อม | "
                f"{distance_source}"
            )
            if distance_data
            else
            "ยังไม่มี Distance calibration"
        ),

        source=
            distance_source,
    )


    verifications = (
        state.get(
            "distance",
            {}
        ).get(
            "verifications",
            []
        )
        or []
    )


    last_verification = (
        verifications[-1]
        if verifications
        else None
    )


    distance_grade = (
        (
            last_verification
            or {}
        ).get(
            "grade"
        )
    )


    distance_verified = bool(
        last_verification
        and
        distance_grade
        !=
        "RECALIBRATE"
    )


    add(
        "distance_verify",
        "Distance verification",

        required=(
            mode
            ==
            "PRODUCTION"
        ),

        ok=
            distance_verified,

        detail=(
            (
                f"Latest grade: "
                f"{distance_grade}"
            )
            if last_verification
            else
            "ยังไม่มี Field Verification"
        ),

        source=
            "wizard-state",
    )


    # ========================================================
    # Cross-preset Geometry
    # ========================================================

    geometry_candidate_path = (
        _candidate_path(
            site_id,
            "preset_rotation.json",
        )
    )


    geometry_candidate = (
        _read_json(
            geometry_candidate_path
        )
    )


    geometry_state = (
        state.get(
            "geometry",
            {}
        )
        or {}
    )


    solver_result = (
        geometry_state.get(
            "solver_result",
            {}
        )
        or {}
    )


    geometry_source = None
    geometry_data = None


    override_meta = (
        (
            geometry_candidate
            or {}
        )
        .get(
            "operator_override",
            {},
        )
        or {}
    )


    geometry_gate = (
        (
            geometry_candidate
            or {}
        )
        .get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    forced_geometry = bool(
        (
            geometry_candidate
            or {}
        ).get(
            "status"
        )
        ==
        "FORCED_CANDIDATE_NOT_INSTALLED"

        and

        override_meta.get(
            "enabled"
        )
        is True

        and

        override_meta.get(
            "acknowledged_holdout_failure"
        )
        is True

        and

        geometry_gate.get(
            "passed"
        )
        is False

        and

        solver_result.get(
            "forced_override"
        )
        is True
    )


    # A historical holdout PASS is not a fresh solver proof. A LAB-only
    # operator-approved legacy trial is tracked separately and always WARNs.
    from manager.services.legacy_geometry_lab import preview as _legacy_trial_preview
    legacy_trial = _legacy_trial_preview(site_id)
    lab_legacy_accepted = bool(mode == "LAB" and legacy_trial.get("accepted") is True)

    solver_geometry_accepted = bool(
        solver_result.get(
            "passed"
        )
        is True

        or

        forced_geometry
    )


    if (
        _valid_geometry(
            geometry_candidate
        )
        and
        (solver_geometry_accepted or lab_legacy_accepted)
    ):

        geometry_source = (
            "candidate"
        )

        geometry_data = (
            geometry_candidate
        )


    elif (
        existing_active
        and
        _valid_geometry(
            _read_json(
                ACTIVE_GEOMETRY
            )
        )
    ):

        geometry_source = (
            "active-runtime"
        )

        geometry_data = (
            _read_json(
                ACTIVE_GEOMETRY
            )
        )


    geometry_is_legacy_trial = bool(geometry_source == "candidate" and lab_legacy_accepted
                                    and not solver_geometry_accepted)

    geometry_is_historical_session = bool(
        isinstance(geometry_candidate, dict)
        and geometry_source == 'candidate'
        and geometry_candidate.get('historical_source_lab_only') is True
        and geometry_candidate.get('field_accuracy_proven') is False
    )

    geometry_is_forced = bool(
        geometry_source
        ==
        "candidate"
        and
        forced_geometry
    )


    add(
        "geometry",
        "Cross-Preset Geometry",

        required=True,

        ok=bool(
            geometry_data
        ),

        status=(
            "WARN"
            if (geometry_is_forced or geometry_is_legacy_trial or geometry_is_historical_session)
            else None
        ),

        detail=(
            (
                "Geometry พร้อมแบบ FORCED LAB OVERRIDE | "
                "Independent Holdout = FAILED"
            )
            if geometry_is_forced
            else
            (
                "LAB TRIAL ONLY: Historical Holdout evidence accepted; "
                "not freshly solved or certified for Production"
            )
            if geometry_is_legacy_trial
            else
            (
                'LAB-ONLY: Historical Session Draft solved and passed holdout; '
                'current field accuracy unverified, not Production certified'
            )
            if geometry_is_historical_session
            else
            (
                (
                    "Geometry พร้อม | "
                    f"{geometry_source}"
                )
                if geometry_data
                else
                "ยังไม่มี Geometry ที่ผ่าน Solver"
            )
        ),

        source=
            geometry_source,
    )


    if geometry_is_historical_session and mode != 'LAB':
        add('historical_session_production_block', 'Historical evidence is not production calibration',
            required=True, ok=False,
            detail='Session images differ from current PTZ captures: field and geometry validation required',
            source='historical-session')

    # Geometry/Intrinsics dependency integrity.
    dependency_ok = False
    dependency_status = None
    dependency_detail = None


    if (
        geometry_source
        ==
        "candidate"
    ):

        geometry_intrinsics_hash = (
            solver_result.get(
                "intrinsics_sha256"
            )
        )


        dependency_ok = bool(
            geometry_intrinsics_hash
            and
            intrinsics_hash
            and
            geometry_intrinsics_hash
            ==
            intrinsics_hash
        )


        if geometry_is_legacy_trial:
            # Policy exception for a supervised LAB trial, NOT SHA provenance.
            dependency_ok = True
            dependency_status = "WARN"
            geometry_intrinsics_hash = None

        dependency_detail = (
            "LAB TRIAL ONLY: Intrinsics lineage unproven. "
            "Requires independent solve/field validation before Production"
            if geometry_is_legacy_trial
            else
            (
            "Geometry ใช้ Intrinsics Candidate ชุดเดียวกัน"
            if dependency_ok
            else
            (
                "Geometry / Intrinsics fingerprint "
                "ไม่ตรงกัน ต้อง Solve Geometry ใหม่"
            )
            )
        )


    elif (
        geometry_source
        ==
        "active-runtime"
    ):

        intrinsics_state = (
            state.get(
                "intrinsics",
                {}
            )
            or {}
        )


        if (
            intrinsics_state.get(
                "source"
            )
            ==
            "FIT_CANDIDATE"
        ):

            dependency_ok = False

            dependency_detail = (
                "มี Intrinsics ใหม่ แต่ Geometry "
                "ยังเป็น Active Runtime เดิม"
            )

        else:

            dependency_ok = True

            dependency_status = (
                "WARN"
            )

            dependency_detail = (
                "Legacy Active Geometry "
                "ไม่มี SHA256 dependency record; "
                "อนุญาต reuse สำหรับ Existing Site"
            )


    add(
        "geometry_intrinsics",
        "Geometry ↔ Intrinsics integrity",

        required=True,

        ok=
            dependency_ok,

        status=
            dependency_status,

        detail=(
            dependency_detail
            or
            "ยังไม่มีข้อมูล dependency"
        ),

        source=
            geometry_source,
    )


    if geometry_is_legacy_trial:
        add(
            "legacy_geometry_lab_trial",
            "Historical Geometry LAB Trial",
            required=False, ok=False, status="WARN",
            detail=("Operator accepted historical 9-preset Holdout; "
                    "intrinsics lineage and present-day field accuracy are NOT proven. "
                    "Not for operational fire-safety reliance or Production."),
            source="explicit-lab-trial-review",
        )

    # ========================================================
    # True North
    # ========================================================

    north_candidate = (
        _candidate_json(
            site_id,
            "site.json",
        )
    )


    north_source = None
    north_data = None


    if _valid_north(
        north_candidate
    ):

        north_source = (
            "candidate"
        )

        north_data = (
            north_candidate
        )


    elif (
        existing_active
        and
        _valid_north(
            _read_json(
                ACTIVE_SITE
            )
        )
    ):

        north_source = (
            "active-runtime"
        )

        north_data = (
            _read_json(
                ACTIVE_SITE
            )
        )


    add(
        "true_north",
        "True North",

        required=(
            mode
            ==
            "PRODUCTION"
        ),

        ok=bool(
            north_data
        ),

        detail=(
            (
                "True North พร้อม | "
                f"{north_source}"
            )
            if north_data
            else
            "ยังไม่มี True North calibration"
        ),

        source=
            north_source,
    )


    # ========================================================
    # Telegram
    # ========================================================

    telegram_candidate = (
        _candidate_json(site_id, "telegram.json")
    )
    telegram_state = state.get("telegram", {}) or {}
    if not isinstance(telegram_state, dict):
        telegram_state = {}

    # Read the current Candidate, not the Active runtime Telegram config.
    # Old wizard booleans alone are insufficient: a later Token/Chat ID
    # change must revoke the previous delivery-test evidence.
    telegram_candidate_file = _candidate_path(site_id, "telegram.json")
    telegram_digest = None
    if (isinstance(telegram_candidate, dict) and telegram_candidate
            and telegram_candidate_file.is_file()
            and not telegram_candidate_file.is_symlink()
            and not telegram_candidate_file.parent.is_symlink()):
        telegram_digest = _sha256(telegram_candidate_file)

    telegram_configured = bool(
        telegram_digest
        and telegram_state.get("proof_version") == 1
        and telegram_state.get("configured") is True
        and telegram_state.get("candidate_sha256") == telegram_digest
    )
    telegram_tested = bool(
        telegram_configured
        and telegram_state.get("tested") is True
        and telegram_state.get("tested_candidate_sha256") == telegram_digest
    )

    telegram_required = (
        mode
        ==
        "PRODUCTION"
    )


    add(
        "telegram_config",
        "Telegram configuration",

        required=
            telegram_required,

        ok=
            telegram_configured,

        detail=(
            "Telegram Candidate พร้อมและยืนยันข้อมูลแล้ว"
            if telegram_configured
            else
            "ยังไม่ได้ตั้ง Telegram Token / Chat ID"
        ),

        source=
            "candidate",
    )


    add(
        "telegram_test",
        "Telegram notification test",

        required=
            telegram_required,

        ok=
            telegram_tested,

        detail=(
            "ทดสอบ Telegram ผ่านกับ Candidate ปัจจุบัน"
            if telegram_tested
            else
            "ยังไม่มีผลทดสอบที่ยืนยันกับ Candidate ปัจจุบัน"
        ),

        source=
            "wizard-state",
    )


    # ========================================================
    # Candidate result
    # ========================================================

    # Phase 4: landmarks changed => historical geometry and trial are stale.
    # Only a fresh solver result tied to the current Intrinsics may lift this.
    phase45_dirty = bool(state.get("phase45_geometry_dirty"))
    phase45_fresh_solve = bool(
        solver_result.get("passed") is True
        and solver_result.get("intrinsics_sha256")
        and solver_result.get("intrinsics_sha256") == intrinsics_hash
    )
    if phase45_dirty:
        add("phase45_landmark_reverification", "Edited landmark verification",
            required=True, ok=phase45_fresh_solve,
            detail=("Fresh solver result verified after changes" if phase45_fresh_solve
                    else "Landmarks edited: rerun Geometry Prepare/Solve and verify before Publish"),
            source="phase45-working-copy")

    from manager.services.site_settings_v24 import FILENAME, resolve_artifact
    settings_path = CANDIDATE_DIR / site_id / FILENAME
    if settings_path.exists() or settings_path.is_symlink():
        try:
            if settings_path.is_symlink() or settings_path.stat().st_size > 16384:
                raise ValueError("unsafe settings file")
            values = json.loads(settings_path.read_text(encoding="utf-8"))
            resolve_artifact(values)
            settings_ok = True
        except (OSError, ValueError, TypeError):
            settings_ok = False
        add("site_detection_settings", "Site-specific Detection Settings",
            required=True, ok=settings_ok,
            detail="Validated site-scoped values" if settings_ok else "Invalid site-scoped detection settings",
            source="working-copy")

    candidate_ready = (
        len(
            blockers
        )
        ==
        0
    )


    runtime_checks = [
        {
            "key":
                "offline_preflight",

            "label":
                "Offline Preflight",

            "status":
                "RUN_DURING_ACTIVATION",

            "detail":
                (
                    "จะรันอีกครั้งก่อน "
                    "Atomic Activation"
                ),
        },

        {
            "key":
                "full_sweep",

            "label":
                "Full Sweep Verification",

            "status":
                "RUN_DURING_ACTIVATION",

            "detail":
                (
                    "จะตรวจ PTZ / Camera / "
                    "Detection ก่อน Commit"
                ),
        },

        {
            "key":
                "service_health",

            "label":
                "Post-Activation Health",

            "status":
                "RUN_DURING_ACTIVATION",

            "detail":
                (
                    "ตรวจ Detection service "
                    "หลัง restart"
                ),
        },
    ]


    return {
        "ok":
            True,

        "site_id":
            site_id,

        "mode":
            mode,

        "existing_active":
            existing_active,

        "candidate_ready":
            candidate_ready,

        # The privileged activation agent already exists.  Its socket's
        # presence proves a local endpoint, not permission to activate this
        # Candidate (publishing an immutable revision is still required).
        "activation_available":
            Path(
                "/run/smart-fire-manager-agent/control.sock"
            ).is_socket(),

        "ready_for_activation":
            False,  # Candidate is not an immutable, verified Revision

        "activation_next_step":
            "Publish immutable revision, then review the activation plan in Site Management",

        "activation_status": (
            "CANDIDATE_READY"
            if candidate_ready
            else
            "BLOCKED"
        ),

        "blocker_count":
            len(
                blockers
            ),

        "warning_count":
            len(
                warnings
            ),

        "blockers":
            blockers,

        "warnings":
            warnings,

        "checks":
            checks,

        "runtime_checks":
            runtime_checks,

        "runtime_changed":
            False,
    }
