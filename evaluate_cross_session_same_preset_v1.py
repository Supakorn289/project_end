#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np

import solve_preset_rotation_v1 as solver


ROOT = Path(
    Path(
        "/home/fire/current_cross_validation_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

MARK_FILE = (
    ROOT
    / "cross_session_same_preset_marks.json"
)

OUTPUT_FILE = (
    ROOT
    / "cross_session_same_preset_result_v1.json"
)

PRESETS = [
    "P1",
    "P6",
    "P7",
    "P8",
    "P9",
]


def main():

    if not MARK_FILE.exists():

        raise RuntimeError(
            f"Missing {MARK_FILE}"
        )


    data=json.loads(
        MARK_FILE.read_text(
            encoding="utf-8"
        )
    )


    K,D=solver.load_intrinsics()


    results={}


    print("="*108)

    print(
        "CROSS-SESSION SAME-PRESET "
        "3-D POSE TEST v1"
    )

    print("="*108)


    for number,name in enumerate(
        PRESETS,
        start=1,
    ):

        marks=(
            data
            .get("presets",{})
            .get(name,[])
        )


        if len(marks)<3:

            raise RuntimeError(
                f"{name}: "
                f"need >=3 marks"
            )


        observations=[]


        for index,mark in enumerate(
            marks,
            start=1,
        ):

            xo,yo=mark["old"]
            xn,yn=mark["new"]


            ray_old=(
                solver.pixel_to_unit_ray(
                    xo,
                    yo,
                    K,
                    D,
                )
            )


            ray_new=(
                solver.pixel_to_unit_ray(
                    xn,
                    yn,
                    K,
                    D,
                )
            )


            observations.append({
                "source":"cross_session",
                "index":index,
                "ray_a":ray_old,
                "ray_b":ray_new,
            })


        #
        # Fits R_new_to_old:
        #
        # old_ray ≈ R @ new_ray
        #
        fit=(
            solver.robust_relative_rotation(
                observations,
                seed=9000+number,
            )
        )


        R=fit[
            "R_b_to_a"
        ]


        axis=(
            R
            @ np.array(
                [0.0,0.0,1.0],
                dtype=float,
            )
        )


        az=math.degrees(
            math.atan2(
                float(axis[0]),
                float(axis[2]),
            )
        )


        el=math.degrees(
            math.atan2(
                -float(axis[1]),
                math.hypot(
                    float(axis[0]),
                    float(axis[2]),
                ),
            )
        )


        rot_total=(
            solver.rotation_angle_deg(
                R
            )
        )


        all_before=[]
        all_after=[]


        for obs in observations:

            before=(
                solver.angle_between_deg(
                    obs["ray_a"],
                    obs["ray_b"],
                )
            )


            predicted=(
                R
                @ obs["ray_b"]
            )


            after=(
                solver.angle_between_deg(
                    obs["ray_a"],
                    predicted,
                )
            )


            all_before.append(
                before
            )

            all_after.append(
                after
            )


        before=np.asarray(
            all_before,
            dtype=float,
        )

        after=np.asarray(
            all_after,
            dtype=float,
        )


        median_before=float(
            np.median(before)
        )

        median_after=float(
            np.median(after)
        )

        p90_after=float(
            np.percentile(
                after,
                90,
            )
        )

        max_after=float(
            np.max(after)
        )


        #
        # Interpretation
        #
        if (
            rot_total <= 1.5
            and
            median_after <= 1.0
            and
            p90_after <= 2.0
        ):
            status=(
                "SESSION_STABLE"
            )

        elif (
            rot_total > 2.0
            and
            median_after <= 1.0
            and
            p90_after <= 2.0
        ):
            status=(
                "SESSION_ROTATION_SHIFT"
            )

        else:
            status=(
                "NON_RIGID_OR_PARALLAX_REVIEW"
            )


        results[name]={
            "target_count":
                len(marks),

            "rotation_difference_deg":
                float(rot_total),

            "rotation_azimuth_component_deg":
                float(
                    solver.normalize_signed_deg(
                        az
                    )
                ),

            "rotation_elevation_component_deg":
                float(el),

            "median_raw_ray_difference_deg":
                median_before,

            "median_post_rotation_residual_deg":
                median_after,

            "p90_post_rotation_residual_deg":
                p90_after,

            "max_post_rotation_residual_deg":
                max_after,

            "ransac_inliers":
                int(
                    fit["inlier_count"]
                ),

            "ransac_total":
                int(
                    fit["total_count"]
                ),

            "ransac_support":
                float(
                    fit[
                        "inlier_fraction"
                    ]
                ),

            "status":
                status,
        }


        print()

        print(
            f"{name}"
        )

        print(
            f"  marks              : "
            f"{len(marks)}"
        )

        print(
            f"  session rotΔ       : "
            f"{rot_total:.3f}°"
        )

        print(
            f"  az component       : "
            f"{solver.normalize_signed_deg(az):+.3f}°"
        )

        print(
            f"  elev component     : "
            f"{el:+.3f}°"
        )

        print(
            f"  raw median ray Δ   : "
            f"{median_before:.3f}°"
        )

        print(
            f"  after-rotation med : "
            f"{median_after:.3f}°"
        )

        print(
            f"  after-rotation P90 : "
            f"{p90_after:.3f}°"
        )

        print(
            f"  after-rotation max : "
            f"{max_after:.3f}°"
        )

        print(
            f"  RANSAC             : "
            f"{fit['inlier_count']}/"
            f"{fit['total_count']}"
        )

        print(
            f"  RESULT             : "
            f"{status}"
        )


    output={
        "format":
            "smart-fire-cross-session-same-preset-result-v1",

        "mark_file":
            str(MARK_FILE),

        "presets":
            results,
    }


    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    print()
    print("="*108)

    print(
        "DECISION SUMMARY"
    )

    print("="*108)


    for name in PRESETS:

        item=results[name]

        print(
            f"{name:>3} "
            f"| rotΔ="
            f"{item['rotation_difference_deg']:7.3f}° "
            f"| residual med="
            f"{item['median_post_rotation_residual_deg']:6.3f}° "
            f"| p90="
            f"{item['p90_post_rotation_residual_deg']:6.3f}° "
            f"| "
            f"{item['status']}"
        )


    print()
    print(
        f"SAVED : {OUTPUT_FILE}"
    )

    print("="*108)


if __name__=="__main__":
    main()
