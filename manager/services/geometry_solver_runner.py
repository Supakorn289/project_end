from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess

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

    holdout = (
        candidate
        .get(
            "post_refit_holdout",
            {}
        )
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

        return {
            "ok": False,

            "error":
                "geometry_solver_failed",

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

        return {
            "ok": False,

            "error":
                "holdout_failed_or_"
                "candidate_not_created",

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
