#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np

import solve_preset_rotation_v1 as solver


SITE_DIR = Path(
    Path(
        "/home/fire/current_site_setup_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

CURRENT_DIR = Path(
    Path(
        "/home/fire/current_cross_validation_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

OLD_DIR = Path(
    "/home/fire/"
    "cross_preset_validation_20260913_185110"
)


SOURCES = {
    "CAL": (
        SITE_DIR
        / "marks"
        / "marks.json"
    ),

    "OLD": (
        OLD_DIR
        / "cross_preset_marks.json"
    ),

    "NEW": (
        CURRENT_DIR
        / "cross_preset_marks.json"
    ),
}


OUTPUT = (
    CURRENT_DIR
    / "pair_rotation_source_audit_v1.json"
)


def rotation_difference_deg(
    R1,
    R2,
):
    delta = (
        R2
        @ R1.T
    )

    return solver.rotation_angle_deg(
        delta
    )


def axis_metrics(
    R,
):

    z = np.array(
        [0.0, 0.0, 1.0],
        dtype=float,
    )

    v = (
        R
        @ z
    )

    v = (
        v
        / np.linalg.norm(v)
    )

    az = math.degrees(
        math.atan2(
            float(v[0]),
            float(v[2]),
        )
    )

    el = math.degrees(
        math.atan2(
            -float(v[1]),
            math.hypot(
                float(v[0]),
                float(v[2]),
            ),
        )
    )

    return {
        "az_deg": float(
            solver.normalize_signed_deg(
                az
            )
        ),

        "el_deg": float(
            el
        ),
    }


def signed_difference(
    a,
    b,
):
    return solver.normalize_signed_deg(
        float(b)
        - float(a)
    )


def main():

    print("=" * 112)
    print(
        "PAIR RELATIVE-ROTATION "
        "SOURCE / SESSION AUDIT v1"
    )
    print("=" * 112)

    print(
        f"CAL : {SOURCES['CAL']}"
    )

    print(
        f"OLD : {SOURCES['OLD']}"
    )

    print(
        f"NEW : {SOURCES['NEW']}"
    )

    print()


    for name, path in SOURCES.items():

        if not path.exists():
            raise RuntimeError(
                f"{name} missing: "
                f"{path}"
            )


    K, D = solver.load_intrinsics()


    datasets = {}

    for name, path in SOURCES.items():

        datasets[name] = (
            solver.load_mark_file(
                path,
                name,
                K,
                D,
            )
        )


    fits = {
        name: {}
        for name in SOURCES
    }


    #
    # Fit every pair independently in each session.
    #
    for source_index, name in enumerate(
        SOURCES,
        start=1,
    ):

        for a, b in solver.PAIR_LIST:

            key = f"{a}-{b}"

            observations = (
                datasets[
                    name
                ][
                    key
                ]
            )

            if len(observations) < 3:

                raise RuntimeError(
                    f"{name} {key}: "
                    f"only "
                    f"{len(observations)} "
                    f"marks"
                )


            fit = (
                solver
                .robust_relative_rotation(
                    observations,
                    seed=(
                        source_index
                        * 10000
                        + a * 100
                        + b
                    ),
                )
            )


            metrics = axis_metrics(
                fit[
                    "R_b_to_a"
                ]
            )


            fits[
                name
            ][
                key
            ] = {
                **fit,
                **metrics,
            }


    payload = {
        "format": (
            "smart-fire-pair-rotation-"
            "source-audit-v1"
        ),

        "sources": {
            name: str(path)
            for name, path
            in SOURCES.items()
        },

        "pairs": {},
    }


    print(
        "PER-SOURCE EDGE FIT"
    )

    print("-" * 112)


    for a, b in solver.PAIR_LIST:

        key = f"{a}-{b}"

        print()
        print(
            f"PAIR {key}"
        )


        for name in (
            "CAL",
            "OLD",
            "NEW",
        ):

            item = (
                fits[
                    name
                ][
                    key
                ]
            )


            print(
                f"  {name} "
                f"| inliers="
                f"{item['inlier_count']:3d}/"
                f"{item['total_count']:<3d} "
                f"| med3D="
                f"{item['median_error_deg']:6.3f}° "
                f"| p90="
                f"{item['p90_error_deg']:6.3f}° "
                f"| rel-az="
                f"{item['az_deg']:+8.3f}° "
                f"| rel-el="
                f"{item['el_deg']:+7.3f}°"
            )


        comparisons = {}


        for left, right in (
            ("CAL", "OLD"),
            ("OLD", "NEW"),
            ("CAL", "NEW"),
        ):

            L = (
                fits[
                    left
                ][
                    key
                ]
            )

            R = (
                fits[
                    right
                ][
                    key
                ]
            )


            rotation_delta = (
                rotation_difference_deg(
                    L[
                        "R_b_to_a"
                    ],
                    R[
                        "R_b_to_a"
                    ],
                )
            )


            az_delta = (
                signed_difference(
                    L[
                        "az_deg"
                    ],
                    R[
                        "az_deg"
                    ],
                )
            )


            el_delta = float(
                R[
                    "el_deg"
                ]
                - L[
                    "el_deg"
                ]
            )


            comparison_key = (
                f"{left}_TO_{right}"
            )


            comparisons[
                comparison_key
            ] = {
                "rotation_difference_deg": (
                    float(
                        rotation_delta
                    )
                ),

                "relative_azimuth_change_deg": (
                    float(
                        az_delta
                    )
                ),

                "relative_elevation_change_deg": (
                    float(
                        el_delta
                    )
                ),
            }


            flag = (
                "STABLE"
                if rotation_delta <= 2.0
                else
                (
                    "REVIEW"
                    if rotation_delta <= 4.0
                    else
                    "SHIFTED"
                )
            )


            print(
                f"    "
                f"{left}->{right} "
                f"| rotΔ="
                f"{rotation_delta:7.3f}° "
                f"| azΔ="
                f"{az_delta:+7.3f}° "
                f"| elΔ="
                f"{el_delta:+7.3f}° "
                f"| {flag}"
            )


        payload[
            "pairs"
        ][
            key
        ] = {
            "sources": {
                name: {
                    "total_count": int(
                        fits[
                            name
                        ][
                            key
                        ][
                            "total_count"
                        ]
                    ),

                    "inlier_count": int(
                        fits[
                            name
                        ][
                            key
                        ][
                            "inlier_count"
                        ]
                    ),

                    "inlier_fraction": float(
                        fits[
                            name
                        ][
                            key
                        ][
                            "inlier_fraction"
                        ]
                    ),

                    "median_error_deg": float(
                        fits[
                            name
                        ][
                            key
                        ][
                            "median_error_deg"
                        ]
                    ),

                    "p90_error_deg": float(
                        fits[
                            name
                        ][
                            key
                        ][
                            "p90_error_deg"
                        ]
                    ),

                    "relative_azimuth_deg": float(
                        fits[
                            name
                        ][
                            key
                        ][
                            "az_deg"
                        ]
                    ),

                    "relative_elevation_deg": float(
                        fits[
                            name
                        ][
                            key
                        ][
                            "el_deg"
                        ]
                    ),
                }

                for name in SOURCES
            },

            "comparisons": comparisons,
        }


    #
    # Compact session-change summary.
    #
    print()
    print("=" * 112)

    print(
        "OLD -> NEW SESSION CHANGE SUMMARY"
    )

    print("=" * 112)


    ranked = []


    for a, b in solver.PAIR_LIST:

        key = f"{a}-{b}"

        item = (
            payload[
                "pairs"
            ][
                key
            ][
                "comparisons"
            ][
                "OLD_TO_NEW"
            ]
        )


        ranked.append(
            (
                item[
                    "rotation_difference_deg"
                ],
                key,
                item,
            )
        )


    ranked.sort(
        reverse=True
    )


    for delta, key, item in ranked:

        flag = (
            "STABLE"
            if delta <= 2.0
            else
            (
                "REVIEW"
                if delta <= 4.0
                else
                "SHIFTED"
            )
        )


        print(
            f"{key:>5} "
            f"| rotΔ="
            f"{delta:7.3f}° "
            f"| azΔ="
            f"{item['relative_azimuth_change_deg']:+7.3f}° "
            f"| elΔ="
            f"{item['relative_elevation_change_deg']:+7.3f}° "
            f"| {flag}"
        )


    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print(
        f"SAVED : {OUTPUT}"
    )

    print("=" * 112)


if __name__ == "__main__":
    main()
