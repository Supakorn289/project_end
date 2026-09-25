from __future__ import annotations

import os

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from config import (
    PRESET_BEARING_DEG,
)

from cross_preset_fusion import (
    OVERLAP_PAIRS,
)


# ============================================================
# Safety timeout
# ============================================================
#
# Normal finalization is now PRESET-AWARE.
#
# This timeout is only the last-resort safety path if:
#
# - verification preset never becomes usable
# - PTZ/camera repeatedly fails
# - expected preset is never reached
#
# It is NOT the normal alert waiting period.
# ============================================================

DEFAULT_PENDING_SEC = float(
    os.getenv(
        "FUSION_PENDING_SAFETY_SEC",
        "90.0",
    )
)


DEFAULT_MAX_ITEMS = int(
    os.getenv(
        "FUSION_PENDING_MAX_ITEMS",
        "16",
    )
)


ZONE_RANK = {
    "EDGE": 1,
    "TRANSITION": 2,
    "CENTER": 3,
}


def circular_error_deg(
    a: float,
    b: float,
) -> float:

    return abs(
        (
            (
                float(a)
                - float(b)
                + 180.0
            )
            % 360.0
        )
        - 180.0
    )


def overlapping_presets(
    preset: int,
) -> list[int]:

    preset = int(
        preset
    )

    result: set[int] = set()

    for pair in OVERLAP_PAIRS:

        if preset not in pair:
            continue

        for value in pair:

            value = int(
                value
            )

            if value != preset:
                result.add(
                    value
                )

    return sorted(
        result
    )


def choose_verification_preset(
    detection: Any,
    source_preset: int,
) -> int | None:
    """
    Select the overlapping preset whose PHYSICAL CENTER
    is closest to the current raw global bearing.

    Example:

        detection from P2
        raw bearing ≈ 10°

        neighbors:
            P1 = 0°
            P3 = 90°

        verification target => P1
    """

    candidates = overlapping_presets(
        source_preset
    )

    if not candidates:
        return None


    bearing = getattr(
        detection,
        "raw_bearing_deg",
        None,
    )

    if bearing is None:

        bearing = getattr(
            detection,
            "bearing_deg",
            None,
        )

    if bearing is None:
        return None


    scored = []

    for preset in candidates:

        try:

            center = float(
                PRESET_BEARING_DEG[
                    preset
                ]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue


        scored.append(
            (
                circular_error_deg(
                    bearing,
                    center,
                ),
                preset,
            )
        )


    if not scored:
        return None


    scored.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )


    return int(
        scored[0][1]
    )


@dataclass
class PendingAlert:

    key: str

    detection: Any

    preset: int

    frame: Any

    first_seen: float

    last_seen: float

    verification_preset: (
        int | None
    )


class PendingAlertBuffer:
    """
    Pending alert state machine.

    Trusted CENTER/fused observation:
        -> alert immediately

    EDGE / TRANSITION:
        -> defer
        -> choose best overlapping verification preset
        -> wait until that preset is actually scanned

    If trusted observation of same object arrives:
        -> cancel pending
        -> current trusted observation becomes final alert

    If verification preset is scanned but no trusted
    match is produced:
        -> fallback immediately

    Safety timeout exists only as a last resort.

    This class does NOT:
        - move PTZ
        - send Telegram
        - change geometry
        - change cross-preset fusion
        - change alert cooldown
    """

    def __init__(
        self,
        timeout_sec: float = DEFAULT_PENDING_SEC,
        max_items: int = DEFAULT_MAX_ITEMS,
    ):

        self.timeout_sec = max(
            0.0,
            float(
                timeout_sec
            ),
        )

        self.max_items = max(
            1,
            int(
                max_items
            ),
        )

        self._items: dict[
            str,
            PendingAlert,
        ] = {}


    @property
    def pending_count(
        self,
    ) -> int:

        return len(
            self._items
        )


    @staticmethod
    def _key(
        detection: Any,
        preset: int,
    ) -> str:

        object_id = getattr(
            detection,
            "object_id",
            None,
        )

        if object_id:

            return (
                f"object:"
                f"{object_id}"
            )


        class_name = getattr(
            detection,
            "canonical_class",
            "unknown",
        )

        bbox = getattr(
            detection,
            "bbox",
            (),
        )


        try:

            bbox_key = ",".join(
                f"{float(value):.1f}"
                for value
                in bbox
            )

        except Exception:

            bbox_key = repr(
                bbox
            )


        return (
            f"legacy:"
            f"{class_name}:"
            f"p{int(preset)}:"
            f"{bbox_key}"
        )


    @staticmethod
    def _quality(
        detection: Any,
    ) -> tuple[int, float]:

        zone = str(
            getattr(
                detection,
                "bearing_zone",
                "EDGE",
            )
        ).upper()


        rank = ZONE_RANK.get(
            zone,
            0,
        )


        try:

            confidence = float(
                getattr(
                    detection,
                    "confidence",
                    0.0,
                )
            )

        except Exception:

            confidence = 0.0


        return (
            rank,
            confidence,
        )


    @staticmethod
    def _copy_frame(
        frame: Any,
    ) -> Any:

        try:

            return frame.copy()

        except Exception:

            return deepcopy(
                frame
            )


    def verification_target(
        self,
        detection: Any,
        preset: int,
    ) -> int | None:

        key = self._key(
            detection,
            preset,
        )

        item = self._items.get(
            key
        )

        if item is None:
            return None

        return (
            item.verification_preset
        )


    def defer(
        self,
        detection: Any,
        preset: int,
        frame: Any,
        now_mono: float,
        verification_preset: int | None = None,
    ) -> list[PendingAlert]:
        """
        Store/update pending object.

        Existing pending object keeps its ORIGINAL
        verification target so the target does not jump
        between presets while the sweep progresses.

        If bounded buffer is full, oldest item is returned
        for immediate fallback instead of being dropped.
        """

        now_mono = float(
            now_mono
        )

        preset = int(
            preset
        )

        key = self._key(
            detection,
            preset,
        )


        existing = self._items.get(
            key
        )


        if existing is not None:

            existing.last_seen = (
                now_mono
            )


            if (
                existing.verification_preset
                is None
                and
                verification_preset
                is not None
            ):

                existing.verification_preset = (
                    int(
                        verification_preset
                    )
                )


            # Keep best non-final observation
            if (
                self._quality(
                    detection
                )
                >
                self._quality(
                    existing.detection
                )
            ):

                existing.detection = (
                    deepcopy(
                        detection
                    )
                )

                existing.preset = (
                    preset
                )

                existing.frame = (
                    self._copy_frame(
                        frame
                    )
                )


            return []


        evicted: list[
            PendingAlert
        ] = []


        if (
            len(
                self._items
            )
            >= self.max_items
        ):

            oldest_key = min(
                self._items,

                key=lambda item_key: (
                    self._items[
                        item_key
                    ].first_seen
                ),
            )

            evicted.append(
                self._items.pop(
                    oldest_key
                )
            )


        if verification_preset is None:

            verification_preset = (
                choose_verification_preset(
                    detection,
                    preset,
                )
            )


        self._items[
            key
        ] = PendingAlert(

            key=key,

            detection=deepcopy(
                detection
            ),

            preset=preset,

            frame=self._copy_frame(
                frame
            ),

            first_seen=now_mono,

            last_seen=now_mono,

            verification_preset=(
                None
                if verification_preset
                is None
                else int(
                    verification_preset
                )
            ),
        )


        return evicted


    def cancel(
        self,
        detection: Any,
        preset: int,
    ) -> PendingAlert | None:

        key = self._key(
            detection,
            preset,
        )

        return self._items.pop(
            key,
            None,
        )


    def mark_preset_scanned(
        self,
        preset: int,
        now_mono: float,
    ) -> list[PendingAlert]:
        """
        Called only after a USABLE scan of preset.

        Any pending item whose verification target is this
        preset has now completed its passive verification.

        Trusted matching detections must cancel their pending
        item BEFORE this method is called.
        """

        preset = int(
            preset
        )

        now_mono = float(
            now_mono
        )


        completed_keys = [

            key

            for (
                key,
                item,
            )
            in self._items.items()

            if (
                item.verification_preset
                == preset
                and
                now_mono
                >= item.first_seen
            )
        ]


        completed_keys.sort(
            key=lambda key: (
                self._items[
                    key
                ].first_seen
            )
        )


        return [

            self._items.pop(
                key
            )

            for key
            in completed_keys
        ]


    def pop_expired(
        self,
        now_mono: float,
    ) -> list[PendingAlert]:

        now_mono = float(
            now_mono
        )


        expired_keys = [

            key

            for (
                key,
                item,
            )
            in self._items.items()

            if (
                now_mono
                - item.first_seen
                >= self.timeout_sec
            )
        ]


        expired_keys.sort(
            key=lambda key: (
                self._items[
                    key
                ].first_seen
            )
        )


        return [

            self._items.pop(
                key
            )

            for key
            in expired_keys
        ]
