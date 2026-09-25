#!/usr/bin/env python3

import json
import math
import os
from functools import lru_cache
from pathlib import Path

from config import (
    FRAME_WIDTH,
    FRAME_HEIGHT,
)


BASE_DIR = Path(
    __file__
).resolve().parent

INTRINSICS_FILE = (
    BASE_DIR
    / "calibration"
    / "camera_intrinsics.json"
)


# ============================================================
# Runtime tuning
# ============================================================
#
# CENTER ~= central ~56% of image width around
# calibrated optical principal point.
#
# Can be overridden from environment later.
# ============================================================

CENTER_HALF_WIDTH = float(
    os.getenv(
        "FUSION_CENTER_HALF_WIDTH",
        "0.28",
    )
)

CENTER_HALF_HEIGHT = float(
    os.getenv(
        "FUSION_CENTER_HALF_HEIGHT",
        "0.42",
    )
)

TRANSITION_HALF_WIDTH = float(
    os.getenv(
        "FUSION_TRANSITION_HALF_WIDTH",
        "0.40",
    )
)

TRANSITION_HALF_HEIGHT = float(
    os.getenv(
        "FUSION_TRANSITION_HALF_HEIGHT",
        "0.47",
    )
)

MATCH_BEARING_GATE_DEG = float(
    os.getenv(
        "FUSION_MATCH_BEARING_GATE_DEG",
        "5.0",
    )
)

MATCH_DISTANCE_ABS_M = float(
    os.getenv(
        "FUSION_MATCH_DISTANCE_ABS_M",
        "1.0",
    )
)

MATCH_DISTANCE_REL = float(
    os.getenv(
        "FUSION_MATCH_DISTANCE_REL",
        "0.30",
    )
)

TRACK_TTL_SEC = float(
    os.getenv(
        "FUSION_TRACK_TTL_SEC",
        "120.0",
    )
)


# ============================================================
# Trusted measurement freshness
# ============================================================
#
# Object identity may live much longer than one trusted
# CENTER measurement.
#
# Example:
#
#   TRACK_TTL_SEC       = 120s
#   ANCHOR_MAX_AGE_SEC  = 15s
#
# The same OBJ can survive, but an old CENTER measurement
# must not be reused indefinitely.
# ============================================================

ANCHOR_MAX_AGE_SEC = float(
    os.getenv(
        "FUSION_ANCHOR_MAX_AGE_SEC",
        "15.0",
    )
)


# ============================================================
# Presets that physically overlap
# ============================================================

OVERLAP_PAIRS = {
    frozenset((1, 2)),
    frozenset((2, 3)),
    frozenset((3, 4)),
    frozenset((4, 5)),

    frozenset((1, 6)),
    frozenset((6, 7)),
    frozenset((7, 8)),
    frozenset((8, 9)),

    frozenset((5, 9)),
}


# ============================================================
# Geometry helpers
# ============================================================

@lru_cache(maxsize=1)
def _principal_point():
    data = json.loads(
        INTRINSICS_FILE.read_text(
            encoding="utf-8"
        )
    )

    K = data["camera_matrix"]

    return (
        float(K[0][2]),
        float(K[1][2]),
        int(data["frame_width"]),
        int(data["frame_height"]),
    )


def classify_zone(
    bbox,
    *,
    frame_width=FRAME_WIDTH,
    frame_height=FRAME_HEIGHT,
):
    """
    Classify detection using bbox CENTER position.

    CENTER:
        preferred geometry measurement

    TRANSITION:
        usable, but CENTER should win if same object exists

    EDGE:
        least trusted; use CENTER anchor when available
    """

    (
        x1,
        y1,
        x2,
        y2,
    ) = bbox

    x = (
        float(x1)
        + float(x2)
    ) / 2.0

    y = (
        float(y1)
        + float(y2)
    ) / 2.0

    (
        native_cx,
        native_cy,
        native_w,
        native_h,
    ) = _principal_point()

    cx = (
        native_cx
        * frame_width
        / native_w
    )

    cy = (
        native_cy
        * frame_height
        / native_h
    )

    dx = abs(
        x - cx
    ) / float(
        frame_width
    )

    dy = abs(
        y - cy
    ) / float(
        frame_height
    )

    if (
        dx <= CENTER_HALF_WIDTH
        and
        dy <= CENTER_HALF_HEIGHT
    ):
        return "CENTER"

    if (
        dx <= TRANSITION_HALF_WIDTH
        and
        dy <= TRANSITION_HALF_HEIGHT
    ):
        return "TRANSITION"

    return "EDGE"


def circular_error_deg(
    a,
    b,
):
    return abs(
        (
            float(a)
            - float(b)
            + 180.0
        )
        % 360.0
        - 180.0
    )


def presets_can_overlap(
    preset_a,
    preset_b,
):
    preset_a = int(
        preset_a
    )

    preset_b = int(
        preset_b
    )

    if preset_a == preset_b:
        return True

    return (
        frozenset(
            (
                preset_a,
                preset_b,
            )
        )
        in OVERLAP_PAIRS
    )


def quality_rank(
    detection,
):
    zone = getattr(
        detection,
        "bearing_zone",
        "EDGE",
    )

    zone_score = {
        "CENTER": 300,
        "TRANSITION": 200,
        "EDGE": 100,
    }.get(
        zone,
        0,
    )

    distance_quality = getattr(
        detection,
        "distance_quality",
        "",
    )

    distance_score = 0

    if distance_quality in {
        "calibrated",
        "calibrated-low",
    }:
        distance_score = 30

    elif getattr(
        detection,
        "distance_m",
        None,
    ) is not None:
        distance_score = 10

    confidence_score = int(
        round(
            float(
                getattr(
                    detection,
                    "confidence",
                    0.0,
                )
            )
            * 20.0
        )
    )

    return (
        zone_score
        + distance_score
        + confidence_score
    )


# ============================================================
# Cross-preset fusion
# ============================================================

class CrossPresetObjectFusion:
    """
    Keep one logical object across overlapping PTZ presets.

    Example:

        P1 CENTER
          fire A
          92.3 deg
          4.2 m
            ↓
        becomes trusted anchor

        P2 EDGE
          same fire A
            ↓
        bbox/confidence remain from P2,
        but bearing/distance come from P1 anchor.

    This is geometric association,
    not visual re-identification.
    """

    def __init__(
        self,
        *,
        bearing_gate_deg=(
            MATCH_BEARING_GATE_DEG
        ),
        distance_abs_gate_m=(
            MATCH_DISTANCE_ABS_M
        ),
        distance_rel_gate=(
            MATCH_DISTANCE_REL
        ),
        ttl_sec=(
            TRACK_TTL_SEC
        ),
    ):
        self.bearing_gate_deg = float(
            bearing_gate_deg
        )

        self.distance_abs_gate_m = float(
            distance_abs_gate_m
        )

        self.distance_rel_gate = float(
            distance_rel_gate
        )

        self.ttl_sec = float(
            ttl_sec
        )

        self._tracks = {}
        self._next_id = 1


    def _purge(
        self,
        now_mono,
    ):
        expired = [
            object_id
            for object_id, track
            in self._tracks.items()
            if (
                now_mono
                - track["last_seen"]
                > self.ttl_sec
            )
        ]

        for object_id in expired:
            self._tracks.pop(
                object_id,
                None,
            )


    def _distance_matches(
        self,
        anchor,
        detection,
    ):
        """
        Distance is an association constraint ONLY when
        both observations have calibrated distance.

        Lab/extrapolated/unverified distance must not
        reject a geometrically valid cross-preset match.
        """

        trusted_qualities = {
            "calibrated",
            "calibrated-low",
        }

        anchor_quality = getattr(
            anchor,
            "distance_quality",
            "",
        )

        detection_quality = getattr(
            detection,
            "distance_quality",
            "",
        )


        if (
            anchor_quality
            not in trusted_qualities
            or
            detection_quality
            not in trusted_qualities
        ):
            return True


        a = getattr(
            anchor,
            "raw_distance_m",
            None,
        )

        if a is None:
            a = getattr(
                anchor,
                "distance_m",
                None,
            )


        b = getattr(
            detection,
            "raw_distance_m",
            None,
        )

        if b is None:
            b = getattr(
                detection,
                "distance_m",
                None,
            )


        if (
            a is None
            or b is None
        ):
            return True


        a = float(a)
        b = float(b)


        gate = max(
            self.distance_abs_gate_m,

            self.distance_rel_gate
            * max(
                abs(a),
                abs(b),
            ),
        )


        return (
            abs(a - b)
            <= gate
        )


    def _find_match(
        self,
        detection,
        preset,
    ):
        candidates = []

        for (
            object_id,
            track,
        ) in self._tracks.items():

            if (
                track["class"]
                != detection.canonical_class
            ):
                continue

            if not presets_can_overlap(
                track["last_preset"],
                preset,
            ):
                continue

            anchor = track[
                "anchor"
            ]

            error = (
                circular_error_deg(
                    getattr(
                        detection,
                        "raw_bearing_deg",
                        detection.bearing_deg,
                    ),
                    getattr(
                        anchor,
                        "raw_bearing_deg",
                        anchor.bearing_deg,
                    ),
                )
            )

            if (
                error
                > self.bearing_gate_deg
            ):
                continue

            if not self._distance_matches(
                anchor,
                detection,
            ):
                continue

            candidates.append(
                (
                    error,
                    object_id,
                    track,
                )
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda item:
                item[0]
        )

        return candidates[0]


    def _prepare_detection(
        self,
        detection,
        preset,
    ):
        #
        # Preserve sensor measurement BEFORE fusion.
        #
        if not hasattr(
            detection,
            "raw_bearing_deg",
        ):
            detection.raw_bearing_deg = float(
                detection.bearing_deg
            )

        if not hasattr(
            detection,
            "raw_distance_m",
        ):
            detection.raw_distance_m = (
                None
                if detection.distance_m
                is None
                else float(
                    detection.distance_m
                )
            )

        detection.bearing_zone = (
            classify_zone(
                detection.bbox
            )
        )

        detection.bearing_quality = {
            "CENTER": "HIGH",
            "TRANSITION": "MEDIUM",
            "EDGE": "LOW",
        }[
            detection.bearing_zone
        ]

        detection.measurement_source_preset = (
            int(preset)
        )

        detection.measurement_source_zone = (
            detection.bearing_zone
        )

        detection.measurement_fused = False

        # Anchor diagnostics are populated when this
        # observation matches an existing track.
        detection.fusion_anchor_age_sec = None
        detection.fusion_anchor_fresh = None
        detection.fusion_anchor_stale = False

        return detection


    def _create_track(
        self,
        detection,
        preset,
        now_mono,
    ):
        object_id = (
            f"OBJ-{self._next_id:04d}"
        )

        self._next_id += 1

        detection.object_id = (
            object_id
        )

        self._tracks[
            object_id
        ] = {
            "class":
                detection.canonical_class,

            "anchor":
                detection,

            "anchor_preset":
                int(preset),

            "last_preset":
                int(preset),

            # Timestamp of the measurement stored as anchor.
            # This is deliberately separate from last_seen.
            "anchor_seen":
                float(now_mono),

            "last_seen":
                float(now_mono),
        }

        return detection


    def _apply_anchor(
        self,
        detection,
        track,
    ):
        anchor = track[
            "anchor"
        ]

        detection.bearing_deg = float(
            anchor.bearing_deg
        )

        detection.distance_m = (
            anchor.distance_m
        )

        detection.distance_quality = (
            anchor.distance_quality
        )

        detection.gps = (
            anchor.gps
        )

        detection.measurement_source_preset = (
            track[
                "anchor_preset"
            ]
        )

        detection.measurement_source_zone = (
            getattr(
                anchor,
                "bearing_zone",
                "UNKNOWN",
            )
        )

        detection.measurement_fused = True

        return detection


    def fuse(
        self,
        detection,
        preset,
        now_mono,
    ):
        self._purge(
            now_mono
        )

        detection = (
            self._prepare_detection(
                detection,
                preset,
            )
        )

        match = self._find_match(
            detection,
            preset,
        )

        if match is None:
            return self._create_track(
                detection,
                preset,
                now_mono,
            )

        (
            _,
            object_id,
            track,
        ) = match

        detection.object_id = (
            object_id
        )

        anchor = track[
            "anchor"
        ]

        current_rank = (
            quality_rank(
                detection
            )
        )

        anchor_rank = (
            quality_rank(
                anchor
            )
        )


        anchor_zone = str(
            getattr(
                anchor,
                "bearing_zone",
                "EDGE",
            )
        ).upper()


        anchor_seen = float(
            track.get(
                "anchor_seen",
                track["last_seen"],
            )
        )


        anchor_age_sec = max(
            0.0,
            float(now_mono)
            - anchor_seen,
        )


        anchor_fresh = (
            anchor_age_sec
            <= ANCHOR_MAX_AGE_SEC
        )


        detection.fusion_anchor_age_sec = (
            anchor_age_sec
        )

        detection.fusion_anchor_fresh = (
            anchor_fresh
        )

        detection.fusion_anchor_stale = False


        # ====================================================
        # CENTER -> CENTER
        #
        # Always refresh the trusted CENTER anchor.
        #
        # Object identity can be old, but position is allowed
        # to move and the newest valid CENTER observation is
        # the best current measurement.
        # ====================================================

        if (
            anchor_zone == "CENTER"
            and
            detection.bearing_zone == "CENTER"
        ):

            track["anchor"] = (
                detection
            )

            track["anchor_preset"] = (
                int(preset)
            )

            track["anchor_seen"] = (
                float(now_mono)
            )

            detection.fusion_anchor_age_sec = (
                0.0
            )

            detection.fusion_anchor_fresh = (
                True
            )


        # ====================================================
        # Fresh CENTER -> lower-quality observation
        # ====================================================

        elif (
            anchor_zone == "CENTER"
            and
            detection.bearing_zone != "CENTER"
        ):

            if anchor_fresh:

                detection = (
                    self._apply_anchor(
                        detection,
                        track,
                    )
                )

            else:

                # Same logical object may still exist,
                # but its trusted CENTER measurement is stale.
                #
                # Keep raw current measurement and allow the
                # pending-alert layer to wait for fresh CENTER.
                detection.fusion_anchor_stale = (
                    True
                )


        # ====================================================
        # Better observation replaces lower-quality anchor
        # ====================================================

        elif (
            current_rank
            > anchor_rank
        ):

            track["anchor"] = (
                detection
            )

            track["anchor_preset"] = (
                int(preset)
            )

            track["anchor_seen"] = (
                float(now_mono)
            )

            detection.fusion_anchor_age_sec = (
                0.0
            )

            detection.fusion_anchor_fresh = (
                True
            )


        # ====================================================
        # Same-zone stale anchor
        #
        # Refresh non-CENTER tracking measurement so object
        # association does not depend forever on old raw data.
        # ====================================================

        elif (
            not anchor_fresh
            and
            detection.bearing_zone
            == anchor_zone
        ):

            track["anchor"] = (
                detection
            )

            track["anchor_preset"] = (
                int(preset)
            )

            track["anchor_seen"] = (
                float(now_mono)
            )

            detection.fusion_anchor_age_sec = (
                0.0
            )

            detection.fusion_anchor_fresh = (
                True
            )


        track["last_preset"] = (
            int(preset)
        )

        track["last_seen"] = (
            float(now_mono)
        )

        return detection


    def fuse_batch(
        self,
        detections,
        preset,
        now_mono,
    ):
        return [
            self.fuse(
                detection,
                preset,
                now_mono,
            )
            for detection
            in detections
        ]


    def snapshot(self):
        result = []

        for (
            object_id,
            track,
        ) in sorted(
            self._tracks.items()
        ):
            anchor = track[
                "anchor"
            ]

            result.append(
                {
                    "object_id":
                        object_id,

                    "class":
                        track["class"],

                    "anchor_preset":
                        track[
                            "anchor_preset"
                        ],

                    "anchor_zone":
                        getattr(
                            anchor,
                            "bearing_zone",
                            None,
                        ),

                    "bearing_deg":
                        float(
                            anchor.bearing_deg
                        ),

                    "distance_m":
                        anchor.distance_m,

                    "last_preset":
                        track[
                            "last_preset"
                        ],
                }
            )

        return result
