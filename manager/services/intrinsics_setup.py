from __future__ import annotations

import json
import os
import subprocess
import time

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

SCRIPT = (
    PROJECT_ROOT
    / "calibrate_intrinsics.py"
)

ACTIVE_INTRINSICS = (
    PROJECT_ROOT
    / "calibration"
    / "camera_intrinsics.json"
)


MIN_VIEWS = 10

RECOMMENDED_MIN = 20
RECOMMENDED_MAX = 30


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


def workspace(
    site_id,
):

    path = candidate_path(
        site_id,
        "intrinsics_workspace",
    )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def capture_dir(
    site_id,
):

    path = (
        workspace(
            site_id
        )
        / "captures"
    )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def candidate_file(
    site_id,
):

    return candidate_path(
        site_id,
        "camera_intrinsics.json",
    )


def _valid_intrinsics(
    data,
):

    return bool(
        data.get(
            "valid_for_production"
        )
        is True

        and

        data.get(
            "status"
        )
        ==
        "intrinsics_calibrated"

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


def _summary(
    data,
):

    fit = (
        data.get(
            "fit",
            {}
        )
    )


    return {
        "status":
            data.get(
                "status"
            ),

        "valid_for_production":
            bool(
                data.get(
                    "valid_for_production"
                )
            ),

        "frame_width":
            data.get(
                "frame_width"
            ),

        "frame_height":
            data.get(
                "frame_height"
            ),

        "input_views":
            data.get(
                "input_views"
            ),

        "views_used":
            data.get(
                "views_used"
            ),

        "views_rejected":
            data.get(
                "views_rejected"
            ),

        "quality":
            fit.get(
                "quality"
            ),

        "opencv_rms_px":
            fit.get(
                "opencv_rms_px"
            ),

        "mean_reprojection_px":
            fit.get(
                "mean_reprojection_px"
            ),

        "max_reprojection_px":
            fit.get(
                "max_reprojection_px"
            ),

        "effective_hfov_deg":
            data.get(
                "effective_hfov_deg"
            ),

        "effective_vfov_deg":
            data.get(
                "effective_vfov_deg"
            ),

        "sanity_warnings":
            data.get(
                "sanity_warnings",
                [],
            ),
    }


def intrinsics_status(
    site_id,
):

    captures = sorted(
        capture_dir(
            site_id
        ).glob(
            "calib_*.jpg"
        )
    )


    active = None

    if ACTIVE_INTRINSICS.exists():

        try:

            data = _read_json(
                ACTIVE_INTRINSICS
            )

            active = {
                "exists":
                    True,

                "production_valid":
                    _valid_intrinsics(
                        data
                    ),

                "summary":
                    _summary(
                        data
                    ),
            }

        except Exception as exc:

            active = {
                "exists":
                    True,

                "production_valid":
                    False,

                "error":
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
            }

    else:

        active = {
            "exists":
                False,
        }


    candidate_path_value = (
        candidate_file(
            site_id
        )
    )


    candidate = {
        "exists":
            False,
    }


    if candidate_path_value.exists():

        try:

            data = _read_json(
                candidate_path_value
            )

            candidate = {
                "exists":
                    True,

                "production_valid":
                    _valid_intrinsics(
                        data
                    ),

                "summary":
                    _summary(
                        data
                    ),
            }

        except Exception as exc:

            candidate = {
                "exists":
                    True,

                "production_valid":
                    False,

                "error":
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
            }


    return {
        "active":
            active,

        "candidate":
            candidate,

        "captures":
            len(
                captures
            ),

        "minimum_views":
            MIN_VIEWS,

        "recommended_views": {
            "min":
                RECOMMENDED_MIN,

            "max":
                RECOMMENDED_MAX,
        },

        "fit_ready":
            (
                len(
                    captures
                )
                >=
                MIN_VIEWS
            ),

        "runtime_changed":
            False,
    }


def reuse_active_intrinsics(
    site_id,
):

    if not ACTIVE_INTRINSICS.exists():

        raise FileNotFoundError(
            "Active camera_intrinsics.json "
            "ไม่พบ"
        )


    data = _read_json(
        ACTIVE_INTRINSICS
    )


    if not _valid_intrinsics(
        data
    ):

        raise ValueError(
            "Active Intrinsics "
            "ยังไม่ผ่าน Production validation"
        )


    path = save_candidate(
        site_id,
        "camera_intrinsics.json",
        data,
    )


    state = load_state(
        site_id
    )


    state[
        "intrinsics"
    ] = {
        "source":
            "REUSED_ACTIVE",

        "candidate":
            str(
                path
            ),

        "valid_for_production":
            True,

        "summary":
            _summary(
                data
            ),
    }


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            True,

        "source":
            "REUSED_ACTIVE",

        "candidate_file":
            str(
                path
            ),

        "summary":
            _summary(
                data
            ),

        "runtime_changed":
            False,
    }


def fit_intrinsics_candidate(
    site_id,
):

    captures = (
        capture_dir(
            site_id
        )
    )


    files = sorted(
        captures.glob(
            "calib_*.jpg"
        )
    )


    if len(files) < MIN_VIEWS:

        raise ValueError(
            "ต้องมี Calibration Images "
            f"อย่างน้อย {MIN_VIEWS} ภาพ "
            f"| ตอนนี้มี {len(files)}"
        )


    work = workspace(
        site_id
    )


    output = candidate_file(
        site_id
    )


    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    report = (
        work
        / "fit_report.json"
    )


    try:
        output.unlink()

    except FileNotFoundError:
        pass


    try:
        report.unlink()

    except FileNotFoundError:
        pass


    env = os.environ.copy()


    env[
        "SMART_FIRE_INTRINSICS_WORK_DIR"
    ] = str(
        work
    )


    env[
        "SMART_FIRE_INTRINSICS_CAPTURE_DIR"
    ] = str(
        captures
    )


    env[
        "SMART_FIRE_INTRINSICS_OUTPUT_FILE"
    ] = str(
        output
    )


    env[
        "SMART_FIRE_INTRINSICS_REPORT_FILE"
    ] = str(
        report
    )


    try:

        process = subprocess.run(
            [
                str(
                    PYTHON
                ),

                str(
                    SCRIPT
                ),

                "fit",

                "--max-view-error",
                "1.5",

                "--min-views",
                "12",

                "--max-reject",
                "8",
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
            "ok":
                False,

            "error":
                "intrinsics_fit_timeout",

            "runtime_changed":
                False,
        }


    if process.returncode != 0:

        return {
            "ok":
                False,

            "error":
                "intrinsics_fit_failed",

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


    if not output.exists():

        return {
            "ok":
                False,

            "error":
                "intrinsics_candidate_missing",

            "runtime_changed":
                False,
        }


    data = _read_json(
        output
    )


    state = load_state(
        site_id
    )


    state[
        "intrinsics"
    ] = {
        "source":
            "FIT_CANDIDATE",

        "candidate":
            str(
                output
            ),

        "valid_for_production":
            _valid_intrinsics(
                data
            ),

        "summary":
            _summary(
                data
            ),
    }


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            True,

        "production_valid":
            _valid_intrinsics(
                data
            ),

        "candidate_file":
            str(
                output
            ),

        "report_file":
            (
                str(
                    report
                )
                if report.exists()
                else None
            ),

        "summary":
            _summary(
                data
            ),

        "stdout_tail":
            (
                process.stdout
                or ""
            )[-3000:],

        "runtime_changed":
            False,
    }


def reset_intrinsics_captures(
    site_id,
):

    captures = capture_dir(
        site_id
    )


    existing = list(
        captures.glob(
            "calib_*.jpg"
        )
    )


    preview = (
        captures
        / "preview_latest.jpg"
    )


    if (
        not existing
        and
        not preview.exists()
    ):

        return {
            "ok":
                True,

            "archived":
                False,

            "previous_captures":
                0,

            "runtime_changed":
                False,
        }


    stamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )


    archive = (
        workspace(
            site_id
        )
        /
        f"captures_archive_{stamp}"
    )


    if archive.exists():

        archive = (
            workspace(
                site_id
            )
            /
            (
                f"captures_archive_"
                f"{stamp}_"
                f"{time.time_ns()}"
            )
        )


    captures.rename(
        archive
    )


    captures.mkdir(
        parents=True,
        exist_ok=True,
    )


    state = load_state(
        site_id
    )


    state[
        "intrinsics"
    ] = {
        "source":
            "NEW_CAPTURE_SET",

        "valid_for_production":
            False,

        "captures":
            0,
    }


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            True,

        "archived":
            True,

        "previous_captures":
            len(
                existing
            ),

        "archive":
            str(
                archive
            ),

        "runtime_changed":
            False,
    }
