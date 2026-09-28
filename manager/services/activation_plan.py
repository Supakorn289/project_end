from __future__ import annotations

import hashlib
import json
import math
import re

from pathlib import Path


from manager.services.revision_engine import (
    REVISION_ROOT,
)

from manager.services.wizard_store import (
    safe_site_id,
)


REVISION_RE = re.compile(
    r"^rev-[A-Za-z0-9TZ_-]{8,80}$"
)


CALIBRATION_ARTIFACTS = {
    "camera_intrinsics.json":
        "camera_intrinsics.json",

    "distance_global.json":
        "distance_global.json",

    "preset_rotation.json":
        "preset_rotation.json",

    "site.json":
        "site.json",
}


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


def _safe_revision_id(
    revision_id,
):

    revision_id = str(
        revision_id
    ).strip()


    if not REVISION_RE.fullmatch(
        revision_id
    ):

        raise ValueError(
            "invalid revision_id"
        )


    return revision_id


def _revision_dir(
    site_id,
    revision_id,
):

    site_id = safe_site_id(
        site_id
    )

    revision_id = (
        _safe_revision_id(
            revision_id
        )
    )


    root = (
        REVISION_ROOT
        / site_id
    ).resolve()


    directory = (
        root
        / revision_id
    ).resolve()


    if (
        directory.parent
        != root
    ):

        raise ValueError(
            "revision path escape"
        )


    return directory


def _candidate_env(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return {}


    runtime_env = data.get(
        "runtime_env"
    )


    if isinstance(
        runtime_env,
        dict,
    ):

        return {
            str(key):
                str(value)

            for key, value
            in runtime_env.items()

            if value is not None
        }


    return {}


def _telegram_env(
    data,
):

    if not isinstance(
        data,
        dict,
    ):

        return {}


    runtime = _candidate_env(
        data
    )


    if runtime:

        return {
            key:
                value

            for key, value
            in runtime.items()

            if key in {
                "TELEGRAM_TOKEN",
                "TELEGRAM_CHAT_ID",
            }
        }


    result = {}


    token = (
        data.get(
            "TELEGRAM_TOKEN"
        )
        or
        data.get(
            "telegram_token"
        )
        or
        data.get(
            "token"
        )
    )


    chat_id = (
        data.get(
            "TELEGRAM_CHAT_ID"
        )
        or
        data.get(
            "telegram_chat_id"
        )
        or
        data.get(
            "chat_id"
        )
    )


    if token is not None:

        result[
            "TELEGRAM_TOKEN"
        ] = str(
            token
        )


    if chat_id is not None:

        result[
            "TELEGRAM_CHAT_ID"
        ] = str(
            chat_id
        )


    return result


def _coordinates(
    site_record,
):

    if not isinstance(
        site_record,
        dict,
    ):

        return None


    location = (
        site_record.get(
            "location"
        )
    )


    if not isinstance(
        location,
        dict,
    ):

        location = (
            site_record
        )


    latitude = location.get(
        "latitude"
    )

    longitude = location.get(
        "longitude"
    )


    try:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )


        if not (
            math.isfinite(
                latitude
            )
            and
            math.isfinite(
                longitude
            )
            and
            -90.0 <= latitude <= 90.0
            and
            -180.0 <= longitude <= 180.0
        ):

            return None


    except (
        TypeError,
        ValueError,
    ):

        return None


    return (
        latitude,
        longitude,
    )


def build_activation_plan(
    site_id,
    revision_id,
):

    site_id = safe_site_id(
        site_id
    )


    revision_dir = (
        _revision_dir(
            site_id,
            revision_id,
        )
    )


    if not revision_dir.exists():

        raise FileNotFoundError(
            "revision not found"
        )


    revision = _read_json(
        revision_dir
        / "revision.json"
    )


    manifest = _read_json(
        revision_dir
        / "manifest.json"
    )


    verification = _read_json(
        revision_dir
        / "final_verification.json"
    )


    site_record = _read_json(
        revision_dir
        / "site_record.json"
    )


    if (
        revision.get(
            "site_id"
        )
        != site_id
    ):

        raise ValueError(
            "revision site mismatch"
        )


    if not (
        revision.get(
            "status"
        )
        ==
        "VALIDATED_CANDIDATE"

        and

        revision.get(
            "candidate_ready"
        )
        is True
    ):

        return {
            "ok":
                False,

            "activatable":
                False,

            "site_id":
                site_id,

            "revision_id":
                revision_id,

            "status":
                revision.get(
                    "status"
                ),

            "error":
                "revision_not_validated",

            "blocker_count":
                verification.get(
                    "blocker_count"
                ),

            "runtime_changed":
                False,
        }


    artifacts_dir = (
        revision_dir
        / "artifacts"
    )


    verified_files = []


    for item in manifest.get(
        "files",
        []
    ):

        relative = Path(
            item[
                "path"
            ]
        )


        if (
            relative.is_absolute()
            or
            ".." in relative.parts
        ):

            raise ValueError(
                "unsafe artifact path"
            )


        path = (
            artifacts_dir
            / relative
        )


        if (
            not path.exists()
            or
            path.is_symlink()
        ):

            raise ValueError(
                "revision artifact missing"
            )


        digest = _sha256(
            path
        )


        if (
            digest
            !=
            item[
                "sha256"
            ]
        ):

            raise ValueError(
                "revision artifact hash mismatch: "
                +
                relative.as_posix()
            )


        verified_files.append(
            relative.as_posix()
        )


    mode = str(
        (
            site_record
            or {}
        ).get(
            "mode"
        )
        or
        verification.get(
            "mode"
        )
        or
        "LAB"
    ).upper()


    if mode not in {
        "LAB",
        "PRODUCTION",
    }:

        raise ValueError(
            "invalid site mode"
        )


    env = {}


    camera_file = (
        artifacts_dir
        / "camera_connection.json"
    )


    if camera_file.exists():

        camera = _candidate_env(
            _read_json(
                camera_file
            )
        )


        for key in (
            "CAMERA_IP",
            "CAMERA_USER",
            "CAMERA_PWD",
            "RTSP_PORT",
            "RTSP_PATH",
        ):

            if key in camera:

                env[key] = camera[
                    key
                ]


        camera_port = (
            camera.get(
                "CAMERA_PORT"
            )
            or
            camera.get(
                "CAMERA_HTTP_PORT"
            )
        )


        if camera_port is not None:

            env[
                "CAMERA_PORT"
            ] = str(
                camera_port
            )

            # Compatibility with the old
            # Settings/Manager naming.
            env[
                "CAMERA_HTTP_PORT"
            ] = str(
                camera_port
            )


        # Force config.py to rebuild CAMERA_ID
        # from the candidate camera fields.
        env[
            "CAMERA_ID"
        ] = ""


    telegram_file = (
        artifacts_dir
        / "telegram.json"
    )


    if telegram_file.exists():

        env.update(
            _telegram_env(
                _read_json(
                    telegram_file
                )
            )
        )


    coords = _coordinates(
        site_record
    )


    if coords is not None:

        env[
            "CAMERA_LAT"
        ] = (
            f"{coords[0]:.10f}"
        )

        env[
            "CAMERA_LON"
        ] = (
            f"{coords[1]:.10f}"
        )


    intrinsics_file = (
        artifacts_dir
        / "camera_intrinsics.json"
    )


    if intrinsics_file.exists():

        intrinsics = _read_json(
            intrinsics_file
        )


        if (
            intrinsics.get(
                "effective_hfov_deg"
            )
            is not None
        ):

            env[
                "HFOV_DEG"
            ] = str(
                float(
                    intrinsics[
                        "effective_hfov_deg"
                    ]
                )
            )


        if (
            intrinsics.get(
                "frame_width"
            )
            is not None
        ):

            env[
                "FRAME_WIDTH"
            ] = str(
                int(
                    intrinsics[
                        "frame_width"
                    ]
                )
            )


        if (
            intrinsics.get(
                "frame_height"
            )
            is not None
        ):

            env[
                "FRAME_HEIGHT"
            ] = str(
                int(
                    intrinsics[
                        "frame_height"
                    ]
                )
            )


    if mode == "PRODUCTION":

        env[
            "ENABLE_TRUE_NORTH"
        ] = "1"

        env[
            "ENABLE_GPS"
        ] = "1"


    else:

        env[
            "ENABLE_TRUE_NORTH"
        ] = "0"

        env[
            "ENABLE_GPS"
        ] = "0"


    calibration = {}


    for source_name, active_name in (
        CALIBRATION_ARTIFACTS.items()
    ):

        path = (
            artifacts_dir
            / source_name
        )


        if path.exists():

            calibration[
                active_name
            ] = {
                "source":
                    source_name,

                "sha256":
                    _sha256(
                        path
                    ),
            }


    secrets_present = {
        "camera_password":
            (
                "CAMERA_PWD"
                in env
                and
                bool(
                    env[
                        "CAMERA_PWD"
                    ]
                )
            ),

        "telegram_token":
            (
                "TELEGRAM_TOKEN"
                in env
                and
                bool(
                    env[
                        "TELEGRAM_TOKEN"
                    ]
                )
            ),
    }


    redacted_env = {}


    for key, value in env.items():

        if key in {
            "CAMERA_PWD",
            "TELEGRAM_TOKEN",
        }:

            redacted_env[
                key
            ] = (
                "***configured***"
                if value
                else ""
            )

        else:

            redacted_env[
                key
            ] = value


    return {
        "ok":
            True,

        "activatable":
            True,

        "site_id":
            site_id,

        "revision_id":
            revision_id,

        "mode":
            mode,

        "candidate_digest":
            revision.get(
                "candidate_digest"
            ),

        "artifact_count":
            len(
                verified_files
            ),

        "verified_artifacts":
            verified_files,

        "calibration":
            calibration,

        "environment":
            redacted_env,

        "secret_status":
            secrets_present,

        "run_full_sweep":
            (
                mode
                ==
                "PRODUCTION"
            ),

        "runtime_changed":
            False,
    }
