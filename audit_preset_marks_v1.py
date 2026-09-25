#!/usr/bin/env python3

import json
import os
from pathlib import Path

import cv2
import numpy as np

from config import PRESET_BEARING_DEG
from geometry import calibrated_horizontal_offset_deg


PAIRS = [
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),
    (1, 6),
    (6, 7),
    (7, 8),
    (8, 9),
    (5, 9),
]


def normalize_signed_deg(value):
    return (
        (
            float(value)
            + 180.0
        )
        % 360.0
    ) - 180.0


def unwrap_near(value, reference):

    return (
        float(value)
        + 360.0
        * round(
            (
                float(reference)
                - float(value)
            )
            / 360.0
        )
    )


def site_dir():

    value = os.environ.get(
        "MARK_SITE_DIR"
    )

    if value:
        return Path(value)

    return Path(
        Path(
            "/home/fire/"
            "current_site_setup_path.txt"
        ).read_text(
            encoding="utf-8"
        ).strip()
    )


def densest_cluster(
    values,
    radius=1.50,
):

    values = np.asarray(
        values,
        dtype=float,
    )

    best = None

    for seed in values:

        mask = (
            np.abs(
                values - seed
            )
            <= radius
        )

        selected = values[
            mask
        ]

        if len(selected) == 0:
            continue

        center = float(
            np.median(
                selected
            )
        )

        mask = (
            np.abs(
                values - center
            )
            <= radius
        )

        selected = values[
            mask
        ]

        score = (
            len(selected),
            -float(
                np.std(
                    selected
                )
            ),
        )

        if (
            best is None
            or
            score > best["score"]
        ):

            best = {
                "score": score,
                "mask": mask,
                "values": selected,
                "center": float(
                    np.median(
                        selected
                    )
                ),
            }

    return best


def main():

    root = site_dir()

    marks_file = (
        root
        / "marks"
        / "marks.json"
    )

    data = json.loads(
        marks_file.read_text(
            encoding="utf-8"
        )
    )

    image = cv2.imread(
        str(
            root
            / "captures"
            / "preset_1.jpg"
        )
    )

    if image is None:
        raise RuntimeError(
            "Cannot read preset_1.jpg"
        )

    height, width = (
        image.shape[:2]
    )

    p1 = float(
        PRESET_BEARING_DEG[1]
    )

    expected = {
        preset:
        normalize_signed_deg(
            float(
                PRESET_BEARING_DEG[
                    preset
                ]
            )
            - p1
        )
        for preset
        in range(1, 10)
    }

    print(
        "=" * 100
    )
    print(
        "MARK GEOMETRY AUDIT"
    )
    print(
        "=" * 100
    )

    for a, b in PAIRS:

        key = f"{a}-{b}"

        marks = (
            data[
                "pairs"
            ][key]
        )

        nominal = (
            expected[b]
            - expected[a]
        )

        values = []

        for mark in marks:

            xa, ya = mark["a"]
            xb, yb = mark["b"]

            ray_a = (
                calibrated_horizontal_offset_deg(
                    float(xa),
                    float(ya),
                    width,
                    height,
                )
            )

            ray_b = (
                calibrated_horizontal_offset_deg(
                    float(xb),
                    float(yb),
                    width,
                    height,
                )
            )

            delta = unwrap_near(
                normalize_signed_deg(
                    ray_a - ray_b
                ),
                nominal,
            )

            values.append(
                float(delta)
            )

        cluster = densest_cluster(
            values,
            radius=1.50,
        )

        mask = cluster[
            "mask"
        ]

        selected = cluster[
            "values"
        ]

        print()
        print(
            f"PAIR {key}"
        )

        print(
            f" nominal    = "
            f"{nominal:+.3f}°"
        )

        print(
            f" marks      = "
            f"{len(values)}"
        )

        print(
            f" best group = "
            f"{len(selected)}/"
            f"{len(values)}"
        )

        print(
            f" center     = "
            f"{cluster['center']:+.3f}°"
        )

        print(
            f" std        = "
            f"{np.std(selected):.3f}°"
        )

        print(
            " values:"
        )

        for index, (
            value,
            keep,
        ) in enumerate(
            zip(
                values,
                mask,
            ),
            start=1,
        ):

            flag = (
                "KEEP"
                if keep
                else
                "BAD "
            )

            print(
                f"   #{index:02d} "
                f"{value:+9.3f}° "
                f"{flag}"
            )

    print()
    print(
        "=" * 100
    )


if __name__ == "__main__":
    main()
