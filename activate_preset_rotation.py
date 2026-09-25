#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from preset_geometry import (
    PresetRotationRuntime,
)


BASE_DIR = Path(
    __file__
).resolve().parent

CALIBRATION_DIR = (
    BASE_DIR
    / "calibration"
)

SITES_DIR = (
    CALIBRATION_DIR
    / "sites"
)

ACTIVE_LINK = (
    CALIBRATION_DIR
    / "preset_rotation_ACTIVE.json"
)

ACTIVE_META = (
    CALIBRATION_DIR
    / "preset_rotation_ACTIVE.meta.json"
)


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def safe_site_id(value):
    value = str(value).strip()

    if not re.fullmatch(
        r"[A-Za-z0-9._-]{1,80}",
        value,
    ):
        raise SystemExit(
            "Invalid site-id. "
            "Use A-Z a-z 0-9 . _ - only"
        )

    return value


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--site-id",
        required=True,
    )

    parser.add_argument(
        "--candidate",
        required=True,
    )

    args = parser.parse_args()

    site_id = safe_site_id(
        args.site_id
    )

    candidate = Path(
        args.candidate
    ).resolve(
        strict=True
    )

    #
    # Validate candidate BEFORE activation.
    #
    validated = (
        PresetRotationRuntime(
            candidate,
            allow_final_fallback=False,
        )
    )

    metadata = (
        validated.metadata
    )

    destination_dir = (
        SITES_DIR
        / site_id
    )

    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        destination_dir
        / "preset_rotation.json"
    )

    temp_destination = (
        destination_dir
        / (
            ".preset_rotation."
            + str(os.getpid())
            + ".tmp"
        )
    )

    shutil.copy2(
        candidate,
        temp_destination,
    )

    os.chmod(
        temp_destination,
        0o444,
    )

    os.replace(
        temp_destination,
        destination,
    )

    digest = sha256_file(
        destination
    )

    #
    # Atomic ACTIVE symlink swap.
    #
    CALIBRATION_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    relative_target = os.path.relpath(
        destination,
        CALIBRATION_DIR,
    )

    temp_link = (
        CALIBRATION_DIR
        / (
            ".preset_rotation_ACTIVE."
            + str(os.getpid())
            + ".tmp"
        )
    )

    try:
        temp_link.unlink(
            missing_ok=True
        )

        os.symlink(
            relative_target,
            temp_link,
        )

        os.replace(
            temp_link,
            ACTIVE_LINK,
        )

    finally:
        try:
            temp_link.unlink(
                missing_ok=True
            )
        except OSError:
            pass

    meta = {
        "site_id": site_id,
        "active_file": str(
            destination
        ),
        "sha256": digest,
        "format": metadata.get(
            "format"
        ),
        "status": metadata.get(
            "status"
        ),
        "model": metadata.get(
            "model"
        ),
        "holdout_passed": (
            metadata.get(
                "independent_holdout_gate",
                {},
            ).get("passed")
            is True
        ),
    }

    meta_tmp = ACTIVE_META.with_suffix(
        ".tmp"
    )

    meta_tmp.write_text(
        json.dumps(
            meta,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.chmod(
        meta_tmp,
        0o444,
    )

    os.replace(
        meta_tmp,
        ACTIVE_META,
    )

    print(
        "ACTIVATION=PASS"
    )

    print(
        f"SITE_ID={site_id}"
    )

    print(
        f"ACTIVE={ACTIVE_LINK}"
    )

    print(
        f"TARGET={destination}"
    )

    print(
        f"SHA256={digest}"
    )

    print(
        "NORTH_OFFSET_ACTIVATED=NO"
    )

    print(
        "GPS_UNLOCKED=NO"
    )


if __name__ == "__main__":
    main()
