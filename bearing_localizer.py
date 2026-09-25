#!/usr/bin/env python3

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2

from test_ptz_repeatability_v1 import (
    compare_images,
    load_intrinsics,
)


DEFAULT_REFERENCE_DIR = Path(
    "/opt/smart-fire-detection-v2/calibration/runtime_bearing_reference"
)

PRIMARY_BANK_TRIGGER_DEG = 10.0
BANK_CLUSTER_DEG = 2.0


def normalize_360(value):
    return float(value) % 360.0


def signed_diff_deg(a, b):
    return (
        (
            float(a)
            - float(b)
            + 180.0
        )
        % 360.0
    ) - 180.0


def circular_mean_deg(values, weights):
    if not values:
        raise ValueError("No values")

    sx = 0.0
    sy = 0.0

    for value, weight in zip(
        values,
        weights,
    ):
        rad = math.radians(
            float(value)
        )

        w = float(weight)

        sx += w * math.cos(rad)
        sy += w * math.sin(rad)

    if (
        abs(sx) < 1e-12
        and
        abs(sy) < 1e-12
    ):
        return normalize_360(
            values[0]
        )

    return normalize_360(
        math.degrees(
            math.atan2(
                sy,
                sx,
            )
        )
    )


def quality_tier(comparison):
    if not comparison.get(
        "ok",
        False,
    ):
        return None

    inliers = int(
        comparison.get(
            "ransac_inliers",
            0,
        )
    )

    stats = (
        comparison.get(
            "angle_stats"
        )
        or {}
    )

    std = stats.get("std")

    if std is None:
        return None

    std = float(std)

    # Internal project criteria.
    # NOT manufacturer specifications.
    if (
        inliers >= 100
        and
        std <= 0.35
    ):
        return "A"

    if (
        inliers >= 50
        and
        std <= 0.60
    ):
        return "B"

    if (
        inliers >= 20
        and
        std <= 0.75
    ):
        return "C"

    return None


def candidate_score(
    inliers,
    std,
):
    return (
        float(inliers)
        /
        max(
            float(std),
            0.05,
        )
    )


class BearingLocalizerCandidate:

    def __init__(
        self,
        reference_dir=DEFAULT_REFERENCE_DIR,
    ):
        self.reference_dir = Path(
            reference_dir
        )

        graph_file = (
            self.reference_dir
            / "bearing_azimuth_graph_candidate.json"
        )

        if not graph_file.exists():
            raise RuntimeError(
                f"Missing graph: {graph_file}"
            )

        graph = json.loads(
            graph_file.read_text(
                encoding="utf-8"
            )
        )

        self.reference_azimuth = {
            int(preset): float(
                values[
                    "reference_relative_azimuth_deg"
                ]
            )
            for preset, values
            in graph["presets"].items()
        }

        (
            self.intrinsics,
            self.camera_matrix,
            self.distortion,
        ) = load_intrinsics()

        self.reference_images = {}

        for preset in range(1, 10):
            image_path = (
                self.reference_dir
                / "images"
                / f"preset_{preset}.jpg"
            )

            image = cv2.imread(
                str(image_path)
            )

            if image is None:
                raise RuntimeError(
                    f"Cannot read {image_path}"
                )

            self.reference_images[
                preset
            ] = image

    def _compare_reference(
        self,
        current_frame,
        reference_preset,
    ):
        comparison = compare_images(
            self.reference_images[
                reference_preset
            ],
            current_frame,
            self.camera_matrix,
            self.distortion,
            ratio_threshold=0.75,
            min_matches=20,
        )

        tier = quality_tier(
            comparison
        )

        if tier is None:
            return None

        stats = comparison[
            "angle_stats"
        ]

        delta = float(
            stats["median"]
        )

        ref_az = float(
            self.reference_azimuth[
                reference_preset
            ]
        )

        center = normalize_360(
            ref_az
            + delta
        )

        inliers = int(
            comparison[
                "ransac_inliers"
            ]
        )

        std = float(
            stats["std"]
        )

        return {
            "reference_preset": (
                reference_preset
            ),
            "tier": tier,
            "inliers": inliers,
            "std_deg": std,
            "delta_deg": delta,
            "center_deg": center,
            "score": candidate_score(
                inliers,
                std,
            ),
        }

    def _bank_localize(
        self,
        current_frame,
    ):
        candidates = []

        for reference_preset in range(
            1,
            10,
        ):
            candidate = (
                self._compare_reference(
                    current_frame,
                    reference_preset,
                )
            )

            if candidate is not None:
                candidates.append(
                    candidate
                )

        if not candidates:
            return {
                "valid": False,
                "method": (
                    "REFERENCE_BANK"
                ),
                "reason": (
                    "no_valid_reference"
                ),
                "candidates": [],
            }

        tier = None

        for wanted in (
            "A",
            "B",
            "C",
        ):
            if any(
                c["tier"] == wanted
                for c in candidates
            ):
                tier = wanted
                break

        selected = [
            c
            for c in candidates
            if c["tier"] == tier
        ]

        best_cluster = None
        best_score = None

        for seed in selected:
            members = [
                c
                for c in selected
                if abs(
                    signed_diff_deg(
                        c["center_deg"],
                        seed["center_deg"],
                    )
                )
                <= BANK_CLUSTER_DEG
            ]

            score = sum(
                c["score"]
                for c in members
            )

            if (
                best_score is None
                or
                score > best_score
            ):
                best_score = score
                best_cluster = members

        if not best_cluster:
            return {
                "valid": False,
                "method": (
                    "REFERENCE_BANK"
                ),
                "reason": (
                    "no_consensus_cluster"
                ),
                "candidates": candidates,
            }

        center = circular_mean_deg(
            [
                c["center_deg"]
                for c in best_cluster
            ],
            [
                c["score"]
                for c in best_cluster
            ],
        )

        spread = max(
            abs(
                signed_diff_deg(
                    c["center_deg"],
                    center,
                )
            )
            for c in best_cluster
        )

        if tier == "A":
            quality = "GOOD"
        else:
            quality = "REVIEW"

        return {
            "valid": True,
            "method": "REFERENCE_BANK",
            "quality": quality,
            "tier": tier,
            "center_deg": center,
            "spread_deg": spread,
            "references": [
                c["reference_preset"]
                for c in best_cluster
            ],
            "candidates": candidates,
        }

    def localize(
        self,
        current_frame,
        requested_preset,
    ):
        requested_preset = int(
            requested_preset
        )

        if requested_preset not in (
            self.reference_azimuth
        ):
            raise ValueError(
                f"Unknown preset "
                f"{requested_preset}"
            )

        primary = (
            self._compare_reference(
                current_frame,
                requested_preset,
            )
        )

        # ----------------------------------------
        # Strong same-preset localization
        # ----------------------------------------

        if (
            primary is not None
            and
            primary["tier"] == "A"
            and
            abs(
                primary["delta_deg"]
            )
            <= PRIMARY_BANK_TRIGGER_DEG
        ):
            return {
                "valid": True,
                "method": (
                    "PRIMARY_SAME_PRESET"
                ),
                "quality": "GOOD",
                "requested_preset": (
                    requested_preset
                ),
                "center_deg": (
                    primary["center_deg"]
                ),
                "primary": primary,
                "bank": None,
            }

        # ----------------------------------------
        # Large shift or weak primary:
        # use bank as independent localization
        # ----------------------------------------

        bank = self._bank_localize(
            current_frame
        )

        if bank.get(
            "valid",
            False,
        ):
            return {
                "valid": True,
                "method": (
                    "REFERENCE_BANK_FALLBACK"
                ),
                "quality": (
                    bank["quality"]
                ),
                "requested_preset": (
                    requested_preset
                ),
                "center_deg": (
                    bank["center_deg"]
                ),
                "primary": primary,
                "bank": bank,
            }

        # ----------------------------------------
        # Bank failed but primary still usable
        # ----------------------------------------

        if primary is not None:
            return {
                "valid": True,
                "method": (
                    "PRIMARY_DEGRADED"
                ),
                "quality": "REVIEW",
                "requested_preset": (
                    requested_preset
                ),
                "center_deg": (
                    primary["center_deg"]
                ),
                "primary": primary,
                "bank": bank,
            }

        return {
            "valid": False,
            "method": "FAILED",
            "quality": "INVALID",
            "requested_preset": (
                requested_preset
            ),
            "center_deg": None,
            "primary": None,
            "bank": bank,
        }
