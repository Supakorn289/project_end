from __future__ import annotations

import ipaddress
import json
import os
import subprocess


from pathlib import Path


from manager.services.runtime_settings import (
    start_detection,
    stop_detection,
)

from manager.services.wizard_store import (
    CANDIDATE_DIR,
    load_state,
    safe_site_id,
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

TEST_CAMERA = (
    PROJECT_ROOT
    / "test_camera.py"
)

DETECTION_SERVICE = (
    "smart-fire-detection.service"
)


def _candidate_file(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )

    return (
        CANDIDATE_DIR
        / site_id
        / "camera_connection.json"
    )


def _text(
    value,
    *,
    name,
    allow_empty=False,
    strip=True,
):

    value = str(
        value
        if value is not None
        else ""
    )


    if strip:
        value = value.strip()


    if (
        "\n" in value
        or
        "\r" in value
    ):

        raise ValueError(
            f"{name} ห้ามมี newline"
        )


    if (
        not allow_empty
        and
        not value
    ):

        raise ValueError(
            f"กรุณากรอก {name}"
        )


    return value


def _port(
    value,
    *,
    name,
):

    try:

        value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ValueError(
            f"{name} ไม่ถูกต้อง"
        ) from exc


    if not (
        1
        <= value
        <= 65535
    ):

        raise ValueError(
            f"{name} ต้องอยู่ระหว่าง "
            "1-65535"
        )


    return value


def validate_camera_settings(
    *,
    camera_ip,
    camera_port,
    camera_user,
    camera_password,
    rtsp_port,
    rtsp_path,
):

    camera_ip = _text(
        camera_ip,
        name="Camera IP",
    )


    try:

        parsed_ip = (
            ipaddress.ip_address(
                camera_ip
            )
        )

    except ValueError as exc:

        raise ValueError(
            "Camera IP ไม่ถูกต้อง"
        ) from exc


    # Runtime CAMERA_ID currently composes
    # rtsp://user:pass@IP:port/path directly.
    # Keep commissioning IPv4-only until
    # IPv6 URL-bracketing is implemented.
    if parsed_ip.version != 4:

        raise ValueError(
            "Commissioning ปัจจุบัน "
            "รองรับ Camera IPv4"
        )


    camera_port = _port(
        camera_port,
        name="Camera HTTP Port",
    )


    camera_user = _text(
        camera_user,
        name="Camera Username",
    )


    # Password must NOT be strip().
    camera_password = _text(
        camera_password,
        name="Camera Password",
        strip=False,
    )


    rtsp_port = _port(
        rtsp_port,
        name="RTSP Port",
    )


    rtsp_path = _text(
        rtsp_path,
        name="RTSP Path",
    )


    if not rtsp_path.startswith(
        "/"
    ):

        raise ValueError(
            "RTSP Path ต้องขึ้นต้นด้วย /"
        )


    return {
        "CAMERA_IP":
            camera_ip,

        "CAMERA_PORT":
            str(
                camera_port
            ),

        "CAMERA_USER":
            camera_user,

        "CAMERA_PWD":
            camera_password,

        "RTSP_PORT":
            str(
                rtsp_port
            ),

        "RTSP_PATH":
            rtsp_path,
    }


def _mask_user(
    username,
):

    username = str(
        username
        or ""
    )


    if not username:
        return None


    if len(username) <= 2:
        return "••"


    return (
        username[0]
        +
        "•••"
        +
        username[-1]
    )


def save_camera_candidate(
    site_id,
    **kwargs,
):

    runtime_env = (
        validate_camera_settings(
            **kwargs
        )
    )


    candidate = {
        "version":
            1,

        "status":
            "CANDIDATE",

        "tested":
            False,

        "runtime_env":
            runtime_env,

        "runtime_changed":
            False,
    }


    path = save_candidate(
        site_id,
        "camera_connection.json",
        candidate,
    )


    # Contains camera password.
    path.chmod(
        0o600
    )


    state = load_state(
        site_id
    )


    state[
        "camera_connection"
    ] = {
        "configured":
            True,

        "tested":
            False,

        "camera_ip":
            runtime_env[
                "CAMERA_IP"
            ],

        "camera_port":
            int(
                runtime_env[
                    "CAMERA_PORT"
                ]
            ),

        "camera_user_hint":
            _mask_user(
                runtime_env[
                    "CAMERA_USER"
                ]
            ),

        "password_configured":
            True,

        "rtsp_port":
            int(
                runtime_env[
                    "RTSP_PORT"
                ]
            ),

        "rtsp_path":
            runtime_env[
                "RTSP_PATH"
            ],
    }


    save_state(
        site_id,
        state,
    )


    return {
        **state[
            "camera_connection"
        ],

        "candidate_file":
            str(
                path
            ),

        "runtime_changed":
            False,
    }


def camera_status(
    site_id,
):

    path = _candidate_file(
        site_id
    )


    if not path.exists():

        return {
            "configured":
                False,

            "tested":
                False,

            "runtime_changed":
                False,
        }


    try:

        candidate = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )


        env = candidate.get(
            "runtime_env",
            {},
        )


        return {
            "configured":
                bool(
                    env.get(
                        "CAMERA_IP"
                    )
                    and
                    env.get(
                        "CAMERA_USER"
                    )
                    and
                    env.get(
                        "CAMERA_PWD"
                    )
                    and
                    env.get(
                        "RTSP_PATH"
                    )
                ),

            "tested":
                bool(
                    candidate.get(
                        "tested",
                        False,
                    )
                ),

            "camera_ip":
                env.get(
                    "CAMERA_IP"
                ),

            "camera_port":
                env.get(
                    "CAMERA_PORT"
                ),

            "camera_user_hint":
                _mask_user(
                    env.get(
                        "CAMERA_USER"
                    )
                ),

            "password_configured":
                bool(
                    env.get(
                        "CAMERA_PWD"
                    )
                ),

            "rtsp_port":
                env.get(
                    "RTSP_PORT"
                ),

            "rtsp_path":
                env.get(
                    "RTSP_PATH"
                ),

            "runtime_changed":
                False,
        }


    except Exception as exc:

        return {
            "configured":
                False,

            "tested":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

            "runtime_changed":
                False,
        }


def _detection_active():

    try:

        process = subprocess.run(
            [
                "/usr/bin/systemctl",
                "is-active",
                DETECTION_SERVICE,
            ],

            capture_output=True,
            text=True,

            timeout=10,
            check=False,
        )


        return (
            process.returncode == 0
            and
            process.stdout.strip()
            == "active"
        )


    except Exception:

        return False


def test_camera_candidate(
    site_id,
):

    path = _candidate_file(
        site_id
    )


    if not path.exists():

        return {
            "ok":
                False,

            "error":
                "camera_candidate_missing",

            "runtime_changed":
                False,
        }


    candidate = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


    runtime_env = (
        candidate.get(
            "runtime_env",
            {}
        )
    )


    # Revalidate before using credentials.
    validated = (
        validate_camera_settings(
            camera_ip=
                runtime_env.get(
                    "CAMERA_IP"
                ),

            camera_port=
                runtime_env.get(
                    "CAMERA_PORT"
                ),

            camera_user=
                runtime_env.get(
                    "CAMERA_USER"
                ),

            camera_password=
                runtime_env.get(
                    "CAMERA_PWD"
                ),

            rtsp_port=
                runtime_env.get(
                    "RTSP_PORT"
                ),

            rtsp_path=
                runtime_env.get(
                    "RTSP_PATH"
                ),
        )
    )


    was_active = (
        _detection_active()
    )

    stopped_by_test = False

    restore_error = None


    try:

        if was_active:

            stopped = (
                stop_detection()
            )


            if not stopped.get(
                "ok"
            ):

                return {
                    "ok":
                        False,

                    "error":
                        "cannot_stop_detection",

                    "detail":
                        stopped,

                    "runtime_changed":
                        False,
                }


            stopped_by_test = True


        env = os.environ.copy()

        env.update(
            validated
        )


        # Force config.py to rebuild
        # CAMERA_ID from candidate fields.
        env.pop(
            "CAMERA_ID",
            None,
        )


        try:

            process = subprocess.run(
                [
                    str(
                        PYTHON
                    ),
                    str(
                        TEST_CAMERA
                    ),
                ],

                cwd=str(
                    PROJECT_ROOT
                ),

                env=env,

                capture_output=True,
                text=True,

                timeout=60,

                check=False,
            )


            passed = (
                process.returncode
                == 0
            )


        except subprocess.TimeoutExpired:

            process = None

            passed = False


    finally:

        if stopped_by_test:

            restored = (
                start_detection()
            )


            if not restored.get(
                "ok"
            ):

                restore_error = (
                    restored
                )


    candidate[
        "tested"
    ] = bool(
        passed
    )


    save_candidate(
        site_id,
        "camera_connection.json",
        candidate,
    ).chmod(
        0o600
    )


    state = load_state(
        site_id
    )


    camera_state = (
        state.setdefault(
            "camera_connection",
            {},
        )
    )


    camera_state[
        "configured"
    ] = True

    camera_state[
        "tested"
    ] = bool(
        passed
    )


    save_state(
        site_id,
        state,
    )


    result = {
        "ok":
            bool(
                passed
                and
                restore_error
                is None
            ),

        "configured":
            True,

        "tested":
            bool(
                passed
            ),

        "detection_was_active":
            was_active,

        "detection_restored":
            (
                _detection_active()
                ==
                was_active
            ),

        "runtime_changed":
            False,
    }


    if process is None:

        result[
            "error"
        ] = (
            "camera_test_timeout"
        )

    else:

        result[
            "return_code"
        ] = int(
            process.returncode
        )

        result[
            "stdout_tail"
        ] = (
            process.stdout
            or ""
        )[-3000:]

        result[
            "stderr_tail"
        ] = (
            process.stderr
            or ""
        )[-3000:]


    if restore_error:

        result[
            "restore_error"
        ] = restore_error


    return result


def camera_source_for_site(
    site_id,
):

    path = _candidate_file(
        site_id
    )


    if not path.exists():

        raise ValueError(
            "ยังไม่มี Camera Candidate "
            "สำหรับ Site นี้"
        )


    candidate = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


    runtime_env = (
        candidate.get(
            "runtime_env",
            {}
        )
    )


    values = (
        validate_camera_settings(
            camera_ip=
                runtime_env.get(
                    "CAMERA_IP"
                ),

            camera_port=
                runtime_env.get(
                    "CAMERA_PORT"
                ),

            camera_user=
                runtime_env.get(
                    "CAMERA_USER"
                ),

            camera_password=
                runtime_env.get(
                    "CAMERA_PWD"
                ),

            rtsp_port=
                runtime_env.get(
                    "RTSP_PORT"
                ),

            rtsp_path=
                runtime_env.get(
                    "RTSP_PATH"
                ),
        )
    )


    # สร้างแบบเดียวกับ config.py runtime ปัจจุบัน
    return (
        "rtsp://"
        f"{values['CAMERA_USER']}:"
        f"{values['CAMERA_PWD']}@"
        f"{values['CAMERA_IP']}:"
        f"{values['RTSP_PORT']}"
        f"{values['RTSP_PATH']}"
    )
