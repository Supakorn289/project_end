#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cv2

from bearing_localizer_candidate import (
    BearingLocalizerCandidate,
)


IMAGE_RE = re.compile(
    r"^s(\d+)_step(\d+)_p(\d+)\.jpg$"
)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "run_dirs",
        nargs="+",
    )

    args = parser.parse_args()

    localizer = (
        BearingLocalizerCandidate()
    )

    all_runs = []

    total = 0
    valid = 0
    invalid = 0
    primary_count = 0
    bank_count = 0
    degraded_count = 0

    for run_text in args.run_dirs:

        run_dir = Path(
            run_text
        )

        image_dir = (
            run_dir
            / "images"
        )

        files = []

        for path in sorted(
            image_dir.glob("*.jpg")
        ):
            match = IMAGE_RE.match(
                path.name
            )

            if not match:
                continue

            files.append(
                (
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    path,
                )
            )

        print()
        print("=" * 100)
        print(
            f"RUN: {run_dir}"
        )
        print(
            f"IMAGES: {len(files)}"
        )
        print("=" * 100)

        run_records = []

        for (
            sweep,
            step,
            preset,
            path,
        ) in files:

            frame = cv2.imread(
                str(path)
            )

            if frame is None:
                raise RuntimeError(
                    f"Cannot read {path}"
                )

            result = (
                localizer.localize(
                    frame,
                    preset,
                )
            )

            total += 1

            if result["valid"]:
                valid += 1
            else:
                invalid += 1

            method = result[
                "method"
            ]

            if method == (
                "PRIMARY_SAME_PRESET"
            ):
                primary_count += 1

            elif method == (
                "REFERENCE_BANK_FALLBACK"
            ):
                bank_count += 1

            elif method == (
                "PRIMARY_DEGRADED"
            ):
                degraded_count += 1

            center = result.get(
                "center_deg"
            )

            center_text = (
                "INVALID"
                if center is None
                else f"{center:8.3f}°"
            )

            print(
                f"S{sweep} "
                f"STEP={step:02d} "
                f"P{preset} "
                f"| {method:24s} "
                f"| {result['quality']:7s} "
                f"| center={center_text}"
            )

            run_records.append(
                {
                    "sweep": sweep,
                    "step": step,
                    "preset": preset,
                    "image": str(path),
                    "result": result,
                }
            )

        all_runs.append(
            {
                "run_dir": str(
                    run_dir
                ),
                "records": (
                    run_records
                ),
            }
        )

    print()
    print("=" * 100)
    print(
        "BEARING LOCALIZER REPLAY SUMMARY"
    )
    print("=" * 100)

    print(
        f"Total arrivals       : {total}"
    )
    print(
        f"Valid                : {valid}"
    )
    print(
        f"Invalid              : {invalid}"
    )
    print(
        f"Primary same-preset  : {primary_count}"
    )
    print(
        f"Reference-bank       : {bank_count}"
    )
    print(
        f"Primary degraded     : {degraded_count}"
    )

    if (
        total > 0
        and
        invalid == 0
    ):
        status = (
            "PASS_FOR_RUNTIME_INTEGRATION_TEST"
        )
    else:
        status = "NOT_READY"

    print(
        f"RESULT               : {status}"
    )

    output = Path(
        "/home/fire/"
        "bearing_localizer_replay_v1.json"
    )

    output.write_text(
        json.dumps(
            {
                "version": 1,
                "status": status,
                "summary": {
                    "total": total,
                    "valid": valid,
                    "invalid": invalid,
                    "primary": (
                        primary_count
                    ),
                    "bank": bank_count,
                    "degraded": (
                        degraded_count
                    ),
                },
                "runs": all_runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Saved                : "
        f"{output}"
    )

    print("=" * 100)


if __name__ == "__main__":
    main()
