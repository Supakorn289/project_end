from __future__ import annotations

import json
import os
import re
import subprocess

from pathlib import Path


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

TEST_SCRIPT = (
    PROJECT_ROOT
    / "test_telegram.py"
)


TOKEN_RIGHT_RE = re.compile(
    r"^[A-Za-z0-9_-]+$"
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
        / "telegram.json"
    )


def _validate_token(
    token,
):

    token = str(
        token
        or ""
    ).strip()


    if (
        "\n" in token
        or
        "\r" in token
    ):

        raise ValueError(
            "Telegram Token "
            "ห้ามมี newline"
        )


    if ":" not in token:

        raise ValueError(
            "รูปแบบ Telegram Bot Token "
            "ไม่ถูกต้อง"
        )


    left, right = (
        token.split(
            ":",
            1,
        )
    )


    if (
        not left.isdigit()
        or
        len(right) < 20
        or
        not TOKEN_RIGHT_RE.fullmatch(
            right
        )
    ):

        raise ValueError(
            "รูปแบบ Telegram Bot Token "
            "ไม่ถูกต้อง"
        )


    return token


def _validate_chat_id(
    chat_id,
):

    chat_id = str(
        chat_id
        or ""
    ).strip()


    if not chat_id:

        raise ValueError(
            "กรุณากรอก Telegram Chat ID"
        )


    if (
        "\n" in chat_id
        or
        "\r" in chat_id
        or
        len(chat_id) > 128
    ):

        raise ValueError(
            "Telegram Chat ID "
            "ไม่ถูกต้อง"
        )


    return chat_id


def _mask_token(
    token,
):

    token = str(
        token
        or ""
    )


    if not token:

        return None


    suffix = (
        token[-4:]
        if len(token) >= 4
        else ""
    )


    return (
        "••••••••"
        +
        suffix
    )


def _mask_chat_id(
    chat_id,
):

    value = str(
        chat_id
        or ""
    )


    if not value:

        return None


    if len(value) <= 4:

        return "••••"


    return (
        "••••"
        +
        value[-4:]
    )


def save_telegram_candidate(
    site_id,
    *,
    token,
    chat_id,
):

    token = _validate_token(
        token
    )

    chat_id = _validate_chat_id(
        chat_id
    )


    candidate = {
        "version":
            1,

        "telegram_token":
            token,

        "telegram_chat_id":
            chat_id,

        "status":
            "CANDIDATE",

        "tested":
            False,

        "runtime_changed":
            False,
    }


    path = save_candidate(
        site_id,
        "telegram.json",
        candidate,
    )


    # Explicit secret-file permission.
    path.chmod(
        0o600
    )


    state = load_state(
        site_id
    )


    state[
        "telegram"
    ] = {
        "configured":
            True,

        "tested":
            False,

        "token_hint":
            _mask_token(
                token
            ),

        "chat_id_hint":
            _mask_chat_id(
                chat_id
            ),
    }


    save_state(
        site_id,
        state,
    )


    return {
        "configured":
            True,

        "tested":
            False,

        "token_hint":
            _mask_token(
                token
            ),

        "chat_id_hint":
            _mask_chat_id(
                chat_id
            ),

        "candidate_file":
            str(
                path
            ),

        "runtime_changed":
            False,
    }


def telegram_status(
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

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )


        return {
            "configured":
                bool(
                    data.get(
                        "telegram_token"
                    )
                    and
                    data.get(
                        "telegram_chat_id"
                    )
                ),

            "tested":
                bool(
                    data.get(
                        "tested",
                        False,
                    )
                ),

            "token_hint":
                _mask_token(
                    data.get(
                        "telegram_token"
                    )
                ),

            "chat_id_hint":
                _mask_chat_id(
                    data.get(
                        "telegram_chat_id"
                    )
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
                f"{type(exc).__name__}: {exc}",

            "runtime_changed":
                False,
        }


def test_telegram_candidate(
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
                "telegram_candidate_missing",

            "runtime_changed":
                False,
        }


    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


    token = _validate_token(
        data.get(
            "telegram_token"
        )
    )

    chat_id = _validate_chat_id(
        data.get(
            "telegram_chat_id"
        )
    )


    env = os.environ.copy()

    env[
        "TELEGRAM_TOKEN"
    ] = token

    env[
        "TELEGRAM_CHAT_ID"
    ] = chat_id


    try:

        process = subprocess.run(
            [
                str(
                    PYTHON
                ),
                str(
                    TEST_SCRIPT
                ),
            ],

            cwd=str(
                PROJECT_ROOT
            ),

            env=env,

            capture_output=True,
            text=True,

            timeout=30,
            check=False,
        )


    except subprocess.TimeoutExpired:

        return {
            "ok":
                False,

            "error":
                "telegram_test_timeout",

            "runtime_changed":
                False,
        }


    passed = (
        process.returncode == 0
    )


    data[
        "tested"
    ] = passed


    save_candidate(
        site_id,
        "telegram.json",
        data,
    ).chmod(
        0o600
    )


    state = load_state(
        site_id
    )


    telegram = (
        state.setdefault(
            "telegram",
            {}
        )
    )


    telegram[
        "configured"
    ] = True

    telegram[
        "tested"
    ] = passed

    telegram[
        "token_hint"
    ] = _mask_token(
        token
    )

    telegram[
        "chat_id_hint"
    ] = _mask_chat_id(
        chat_id
    )


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            passed,

        "configured":
            True,

        "tested":
            passed,

        "token_hint":
            _mask_token(
                token
            ),

        "chat_id_hint":
            _mask_chat_id(
                chat_id
            ),

        "detail":
            (
                "Telegram test message delivered"
                if passed
                else
                "Telegram test failed"
            ),

        "stdout_tail":
            (
                process.stdout
                or ""
            )[-1000:],

        "stderr_tail":
            (
                process.stderr
                or ""
            )[-1000:],

        "runtime_changed":
            False,
    }
