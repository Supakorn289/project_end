from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


from manager.services.wizard_store import (
    candidate_path,
    load_state,
    save_candidate,
    save_state,
)


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

PYTHON = (
    PROJECT_ROOT
    / "venv"
    / "bin"
    / "python"
)

SOLVER = (
    PROJECT_ROOT
    / "solve_final_mixed_rotation_AB_v3.py"
)

LOCK_FILE = (
    PROJECT_ROOT
    / "calibration"
    / ".manager"
    / "geometry_solver.lock"
)


FAILED_CANDIDATE_NAME = (
    "preset_rotation_failed_"
    "holdout_MIXED_AB_v3.json"
)


def _failed_geometry_candidate_path(
    site_id,
):

    return candidate_path(
        site_id,
        "geometry_solver_workspace/"
        + FAILED_CANDIDATE_NAME,
    )


def _sha256_file(
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


def _read_json(
    path,
):

    return json.loads(
        Path(
            path
        ).read_text(
            encoding="utf-8"
        )
    )


def _copy_json(
    source,
    destination,
):

    source = Path(
        source
    )

    destination = Path(
        destination
    )


    if not source.exists():

        raise FileNotFoundError(
            source
        )


    # Validate JSON before copying.
    _read_json(
        source
    )


    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    shutil.copyfile(
        source,
        destination,
    )


def _summary(
    candidate,
):

    holdout_evaluation = (
        candidate.get(
            "post_refit_holdout"
        )
        or
        candidate.get(
            "holdout_evaluation"
        )
        or
        {}
    )


    holdout = (
        holdout_evaluation
        .get(
            "global_metrics",
            {}
        )
    )


    return {
        "status":
            candidate.get(
                "status"
            ),

        "model":
            candidate.get(
                "model"
            ),

        "holdout_passed":
            bool(
                candidate
                .get(
                    "independent_holdout_gate",
                    {}
                )
                .get(
                    "passed"
                )
            ),

        "pair_checks":
            candidate
            .get(
                "independent_holdout_gate",
                {}
            )
            .get(
                "pairs",
                {}
            ),

        "global_metrics":
            holdout,
    }



GEOMETRY_DIAGNOSTIC_PREFIX = (
    "GEOMETRY_DIAGNOSTIC_JSON="
)


def _extract_geometry_diagnostic(
    stdout,
):

    stdout = str(
        stdout
        or ""
    )


    for line in reversed(
        stdout.splitlines()
    ):

        line = line.strip()


        if not line.startswith(
            GEOMETRY_DIAGNOSTIC_PREFIX
        ):
            continue


        raw = line[
            len(
                GEOMETRY_DIAGNOSTIC_PREFIX
            ):
        ]


        try:

            value = json.loads(
                raw
            )


            if isinstance(
                value,
                dict,
            ):
                return value


        except Exception:
            return None


    return None


def _geometry_failure_user_message(
    diagnostic,
    stderr,
):

    lines = [
        "GEOMETRY SOLVER FAILED",
    ]


    if isinstance(
        diagnostic,
        dict,
    ):

        failures = (
            diagnostic.get(
                "hard_failures",
                [],
            )
            or []
        )

        reviews = (
            diagnostic.get(
                "review_pairs",
                [],
            )
            or []
        )


        if failures:

            lines.extend([
                "",
                (
                    "สาเหตุ: Training Landmark "
                    "บาง Pair ไม่สามารถสร้าง "
                    "rotation ที่สอดคล้องกันได้"
                ),
            ])


            for item in failures:

                pair = item.get(
                    "pair",
                    "?",
                )

                reason = item.get(
                    "reason",
                    "RANSAC failed",
                )

                lines.append(
                    f"❌ TRAIN Pair {pair}: "
                    f"{reason}"
                )


                residuals = (
                    item.get(
                        "train_residuals_deg",
                        [],
                    )
                    or []
                )


                if residuals:

                    values = ", ".join(
                        f"M{i + 1}="
                        f"{float(value):.3f}°"

                        for i, value
                        in enumerate(
                            residuals
                        )
                    )

                    lines.append(
                        "   Direct-fit residual: "
                        + values
                    )


                suspect = item.get(
                    "suspect_mark_index"
                )


                if suspect is not None:

                    lines.append(
                        "   จุดที่ควรตรวจอันดับแรก: "
                        f"Mark {suspect}"
                    )


            threshold = diagnostic.get(
                "ransac_threshold_deg"
            )

            minimum = diagnostic.get(
                "minimum_pair_inliers"
            )


            if (
                threshold is not None
                and
                minimum is not None
            ):

                lines.append(
                    ""
                    "เกณฑ์ RANSAC: "
                    f"ต้องมีอย่างน้อย {minimum} "
                    "inliers ภายใน "
                    f"{float(threshold):.2f}°"
                )


        if reviews:

            lines.extend([
                "",
                (
                    "คู่ที่ยังไม่ทำให้ Solver crash "
                    "แต่ควรตรวจเพิ่มเติม:"
                ),
            ])


            for item in reviews:

                lines.append(
                    "⚠ HOLDOUT Pair "
                    f"{item.get('pair', '?')}: "
                    "median="
                    f"{float(item.get('median_deg', 0.0)):.3f}° "
                    "p90="
                    f"{float(item.get('p90_deg', 0.0)):.3f}° "
                    "max="
                    f"{float(item.get('max_deg', 0.0)):.3f}°"
                )


        if failures:

            lines.extend([
                "",
                (
                    "วิธีแก้: ตรวจ/เพิ่ม Landmark "
                    "ของ Pair ที่ระบุ โดยเลือก "
                    "วัตถุไกล คงที่ และจุดชัด"
                ),
                (
                    "หลังแก้ Landmark ให้กด "
                    "\"เตรียมข้อมูลสำหรับ Solver\" "
                    "ใหม่ แล้วค่อยคำนวณอีกครั้ง"
                ),
            ])


            return "\n".join(
                lines
            )


    # Fallback เมื่อไม่มี structured diagnostic
    stderr = str(
        stderr
        or ""
    ).strip()


    if stderr:

        last_line = (
            stderr.splitlines()[-1]
        )

        lines.extend([
            "",
            "รายละเอียด:",
            last_line,
        ])


    return "\n".join(
        lines
    )


def _holdout_gate_diagnostic(
    result_file,
):

    result_file = Path(
        result_file
    )


    if not result_file.exists():
        return None


    try:

        payload = _read_json(
            result_file
        )


    except Exception:
        return None


    checks = (
        payload.get(
            "production_pair_checks",
            {},
        )
        or {}
    )

    evaluation = (
        payload.get(
            "holdout_evaluation",
            {},
        )
        or {}
    )

    pair_metrics = (
        evaluation.get(
            "pairs",
            {},
        )
        or {}
    )


    failed = []


    for pair, passed in checks.items():

        if bool(
            passed
        ):
            continue


        metrics = (
            pair_metrics.get(
                pair,
                {},
            )
            or {}
        )


        failed.append({
            "pair":
                pair,

            "median_deg":
                metrics.get(
                    "median_abs_azimuth_error_deg"
                ),

            "p90_deg":
                metrics.get(
                    "p90_abs_azimuth_error_deg"
                ),

            "max_deg":
                metrics.get(
                    "max_abs_azimuth_error_deg"
                ),

            "status":
                metrics.get(
                    "status"
                ),
        })


    return {
        "stage":
            "holdout_gate",

        "failed_pairs":
            failed,

        "global_metrics":
            (
                evaluation.get(
                    "global_metrics",
                    {},
                )
                or {}
            ),
    }


def _holdout_failure_user_message(
    diagnostic,
):

    lines = [
        "GEOMETRY HOLDOUT FAILED",
        "",
        (
            "Solver ทำงานจบ แต่ Independent "
            "Holdout ไม่ผ่าน Production Gate"
        ),
    ]


    if not isinstance(
        diagnostic,
        dict,
    ):

        return "\n".join(
            lines
        )


    failed = (
        diagnostic.get(
            "failed_pairs",
            [],
        )
        or []
    )


    if failed:

        lines.extend([
            "",
            "Pair ที่ไม่ผ่าน:",
        ])


        for item in failed:

            pair = item.get(
                "pair",
                "?",
            )

            median = item.get(
                "median_deg"
            )

            p90 = item.get(
                "p90_deg"
            )

            maximum = item.get(
                "max_deg"
            )


            parts = [
                f"❌ HOLDOUT Pair {pair}",
            ]


            if median is not None:
                parts.append(
                    "median="
                    f"{float(median):.3f}°"
                )

            if p90 is not None:
                parts.append(
                    "p90="
                    f"{float(p90):.3f}°"
                )

            if maximum is not None:
                parts.append(
                    "max="
                    f"{float(maximum):.3f}°"
                )


            lines.append(
                " | ".join(
                    parts
                )
            )


    metrics = (
        diagnostic.get(
            "global_metrics",
            {},
        )
        or {}
    )


    if metrics:

        median = metrics.get(
            "median_abs_azimuth_error_deg"
        )

        p90 = metrics.get(
            "p90_abs_azimuth_error_deg"
        )


        if (
            median is not None
            or
            p90 is not None
        ):

            lines.extend([
                "",
                "Global Holdout:",
            ])


            if median is not None:
                lines.append(
                    "median="
                    f"{float(median):.3f}°"
                )

            if p90 is not None:
                lines.append(
                    "p90="
                    f"{float(p90):.3f}°"
                )


    lines.extend([
        "",
        (
            "ให้ตรวจ Landmark ของ Pair ที่ระบุ "
            "แล้ว Prepare Solver ใหม่ก่อนคำนวณซ้ำ"
        ),
    ])


    return "\n".join(
        lines
    )


def failed_geometry_force_status(
    site_id,
):

    state = load_state(
        site_id
    )


    mode = str(
        state.get(
            "mode",
            "LAB",
        )
        or "LAB"
    ).upper()


    failed_file = (
        _failed_geometry_candidate_path(
            site_id
        )
    )


    manifest_file = (
        candidate_path(
            site_id,
            "geometry_inputs/"
            "manifest.json",
        )
    )


    exists = (
        failed_file.exists()
    )


    stale = False


    if exists:

        if not manifest_file.exists():

            stale = True

        else:

            try:

                stale = (
                    failed_file.stat().st_mtime_ns
                    <
                    manifest_file.stat().st_mtime_ns
                )

            except OSError:

                stale = True


    candidate = None


    if (
        exists
        and
        not stale
    ):

        try:

            candidate = (
                _read_json(
                    failed_file
                )
            )

        except Exception:

            candidate = None


    gate = (
        (
            candidate
            or {}
        )
        .get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    presets = (
        (
            candidate
            or {}
        )
        .get(
            "presets"
        )
    )


    structurally_valid = bool(
        isinstance(
            candidate,
            dict,
        )

        and

        candidate.get(
            "status"
        )
        ==
        "HOLDOUT_FAILED_CANDIDATE_NOT_INSTALLED"

        and

        candidate.get(
            "model"
        )
        ==
        "calibrated-global-raw-ray-rotation"

        and

        gate.get(
            "passed"
        )
        is False

        and

        isinstance(
            presets,
            dict,
        )

        and

        all(
            str(preset)
            in presets

            for preset
            in range(
                1,
                10,
            )
        )
    )


    available = bool(
        exists
        and
        not stale
        and
        structurally_valid
    )


    pair_checks = (
        gate.get(
            "pairs",
            {},
        )
        or {}
    )


    failed_pairs = [
        pair
        for pair, passed
        in pair_checks.items()
        if passed is not True
    ]


    holdout_metrics = (
        (
            candidate
            or {}
        )
        .get(
            "holdout_evaluation",
            {},
        )
        .get(
            "global_metrics",
            {},
        )
        or {}
    )


    return {
        "ok":
            True,

        "site_id":
            site_id,

        "mode":
            mode,

        "available":
            available,

        # Force override is intentionally LAB-only.
        "allowed":
            bool(
                available
                and
                mode
                ==
                "LAB"
            ),

        "stale":
            bool(
                stale
            ),

        "failed_pairs":
            failed_pairs,

        "global_metrics":
            holdout_metrics,

        "reason":
            (
                None
                if (
                    available
                    and
                    mode
                    ==
                    "LAB"
                )
                else
                (
                    "force_override_lab_only"
                    if (
                        available
                        and
                        mode
                        !=
                        "LAB"
                    )
                    else
                    (
                        "failed_candidate_stale"
                        if stale
                        else
                        "no_current_failed_candidate"
                    )
                )
            ),

        "runtime_changed":
            False,
    }


def force_failed_geometry_candidate(
    site_id,
    *,
    confirmation,
    reason=None,
):

    status = (
        failed_geometry_force_status(
            site_id
        )
    )


    if (
        str(
            confirmation
            or ""
        )
        .strip()
        .upper()
        !=
        "FORCE"
    ):

        raise ValueError(
            "confirmation must be FORCE"
        )


    if not status.get(
        "allowed"
    ):

        raise RuntimeError(
            status.get(
                "reason"
            )
            or
            "force_override_not_allowed"
        )


    failed_file = (
        _failed_geometry_candidate_path(
            site_id
        )
    )


    candidate = (
        _read_json(
            failed_file
        )
    )


    gate = (
        candidate.get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    if (
        gate.get(
            "passed"
        )
        is not False
    ):

        raise RuntimeError(
            "failed candidate does not "
            "contain a failed holdout gate"
        )


    forced_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


    reason_text = str(
        reason
        or
        "manual_operator_override"
    ).strip()


    if not reason_text:

        reason_text = (
            "manual_operator_override"
        )


    reason_text = (
        reason_text[
            :300
        ]
    )


    forced = dict(
        candidate
    )


    forced[
        "status"
    ] = (
        "FORCED_CANDIDATE_NOT_INSTALLED"
    )


    forced[
        "operator_override"
    ] = {
        "enabled":
            True,

        "acknowledged_holdout_failure":
            True,

        "scope":
            "LAB",

        "forced_at_utc":
            forced_at,

        "reason":
            reason_text,

        "source_status":
            candidate.get(
                "status"
            ),

        "source_failed_candidate":
            str(
                failed_file
            ),
    }


    manager_candidate = (
        save_candidate(
            site_id,
            "preset_rotation.json",
            forced,
        )
    )


    intrinsics_file = (
        candidate_path(
            site_id,
            "camera_intrinsics.json",
        )
    )


    intrinsics_sha256 = (
        _sha256_file(
            intrinsics_file
        )
        if intrinsics_file.exists()
        else None
    )


    state = load_state(
        site_id
    )


    geometry = (
        state.setdefault(
            "geometry",
            {},
        )
    )


    geometry[
        "candidate"
    ] = forced


    geometry[
        "solver_result"
    ] = {
        "engine":
            "solve_final_mixed_"
            "rotation_AB_v3.py",

        "candidate_file":
            str(
                manager_candidate
            ),

        "workspace":
            str(
                failed_file.parent
            ),

        "passed":
            False,

        "forced_override":
            True,

        "holdout_passed":
            False,

        "source_failed_candidate":
            str(
                failed_file
            ),

        "intrinsics_file":
            str(
                intrinsics_file
            ),

        "intrinsics_sha256":
            intrinsics_sha256,
    }


    geometry[
        "override"
    ] = {
        "enabled":
            True,

        "forced_at_utc":
            forced_at,

        "reason":
            reason_text,

        "failed_pairs":
            status.get(
                "failed_pairs",
                [],
            ),

        "global_metrics":
            status.get(
                "global_metrics",
                {},
            ),
    }


    state[
        "step"
    ] = "TRUE_NORTH"


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            True,

        "site_id":
            site_id,

        "status":
            forced[
                "status"
            ],

        "forced_override":
            True,

        "holdout_passed":
            False,

        "failed_pairs":
            status.get(
                "failed_pairs",
                [],
            ),

        "global_metrics":
            status.get(
                "global_metrics",
                {},
            ),

        "candidate_file":
            str(
                manager_candidate
            ),

        "warning":
            (
                "Geometry นี้ไม่ผ่าน Independent "
                "Holdout และถูกเปิดใช้ด้วย "
                "LAB operator override"
            ),

        "runtime_changed":
            False,
    }


def run_existing_geometry_solver(
    site_id,
):

    if not SOLVER.exists():

        return {
            "ok": False,
            "error":
                "existing_solver_missing",
        }


    manifest_path = (
        candidate_path(
            site_id,
            "geometry_inputs/"
            "manifest.json",
        )
    )


    if not manifest_path.exists():

        return {
            "ok": False,

            "error":
                "solver_inputs_not_prepared",
        }


    manifest = (
        _read_json(
            manifest_path
        )
    )


    intrinsics_file = (
        candidate_path(
            site_id,
            "camera_intrinsics.json",
        )
    )


    if not intrinsics_file.exists():

        return {
            "ok": False,

            "error":
                "intrinsics_candidate_missing",

            "detail":
                (
                    "เลือก Reuse Active Intrinsics "
                    "หรือ Fit Intrinsics Candidate "
                    "ก่อน Solve Geometry"
                ),

            "runtime_changed":
                False,
        }


    intrinsics_sha256 = (
        _sha256_file(
            intrinsics_file
        )
    )


    inputs = manifest.get(
        "inputs",
        {}
    )


    required = {
        "positive_train":
            (
                "positive_train",
                "cross_preset_marks_FINAL_A.json",
            ),

        "positive_holdout":
            (
                "positive_holdout",
                "cross_preset_marks_FINAL_B.json",
            ),

        "negative_train":
            (
                "negative_train",
                "negative_side_marks_FINAL_A2.json",
            ),

        "negative_holdout":
            (
                "negative_holdout",
                "negative_side_marks_FINAL_B2.json",
            ),
    }


    workspace = (
        candidate_path(
            site_id,
            "geometry_solver_workspace",
        )
    )


    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )


    roots = {}


    for (
        key,
        (
            dirname,
            filename,
        ),
    ) in required.items():

        if key not in inputs:

            return {
                "ok": False,

                "error":
                    f"missing_input:{key}",
            }


        root = (
            workspace
            / dirname
        )

        root.mkdir(
            parents=True,
            exist_ok=True,
        )


        _copy_json(
            inputs[
                key
            ],

            root
            / filename,
        )


        roots[
            key
        ] = root


    compatibility_site = (
        workspace
        / "compat_site"
    )

    compatibility_validation = (
        workspace
        / "compat_validation"
    )


    compatibility_site.mkdir(
        parents=True,
        exist_ok=True,
    )

    compatibility_validation.mkdir(
        parents=True,
        exist_ok=True,
    )


    train_file = (
        workspace
        / "final_mixed_train_marks_v3.json"
    )

    holdout_file = (
        workspace
        / "final_mixed_holdout_marks_v3.json"
    )

    result_file = (
        workspace
        / "final_mixed_rotation_AB_v3_result.json"
    )

    candidate_file = (
        workspace
        / "preset_rotation_candidate_MIXED_AB_v3.json"
    )

    failed_candidate_file = (
        workspace
        / FAILED_CANDIDATE_NAME
    )


    stdout_file = (
        workspace
        / "solver.stdout.txt"
    )

    stderr_file = (
        workspace
        / "solver.stderr.txt"
    )


    # Never accept a stale candidate.
    for path in (
        train_file,
        holdout_file,
        result_file,
        candidate_file,
        failed_candidate_file,
    ):

        try:
            path.unlink()

        except FileNotFoundError:
            pass


    env = os.environ.copy()


    # Geometry MUST use the Intrinsics Candidate
    # belonging to this Site.
    env[
        "SMART_FIRE_SOLVER_INTRINSICS_FILE"
    ] = str(
        intrinsics_file
    )


    # solve_preset_rotation_v1.py
    env[
        "SMART_FIRE_SOLVER_SITE_DIR"
    ] = str(
        compatibility_site
    )

    env[
        "SMART_FIRE_SOLVER_VALIDATION_DIR"
    ] = str(
        compatibility_validation
    )


    # solve_final_rotation_bundle_AB_v2.py
    env[
        "SMART_FIRE_BUNDLE_A_ROOT"
    ] = str(
        roots[
            "positive_train"
        ]
    )

    env[
        "SMART_FIRE_BUNDLE_B_ROOT"
    ] = str(
        roots[
            "positive_holdout"
        ]
    )


    # solve_final_mixed_rotation_AB_v3.py
    env[
        "SMART_FIRE_MIXED_POS_A_ROOT"
    ] = str(
        roots[
            "positive_train"
        ]
    )

    env[
        "SMART_FIRE_MIXED_POS_B_ROOT"
    ] = str(
        roots[
            "positive_holdout"
        ]
    )

    env[
        "SMART_FIRE_MIXED_NEG_A_ROOT"
    ] = str(
        roots[
            "negative_train"
        ]
    )

    env[
        "SMART_FIRE_MIXED_NEG_B_ROOT"
    ] = str(
        roots[
            "negative_holdout"
        ]
    )

    env[
        "SMART_FIRE_MIXED_TRAIN_FILE"
    ] = str(
        train_file
    )

    env[
        "SMART_FIRE_MIXED_HOLDOUT_FILE"
    ] = str(
        holdout_file
    )

    env[
        "SMART_FIRE_MIXED_RESULT_FILE"
    ] = str(
        result_file
    )

    env[
        "SMART_FIRE_MIXED_FINAL_CANDIDATE"
    ] = str(
        candidate_file
    )


    env[
        "SMART_FIRE_MIXED_FAILED_CANDIDATE"
    ] = str(
        failed_candidate_file
    )


    LOCK_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOCK_FILE.touch(
        exist_ok=True
    )


    with LOCK_FILE.open(
        "r+"
    ) as lock:

        try:

            fcntl.flock(
                lock,
                (
                    fcntl.LOCK_EX
                    |
                    fcntl.LOCK_NB
                ),
            )

        except BlockingIOError:

            return {
                "ok": False,
                "error":
                    "geometry_solver_busy",
            }


        try:

            process = subprocess.run(
                [
                    str(
                        PYTHON
                    ),
                    str(
                        SOLVER
                    ),
                ],

                cwd=str(
                    PROJECT_ROOT
                ),

                env=env,

                capture_output=True,
                text=True,

                timeout=300,

                check=False,
            )


        except subprocess.TimeoutExpired:

            return {
                "ok": False,
                "error":
                    "geometry_solver_timeout",
            }


        finally:

            fcntl.flock(
                lock,
                fcntl.LOCK_UN,
            )


    stdout_file.write_text(
        process.stdout
        or "",
        encoding="utf-8",
    )

    stderr_file.write_text(
        process.stderr
        or "",
        encoding="utf-8",
    )


    if process.returncode != 0:

        diagnostic = (
            _extract_geometry_diagnostic(
                process.stdout
            )
        )


        return {
            "ok": False,

            "error":
                "geometry_solver_failed",

            "user_message":
                _geometry_failure_user_message(
                    diagnostic,
                    process.stderr,
                ),

            "diagnostic":
                diagnostic,

            "return_code":
                int(
                    process.returncode
                ),

            "stdout_tail":
                (
                    process.stdout
                    or ""
                )[-4000:],

            "stderr_tail":
                (
                    process.stderr
                    or ""
                )[-4000:],

            "runtime_changed":
                False,
        }


    if not candidate_file.exists():

        diagnostic = (
            _holdout_gate_diagnostic(
                result_file
            )
        )


        return {
            "ok": False,

            "error":
                "holdout_failed_or_"
                "candidate_not_created",

            "user_message":
                _holdout_failure_user_message(
                    diagnostic
                ),

            "diagnostic":
                diagnostic,

            "result_file":
                (
                    str(
                        result_file
                    )
                    if result_file.exists()
                    else None
                ),

            "stdout_tail":
                (
                    process.stdout
                    or ""
                )[-4000:],

            "runtime_changed":
                False,
        }


    candidate = (
        _read_json(
            candidate_file
        )
    )


    valid = bool(
        candidate.get(
            "status"
        )
        ==
        "PASS_CANDIDATE_NOT_INSTALLED"

        and

        candidate.get(
            "model"
        )
        ==
        "calibrated-global-raw-ray-rotation"

        and

        candidate
        .get(
            "independent_holdout_gate",
            {}
        )
        .get(
            "passed"
        )
        is True
    )


    if not valid:

        return {
            "ok": False,

            "error":
                "candidate_validation_failed",

            "summary":
                _summary(
                    candidate
                ),

            "runtime_changed":
                False,
        }


    # Copy only into Manager candidate storage.
    # Active runtime is still untouched.
    manager_candidate = (
        save_candidate(
            site_id,
            "preset_rotation.json",
            candidate,
        )
    )


    state = load_state(
        site_id
    )


    state[
        "geometry"
    ][
        "candidate"
    ] = candidate


    state[
        "geometry"
    ][
        "solver_result"
    ] = {
        "engine":
            "solve_final_mixed_"
            "rotation_AB_v3.py",

        "candidate_file":
            str(
                manager_candidate
            ),

        "workspace":
            str(
                workspace
            ),

        "passed":
            True,

        "intrinsics_file":
            str(
                intrinsics_file
            ),

        "intrinsics_sha256":
            intrinsics_sha256,
    }


    state[
        "step"
    ] = "TRUE_NORTH"


    save_state(
        site_id,
        state,
    )


    return {
        "ok": True,

        "engine":
            "solve_final_mixed_"
            "rotation_AB_v3.py",

        "summary":
            _summary(
                candidate
            ),

        "candidate_file":
            str(
                manager_candidate
            ),

        "workspace":
            str(
                workspace
            ),

        "intrinsics_sha256":
            intrinsics_sha256,

        "runtime_changed":
            False,
    }
