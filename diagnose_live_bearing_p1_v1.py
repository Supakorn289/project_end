#!/usr/bin/env python3

import time
from pathlib import Path

import cv2

from camera import LatestFrameCamera
from ptz import PTZController

from test_ptz_repeatability_v1 import (
    compare_images,
    load_intrinsics,
    move_to_stable,
    save_match_debug,
)


REFERENCE_DIR = Path(
    "/home/fire/bearing_reference_20260908_141707"
)

OLD_GOOD_RUN = Path(
    "/home/fire/dynamic_bearing_validation/"
    "run_20260909_123105/images/"
    "s01_step01_p1.jpg"
)

OUT_DIR = Path(
    "/home/fire/bearing_live_p1_debug"
)


def summary(label, result):

    reason = result.get(
        "reason"
    )

    ratio = result.get(
        "ratio_matches"
    )

    inliers = result.get(
        "ransac_inliers"
    )

    stats = (
        result.get(
            "angle_stats"
        )
        or {}
    )

    median = stats.get(
        "median"
    )

    std = stats.get(
        "std"
    )

    spread = stats.get(
        "range"
    )

    print(
        f"{label:<24} "
        f"| ok={str(result.get('ok')):<5} "
        f"| reason={str(reason):<28} "
        f"| ratio={str(ratio):>5} "
        f"| inliers={str(inliers):>5} "
        f"| median={str(median):>12} "
        f"| std={str(std):>12} "
        f"| range={str(spread):>12}"
    )


def run_compare(
    label,
    image_a,
    image_b,
    camera_matrix,
    distortion,
    *,
    ratio_threshold,
    min_matches,
    debug_name=None,
):

    result = compare_images(
        image_a,
        image_b,
        camera_matrix,
        distortion,
        ratio_threshold=ratio_threshold,
        min_matches=min_matches,
    )

    summary(
        label,
        result,
    )

    if (
        result.get("ok")
        and
        debug_name
    ):
        save_match_debug(
            OUT_DIR
            / debug_name,
            image_a,
            image_b,
            result,
        )

    return result


def main():

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        _intrinsics,
        camera_matrix,
        distortion,
    ) = load_intrinsics()

    # ========================================================
    # Load frozen references
    # ========================================================

    refs = {}

    for preset in range(
        1,
        10,
    ):

        path = (
            REFERENCE_DIR
            / "images"
            / f"preset_{preset}.jpg"
        )

        image = cv2.imread(
            str(path)
        )

        if image is None:
            raise RuntimeError(
                f"Cannot read {path}"
            )

        refs[preset] = image


    # ========================================================
    # Historical control image
    # ========================================================

    old_good = cv2.imread(
        str(OLD_GOOD_RUN)
    )

    if old_good is None:
        raise RuntimeError(
            f"Cannot read old-good image: "
            f"{OLD_GOOD_RUN}"
        )


    # ========================================================
    # Capture current P1
    # ========================================================

    camera = (
        LatestFrameCamera()
        .start()
    )

    try:

        deadline = (
            time.monotonic()
            + 15.0
        )

        while (
            camera.latest(
                copy=False
            )
            is None
        ):

            if (
                time.monotonic()
                >= deadline
            ):
                raise RuntimeError(
                    "RTSP timeout"
                )

            time.sleep(
                0.1
            )

        ptz = PTZController()

        packet = move_to_stable(
            camera,
            ptz,
            1,
            first_move=True,
        )

        current = (
            packet.frame.copy()
        )

    finally:

        camera.stop()


    stamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    current_path = (
        OUT_DIR
        / f"current_p1_{stamp}.jpg"
    )

    cv2.imwrite(
        str(current_path),
        current,
    )

    print()
    print("=" * 150)
    print("LIVE P1 RAW MATCHER DIAGNOSTIC")
    print("=" * 150)

    print(
        f"Current frame : {current_path}"
    )

    print(
        f"Shape current : {current.shape}"
    )

    print(
        f"Shape frozen  : "
        f"{refs[1].shape}"
    )

    print(
        f"Shape old-good: "
        f"{old_good.shape}"
    )


    # ========================================================
    # CONTROL
    #
    # Frozen P1 vs Sep-9 image that previously matched.
    #
    # If this fails now -> software/reference path problem.
    # ========================================================

    print()
    print("-" * 150)
    print(
        "CONTROL: Frozen P1 -> "
        "historical successful P1"
    )
    print("-" * 150)

    run_compare(
        "FROZEN1 -> OLDGOOD",
        refs[1],
        old_good,
        camera_matrix,
        distortion,
        ratio_threshold=0.75,
        min_matches=20,
        debug_name=(
            "control_frozen1_oldgood.jpg"
        ),
    )


    # ========================================================
    # CURRENT vs historical successful P1
    # ========================================================

    print()
    print("-" * 150)
    print(
        "CURRENT P1 -> historical successful P1"
    )
    print("-" * 150)

    run_compare(
        "OLDGOOD -> CURRENT",
        old_good,
        current,
        camera_matrix,
        distortion,
        ratio_threshold=0.75,
        min_matches=20,
        debug_name=(
            "oldgood_current_075.jpg"
        ),
    )


    # ========================================================
    # PRODUCTION SETTINGS
    # Current P1 against entire frozen bank
    # ========================================================

    print()
    print("-" * 150)
    print(
        "CURRENT P1 vs FROZEN BANK "
        "| production ratio=0.75 min=20"
    )
    print("-" * 150)

    for preset in range(
        1,
        10,
    ):

        run_compare(
            f"REF P{preset} -> CURRENT",
            refs[preset],
            current,
            camera_matrix,
            distortion,
            ratio_threshold=0.75,
            min_matches=20,
            debug_name=(
                f"prod_ref{preset}_current.jpg"
            ),
        )


    # ========================================================
    # DIAGNOSTIC ONLY
    #
    # Relax ratio/minimum slightly.
    # DO NOT use this as production config yet.
    # ========================================================

    print()
    print("-" * 150)
    print(
        "CURRENT P1 vs FROZEN BANK "
        "| DIAGNOSTIC ONLY ratio=0.85 min=8"
    )
    print("-" * 150)

    for preset in range(
        1,
        10,
    ):

        run_compare(
            f"REF P{preset} -> CURRENT",
            refs[preset],
            current,
            camera_matrix,
            distortion,
            ratio_threshold=0.85,
            min_matches=8,
            debug_name=(
                f"relaxed_ref{preset}_current.jpg"
            ),
        )


    print()
    print("=" * 150)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 150)


if __name__ == "__main__":
    main()
