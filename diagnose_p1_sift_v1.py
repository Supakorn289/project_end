#!/usr/bin/env python3

from pathlib import Path

import cv2
import numpy as np


FROZEN_DIR = Path(
    "/home/fire/bearing_reference_20260908_141707/images"
)

OLD_GOOD = Path(
    "/home/fire/dynamic_bearing_validation/"
    "run_20260909_123105/images/"
    "s01_step01_p1.jpg"
)

CURRENT_DIR = Path(
    "/home/fire/bearing_live_p1_debug"
)

OUT_DIR = (
    CURRENT_DIR
    / "sift_diagnostic"
)


def newest_current():

    files = sorted(
        CURRENT_DIR.glob(
            "current_p1_*.jpg"
        )
    )

    if not files:
        raise RuntimeError(
            "No current P1 image"
        )

    return files[-1]


def load(path):

    image = cv2.imread(
        str(path)
    )

    if image is None:
        raise RuntimeError(
            f"Cannot read {path}"
        )

    return image


def compare(
    label,
    image_a,
    image_b,
    ratio,
):

    gray_a = cv2.cvtColor(
        image_a,
        cv2.COLOR_BGR2GRAY,
    )

    gray_b = cv2.cvtColor(
        image_b,
        cv2.COLOR_BGR2GRAY,
    )

    sift = cv2.SIFT_create(
        nfeatures=5000
    )

    ka, da = sift.detectAndCompute(
        gray_a,
        None,
    )

    kb, db = sift.detectAndCompute(
        gray_b,
        None,
    )

    if (
        da is None
        or
        db is None
    ):
        print(
            f"{label:<22} "
            "| NO DESCRIPTORS"
        )
        return None

    matcher = cv2.BFMatcher(
        cv2.NORM_L2
    )

    knn = matcher.knnMatch(
        da,
        db,
        k=2,
    )

    good = []

    for pair in knn:

        if len(pair) < 2:
            continue

        m, n = pair

        if (
            m.distance
            <
            ratio * n.distance
        ):
            good.append(m)

    result = {
        "label": label,
        "key_a": len(ka),
        "key_b": len(kb),
        "good": len(good),
        "inliers": 0,
        "inlier_ratio": 0.0,
        "reprojection_median": None,
    }

    if len(good) < 4:

        print(
            f"{label:<22} "
            f"| kp={len(ka):4d}/{len(kb):4d} "
            f"| good={len(good):4d} "
            "| HOMOGRAPHY=NO"
        )

        return result

    pa = np.float32(
        [
            ka[m.queryIdx].pt
            for m in good
        ]
    )

    pb = np.float32(
        [
            kb[m.trainIdx].pt
            for m in good
        ]
    )

    H, mask = cv2.findHomography(
        pa,
        pb,
        cv2.RANSAC,
        3.0,
    )

    if (
        H is None
        or
        mask is None
    ):

        print(
            f"{label:<22} "
            f"| good={len(good):4d} "
            "| HOMOGRAPHY=FAIL"
        )

        return result

    mask = (
        mask
        .reshape(-1)
        .astype(bool)
    )

    inliers = int(
        mask.sum()
    )

    result[
        "inliers"
    ] = inliers

    result[
        "inlier_ratio"
    ] = (
        inliers
        / len(good)
        if good
        else 0.0
    )

    if inliers:

        src = pa[
            mask
        ].reshape(
            -1,
            1,
            2,
        )

        dst = pb[
            mask
        ]

        projected = (
            cv2.perspectiveTransform(
                src,
                H,
            )
            .reshape(
                -1,
                2,
            )
        )

        error = np.linalg.norm(
            projected
            - dst,
            axis=1,
        )

        result[
            "reprojection_median"
        ] = float(
            np.median(
                error
            )
        )

    print(
        f"{label:<22} "
        f"| kp={len(ka):4d}/{len(kb):4d} "
        f"| good={len(good):4d} "
        f"| inliers={inliers:4d} "
        f"| support="
        f"{result['inlier_ratio']*100:6.2f}% "
        f"| reproj="
        f"{result['reprojection_median']}"
    )

    if inliers >= 8:

        selected = [
liers >= 8:

        selected = [
            match
            for match, keep
            in zip(
                good,
                mask,
            )
            if keep
        ]

        debug = cv2.drawMatches(
            image_a,
            ka,
            image_b,
            kb,
            selected[:100],
            None,
            flags=(
                cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS
            ),
        )

        safe = (
            label
            .lower()
            .replace(" ", "_")
            .replace(">", "")
        )

        cv2.imwrite(
            str(
                OUT_DIR
                / f"{safe}_r{ratio:.2f}.jpg"
            ),
            debug,
        )

    return result


def make_montage(
    frozen,
    old_good,
    current,
):

    images = [
        ("FROZEN P1", frozen),
        ("SEP 9 OLD-GOOD", old_good),
        ("SEP 11 CURRENT", current),
    ]

    blocks = []

    for label, image in images:

        img = image.copy()

        cv2.rectangle(
            img,
            (0, = image.copy()

        cv2.rectangle(
            img,
            (0, 0),
            (1280, 60),
            (0, 0, 0),
            -1,
        )

        cv2.putText(
            img,
            label,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        blocks.append(img)

    montage = np.vstack(
        blocks
    )

    path = (
        OUT_DIR
        / "p1_state_comparison.jpg"
    )

    cv2.imwrite(
        str(path),
        montage,
    )

    print(
        f"\nMontage: {path}"
    )


def main():

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_path = (
        newest_current()
    )

    frozen1 = load(
        FROZEN_DIR
        / "preset_1.jpg"
    )

    old_good = load(
        OLD_GOOD
    )

    current = load(
        current_path
    )

    print(
        f"Current: {current_path}"
    )

    print()
    print(
        "=" * 110
    )
    print(
        "SIFT CONTROL"
    )
    print(
        "=" * 110
    )

    for ratio in (
        0.70,
        0.75,
        0.80,
    ):

        print(
            f"\nRATIO={ratio:.2f}"
        )

        compare(
            "FROZEN1 > OLDGOOD",
            frozen1,
            old_good,
            ratio,
        )

        compare(
            "OLDGOOD > CURRENT",
            old_good,
            current,
            ratio,
        )

        > CURRENT",
            old_good,
            current,
            ratio,
        )

        compare(
            "FROZEN1 > CURRENT",
            frozen1,
            current,
            ratio,
        )

    print()
    print(
        "=" * 110
    )
    print(
        "SIFT FROZEN BANK -> CURRENT"
    )
    print(
        "=" * 110
    )

    for preset in range(
        1,
        10,
    ):

        ref = load(
            FROZEN_DIR
            / f"preset_{preset}.jpg"
        )

        compare(
            f"REF P{preset} > CURRENT",
            ref,
            current,
            0.75,
        )

    make_montage(
        frozen1,
        old_good,
        current,
    )


if __name__ == "__main__":
    main()
