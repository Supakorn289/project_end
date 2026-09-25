from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


ROOT = Path(
    "/opt/smart-fire-detection-v2/"
    "calibration/.manager"
)

STATE_DIR = (
    ROOT
    / "wizard"
)

CANDIDATE_DIR = (
    ROOT
    / "candidates"
)

LOCK_FILE = (
    STATE_DIR
    / ".lock"
)


SITE_RE = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._-]{0,63}$"
)


def utc_now():

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def safe_site_id(
    site_id,
):

    site_id = str(
        site_id
    ).strip()

    if not SITE_RE.fullmatch(
        site_id
    ):

        raise ValueError(
            "site_id ใช้ได้เฉพาะ "
            "A-Z a-z 0-9 . _ -"
        )

    return site_id


def _path(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )

    return (
        STATE_DIR
        / f"{site_id}.json"
    )


def _default(
    site_id,
    mode="LAB",
):

    return {
        "schema_version": 1,
        "site_id": site_id,
        "mode": str(
            mode
        ).upper(),
        "step": "DEVICE",
        "calibration_mode": False,
        "captures": {
            "main": {},
            "holdout": {},
        },
        "distance": {
            "points": [],
            "candidate": None,
            "verifications": [],
        },
        "geometry": {
            "train": {},
            "holdout": {},
            "candidate": None,
        },
        "north": {
            "references": [],
            "candidate": None,
        },
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _atomic_write(
    path,
    data,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temp_name = (
        tempfile.mkstemp(
            dir=str(
                path.parent
            ),
            prefix=(
                "."
                + path.name
                + "."
            ),
        )
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:

            json.dump(
                data,
                handle,
                ensure_ascii=False,
                indent=2,
            )

            handle.flush()

            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp_name,
            path,
        )


    finally:

        try:
            os.unlink(
                temp_name
            )

        except FileNotFoundError:
            pass


def load_state(
    site_id,
    mode="LAB",
):

    site_id = safe_site_id(
        site_id
    )

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    path = _path(
        site_id
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


        if path.exists():

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

        else:

            data = _default(
                site_id,
                mode,
            )

            _atomic_write(
                path,
                data,
            )


        fcntl.flock(
            lock,
            fcntl.LOCK_UN,
        )


    return data


def save_state(
    site_id,
    data,
):

    site_id = safe_site_id(
        site_id
    )


    data[
        "site_id"
    ] = site_id

    data[
        "updated_at"
    ] = utc_now()


    STATE_DIR.mkdir(
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

        _atomic_write(
            _path(
                site_id
            ),
            data,
        )

        fcntl.flock(
            lock,
            fcntl.LOCK_UN,
        )


    return data


def candidate_path(
    site_id,
    filename,
):

    site_id = safe_site_id(
        site_id
    )

    directory = (
        CANDIDATE_DIR
        / site_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return (
        directory
        / filename
    )


def save_candidate(
    site_id,
    filename,
    data,
):

    path = candidate_path(
        site_id,
        filename,
    )

    _atomic_write(
        path,
        data,
    )

    return path
