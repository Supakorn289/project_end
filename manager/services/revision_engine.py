from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


from manager.services.final_verification import (
    verify_site_candidate,
)

from manager.services.site_registry import (
    list_registered_sites,
)

from manager.services.wizard_store import (
    CANDIDATE_DIR,
    ROOT,
    STATE_DIR,
    load_state,
    safe_site_id,
    save_state,
)


REVISION_ROOT = (
    ROOT
    / "revisions"
)

LOCK_FILE = (
    ROOT
    / "revisions.lock"
)


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

CALIBRATION_ROOT = (
    PROJECT_ROOT
    / "calibration"
)

PRODUCTION_ENV = Path(
    "/etc/smart-fire-detection/"
    "production.env"
)


SECRET_FILES = {
    "camera_connection.json",
    "telegram.json",
}



ACTIVE_ARTIFACT_FALLBACKS = {
    "camera_intrinsics.json":
        CALIBRATION_ROOT
        / "camera_intrinsics.json",

    "distance_global.json":
        CALIBRATION_ROOT
        / "distance_global.json",

    "site.json":
        CALIBRATION_ROOT
        / "site.json",

    "preset_rotation.json":
        CALIBRATION_ROOT
        / "preset_rotation_ACTIVE.json",
}


COPY_SUFFIXES = {
    ".json",
    ".txt",
    ".sha256",
}


def utc_now():

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def _sha256(
    path,
):

    digest = hashlib.sha256()


    with Path(path).open(
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


def _json_bytes(
    value,
):

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )
        .encode(
            "utf-8"
        )
    )


def _sha256_json(
    value,
):

    return hashlib.sha256(
        _json_bytes(
            value
        )
    ).hexdigest()


def _candidate_files(
    site_id,
):

    base = (
        CANDIDATE_DIR
        / site_id
    )


    if not base.exists():

        return []


    result = []


    for path in sorted(
        base.rglob("*")
    ):

        if (
            not path.is_file()
            or
            path.is_symlink()
        ):

            continue


        # Raw calibration images remain evidence
        # in Candidate workspace. Revision stores
        # activation/configuration artifacts only.
        if path.suffix.lower() not in COPY_SUFFIXES:

            continue


        result.append(
            path
        )


    return result


def _baseline_entry(
    path,
):

    path = Path(
        path
    )


    entry = {
        "path":
            str(
                path
            ),

        "exists":
            path.exists(),
    }


    if path.is_symlink():

        try:

            entry[
                "symlink_target"
            ] = os.readlink(
                path
            )

        except OSError:
            pass


    if path.exists():

        try:

            entry[
                "sha256"
            ] = _sha256(
                path
            )

            entry[
                "size"
            ] = path.stat().st_size

        except OSError as exc:

            entry[
                "error"
            ] = str(
                exc
            )


    return entry


def runtime_baseline():

    files = [
        CALIBRATION_ROOT
        / "camera_intrinsics.json",

        CALIBRATION_ROOT
        / "distance_global.json",

        CALIBRATION_ROOT
        / "site.json",

        CALIBRATION_ROOT
        / "preset_rotation_ACTIVE.json",
    ]


    result = {
        "calibration":
            [
                _baseline_entry(
                    path
                )
                for path
                in files
            ],

        "production_env": {
            "path":
                str(
                    PRODUCTION_ENV
                ),

            "exists":
                PRODUCTION_ENV.exists(),
        },
    }


    # Hash only. Never copy Runtime secrets
    # into an unprivileged revision.
    if PRODUCTION_ENV.exists():

        try:

            result[
                "production_env"
            ][
                "sha256"
            ] = _sha256(
                PRODUCTION_ENV
            )

        except OSError:

            result[
                "production_env"
            ][
                "sha256"
            ] = None


    return result


def _site_record(
    site_id,
):

    registry = (
        list_registered_sites()
    )


    return (
        registry
        .get(
            "sites",
            {}
        )
        .get(
            site_id
        )
    )


def create_revision(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )


    ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    REVISION_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOCK_FILE.touch(
        exist_ok=True
    )


    with LOCK_FILE.open(
        "r+"
    ) as lock:

        fcntl.flock(
            lock,
            fcntl.LOCK_EX,
        )


        verification = (
            verify_site_candidate(
                site_id
            )
        )


        state = load_state(
            site_id
        )


        record = _site_record(
            site_id
        )


        candidate_files = (
            _candidate_files(
                site_id
            )
        )


        file_manifest = []

        fallback_files = []


        candidate_relative = {
            path.relative_to(
                CANDIDATE_DIR
                / site_id
            ).as_posix()

            for path
            in candidate_files
        }


        for path in candidate_files:

            relative = path.relative_to(
                CANDIDATE_DIR
                / site_id
            )


            file_manifest.append({
                "path":
                    relative.as_posix(),

                "sha256":
                    _sha256(
                        path
                    ),

                "size":
                    path.stat().st_size,

                "source":
                    "candidate",
            })


        # A deployable revision must not depend on
        # whatever happens to be Active later.
        for relative_name, active_path in (
            ACTIVE_ARTIFACT_FALLBACKS.items()
        ):

            if relative_name in candidate_relative:
                continue


            if not (
                active_path.exists()
                or
                active_path.is_symlink()
            ):

                continue


            fallback_files.append(
                (
                    Path(
                        relative_name
                    ),
                    active_path,
                )
            )


            file_manifest.append({
                "path":
                    relative_name,

                "sha256":
                    _sha256(
                        active_path
                    ),

                "size":
                    active_path.stat().st_size,

                "source":
                    "active-runtime-fallback",
            })


        digest_input = {
            "site_id":
                site_id,

            "candidate_files":
                file_manifest,

            "wizard_state_sha256":
                _sha256_json(
                    state
                ),

            "site_record_sha256":
                _sha256_json(
                    record
                ),

            "verification_sha256":
                _sha256_json(
                    verification
                ),
        }


        candidate_digest = (
            _sha256_json(
                digest_input
            )
        )


        stamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )


        revision_id = (
            "rev-"
            +
            stamp
            +
            "-"
            +
            candidate_digest[:12]
        )


        site_revision_root = (
            REVISION_ROOT
            / site_id
        )


        site_revision_root.mkdir(
            parents=True,
            exist_ok=True,
        )


        final_dir = (
            site_revision_root
            / revision_id
        )


        if final_dir.exists():

            fcntl.flock(
                lock,
                fcntl.LOCK_UN,
            )


            return {
                "ok":
                    True,

                "revision_id":
                    revision_id,

                "status":
                    json.loads(
                        (
                            final_dir
                            / "revision.json"
                        ).read_text(
                            encoding="utf-8"
                        )
                    ).get(
                        "status"
                    ),

                "existing":
                    True,

                "runtime_changed":
                    False,
            }


        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=".revision.",
                dir=str(
                    site_revision_root
                ),
            )
        )


        try:

            artifacts_dir = (
                temp_dir
                / "artifacts"
            )


            artifacts_dir.mkdir(
                parents=True,
                exist_ok=True,
            )


            for path in candidate_files:

                relative = path.relative_to(
                    CANDIDATE_DIR
                    / site_id
                )


                target = (
                    artifacts_dir
                    / relative
                )


                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )


                shutil.copy2(
                    path,
                    target,
                )


                if (
                    target.name
                    in SECRET_FILES
                ):

                    target.chmod(
                        0o600
                    )

                else:

                    target.chmod(
                        0o640
                    )



            # Snapshot reused Active calibration into
            # the immutable revision as real files.
            for relative, active_path in fallback_files:

                target = (
                    artifacts_dir
                    / relative
                )


                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )


                shutil.copy2(
                    active_path,
                    target,
                    follow_symlinks=True,
                )


                target.chmod(
                    0o640
                )


            revision_status = (
                "VALIDATED_CANDIDATE"
                if verification.get(
                    "candidate_ready"
                )
                else
                "DRAFT_BLOCKED"
            )


            revision = {
                "schema_version":
                    1,

                "revision_id":
                    revision_id,

                "site_id":
                    site_id,

                "created_at":
                    utc_now(),

                "status":
                    revision_status,

                "candidate_ready":
                    bool(
                        verification.get(
                            "candidate_ready"
                        )
                    ),

                "candidate_digest":
                    candidate_digest,

                "blocker_count":
                    int(
                        verification.get(
                            "blocker_count",
                            0,
                        )
                    ),

                "warning_count":
                    int(
                        verification.get(
                            "warning_count",
                            0,
                        )
                    ),

                "runtime_changed":
                    False,
            }


            documents = {
                "revision.json":
                    revision,

                "manifest.json": {
                    "schema_version":
                        1,

                    "revision_id":
                        revision_id,

                    "candidate_digest":
                        candidate_digest,

                    "files":
                        file_manifest,
                },

                "wizard_state.json":
                    state,

                "site_record.json":
                    record,

                "final_verification.json":
                    verification,

                "runtime_baseline.json":
                    runtime_baseline(),
            }


            for filename, data in (
                documents.items()
            ):

                output = (
                    temp_dir
                    / filename
                )


                output.write_text(
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )


                output.chmod(
                    0o640
                )


            # Verify copied artifacts
            # before publishing revision.
            for item in file_manifest:

                target = (
                    artifacts_dir
                    / item[
                        "path"
                    ]
                )


                if (
                    _sha256(
                        target
                    )
                    !=
                    item[
                        "sha256"
                    ]
                ):

                    raise RuntimeError(
                        "Revision artifact "
                        "hash mismatch: "
                        +
                        item[
                            "path"
                        ]
                    )


            temp_dir.chmod(
                0o750
            )


            os.replace(
                temp_dir,
                final_dir,
            )


        except Exception:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )

            raise


        state[
            "latest_revision"
        ] = {
            "revision_id":
                revision_id,

            "status":
                revision_status,

            "candidate_digest":
                candidate_digest,

            "created_at":
                revision[
                    "created_at"
                ],
        }


        save_state(
            site_id,
            state,
        )


        fcntl.flock(
            lock,
            fcntl.LOCK_UN,
        )


    return {
        "ok":
            True,

        "revision_id":
            revision_id,

        "status":
            revision_status,

        "candidate_ready":
            revision[
                "candidate_ready"
            ],

        "candidate_digest":
            candidate_digest,

        "revision_dir":
            str(
                final_dir
            ),

        "artifact_count":
            len(
                file_manifest
            ),

        "blocker_count":
            revision[
                "blocker_count"
            ],

        "runtime_changed":
            False,
    }


def list_revisions(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )


    root = (
        REVISION_ROOT
        / site_id
    )


    if not root.exists():

        return []


    result = []


    for directory in sorted(
        root.iterdir(),
        reverse=True,
    ):

        if not directory.is_dir():
            continue


        revision_file = (
            directory
            / "revision.json"
        )


        if not revision_file.exists():
            continue


        try:

            data = json.loads(
                revision_file.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:
            continue


        result.append(
            data
        )


    return result
