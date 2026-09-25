#!/usr/bin/env python3

import json
import math
import os
import threading
from pathlib import Path

import numpy as np

from geometry import (
    calibrated_pixel_to_unit_ray,
    normalize_bearing,
)


BASE_DIR = Path(
    __file__
).resolve().parent

CALIBRATION_DIR = (
    BASE_DIR
    / "calibration"
)

DEFAULT_ACTIVE_ROTATION_FILE = (
    CALIBRATION_DIR
    / "preset_rotation_ACTIVE.json"
)

DEFAULT_FINAL_ROTATION_FILE = (
    CALIBRATION_DIR
    / "preset_rotation_FINAL.json"
)

DEFAULT_LEGACY_GEOMETRY_FILE = (
    CALIBRATION_DIR
    / "preset_geometry.json"
)


def _configured_rotation_path():
    value = os.environ.get(
        "PRESET_ROTATION_ACTIVE_FILE",
        "",
    ).strip()

    if value:
        path = Path(value)

        if not path.is_absolute():
            path = (
                BASE_DIR
                / path
            )

        return path

    return DEFAULT_ACTIVE_ROTATION_FILE


def _rotation_error_deg(R):
    """
    Rotation magnitude for diagnostics.
    """
    value = (
        np.trace(R)
        - 1.0
    ) / 2.0

    value = float(
        np.clip(
            value,
            -1.0,
            1.0,
        )
    )

    return math.degrees(
        math.acos(value)
    )


class PresetRotationRuntime:
    """
    Dynamic per-site preset rotation runtime.

    ACTIVE calibration can be replaced atomically
    while the service is running.

    No reference images.
    No ORB/SIFT.
    No scene matching.

    Q[preset]:
        camera ray
            ->
        P1/reference coordinate frame
    """

    def __init__(
        self,
        path=None,
        *,
        allow_final_fallback=True,
    ):
        self.path = (
            Path(path)
            if path is not None
            else _configured_rotation_path()
        )

        self.allow_final_fallback = bool(
            allow_final_fallback
        )

        self._lock = threading.RLock()

        self._fingerprint = None
        self._resolved_path = None
        self._matrices = {}
        self._metadata = None

        self.reload(
            force=True
        )


    def _effective_path(self):
        path = self.path

        if path.exists():
            return path

        if (
            self.allow_final_fallback
            and
            path == DEFAULT_ACTIVE_ROTATION_FILE
            and
            DEFAULT_FINAL_ROTATION_FILE.exists()
        ):
            return DEFAULT_FINAL_ROTATION_FILE

        raise FileNotFoundError(
            f"Preset rotation calibration "
            f"not found: {path}"
        )


    def _stat_fingerprint(
        self,
        path,
    ):
        #
        # Include BOTH:
        # - active symlink information
        # - resolved target information
        #
        # so atomic symlink swaps are detected.
        #
        path = Path(path)

        link_stat = path.lstat()

        resolved = path.resolve(
            strict=True
        )

        target_stat = resolved.stat()

        return (
            str(resolved),
            int(link_stat.st_ino),
            int(link_stat.st_mtime_ns),
            int(target_stat.st_ino),
            int(target_stat.st_mtime_ns),
            int(target_stat.st_size),
        )


    @staticmethod
    def _validate_payload(
        payload,
        source_path,
    ):
        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                "Rotation calibration root "
                "must be a JSON object"
            )

        format_name = str(
            payload.get(
                "format",
                "",
            )
        )

        if not format_name.startswith(
            "smart-fire-preset-rotation-"
        ):
            raise RuntimeError(
                "Unsupported preset rotation "
                f"format: {format_name}"
            )

        status = str(
            payload.get(
                "status",
                "",
            )
        )

        if not status.startswith(
            "PASS_"
        ):
            raise RuntimeError(
                "Preset rotation is not "
                f"a PASS artifact: {status}"
            )

        gate = payload.get(
            "independent_holdout_gate",
            {},
        )

        if (
            not isinstance(gate, dict)
            or
            gate.get("passed")
            is not True
        ):
            raise RuntimeError(
                "Independent holdout gate "
                "is not PASS"
            )

        presets = payload.get(
            "presets"
        )

        if not isinstance(
            presets,
            dict,
        ):
            raise RuntimeError(
                "Missing presets object"
            )

        parsed = {}

        for preset in range(
            1,
            10,
        ):
            key = str(preset)

            if key not in presets:
                raise RuntimeError(
                    f"Missing preset P{preset}"
                )

            entry = presets[key]

            if not isinstance(
                entry,
                dict,
            ):
                raise RuntimeError(
                    f"P{preset}: invalid entry"
                )

            raw_matrix = entry.get(
                "camera_to_reference_rotation"
            )

            matrix = np.asarray(
                raw_matrix,
                dtype=np.float64,
            )

            if matrix.shape != (
                3,
                3,
            ):
                raise RuntimeError(
                    f"P{preset}: rotation "
                    "matrix must be 3x3"
                )

            if not np.all(
                np.isfinite(matrix)
            ):
                raise RuntimeError(
                    f"P{preset}: non-finite "
                    "rotation matrix"
                )

            orthogonality = (
                matrix.T
                @ matrix
            )

            ortho_error = float(
                np.max(
                    np.abs(
                        orthogonality
                        - np.eye(3)
                    )
                )
            )

            determinant = float(
                np.linalg.det(
                    matrix
                )
            )

            if ortho_error > 5e-3:
                raise RuntimeError(
                    f"P{preset}: rotation "
                    f"orthogonality error "
                    f"{ortho_error:.6g}"
                )

            if not (
                0.98
                <= determinant
                <= 1.02
            ):
                raise RuntimeError(
                    f"P{preset}: invalid "
                    f"rotation determinant "
                    f"{determinant:.6f}"
                )

            parsed[preset] = matrix

        #
        # Anchor requirement:
        # P1 must remain effectively identity.
        #
        p1_angle = (
            _rotation_error_deg(
                parsed[1]
            )
        )

        if p1_angle > 0.5:
            raise RuntimeError(
                "P1 reference rotation is "
                f"not anchored: {p1_angle:.3f} deg"
            )

        return parsed


    def reload(
        self,
        *,
        force=False,
    ):
        with self._lock:
            path = self._effective_path()

            fingerprint = (
                self._stat_fingerprint(
                    path
                )
            )

            if (
                not force
                and
                fingerprint
                == self._fingerprint
            ):
                return False

            resolved = (
                Path(path)
                .resolve(strict=True)
            )

            payload = json.loads(
                resolved.read_text(
                    encoding="utf-8"
                )
            )

            matrices = (
                self._validate_payload(
                    payload,
                    resolved,
                )
            )

            #
            # Only replace live data AFTER
            # complete validation succeeds.
            #
            self._matrices = matrices
            self._metadata = payload
            self._fingerprint = fingerprint
            self._resolved_path = resolved

            return True


    def reload_if_changed(self):
        return self.reload(
            force=False
        )


    def matrix(
        self,
        preset,
    ):
        preset = int(preset)

        with self._lock:
            self.reload_if_changed()

            if preset not in self._matrices:
                raise ValueError(
                    f"Unknown preset P{preset}"
                )

            #
            # Return a copy so callers cannot
            # mutate runtime calibration.
            #
            return self._matrices[
                preset
            ].copy()


    def relative_bearing_deg(
        self,
        preset,
        x_px,
        y_px,
        frame_width,
        frame_height,
    ):
        ray_camera = (
            calibrated_pixel_to_unit_ray(
                x_px,
                y_px,
                frame_width,
                frame_height,
            )
        )

        Q = self.matrix(
            preset
        )

        ray_reference = (
            Q
            @ ray_camera
        )

        norm = float(
            np.linalg.norm(
                ray_reference
            )
        )

        if (
            not math.isfinite(norm)
            or norm <= 1e-12
        ):
            raise RuntimeError(
                "Invalid reference ray"
            )

        ray_reference = (
            ray_reference
            / norm
        )

        #
        # Reference coordinates:
        # +X = right/east-like relative axis
        # +Z = forward/P1-like axis
        #
        relative = math.degrees(
            math.atan2(
                float(
                    ray_reference[0]
                ),
                float(
                    ray_reference[2]
                ),
            )
        )

        return normalize_bearing(
            relative
        )


    def bearing_deg(
        self,
        preset,
        x_px,
        y_px,
        frame_width,
        frame_height,
        *,
        north_offset_deg=0.0,
    ):
        relative = (
            self.relative_bearing_deg(
                preset,
                x_px,
                y_px,
                frame_width,
                frame_height,
            )
        )

        return normalize_bearing(
            relative
            + float(
                north_offset_deg
            )
        )


    @property
    def metadata(self):
        with self._lock:
            self.reload_if_changed()

            return dict(
                self._metadata
            )


    @property
    def resolved_path(self):
        with self._lock:
            self.reload_if_changed()

            return self._resolved_path


_RUNTIME_ROTATION = None
_RUNTIME_ROTATION_LOCK = (
    threading.Lock()
)


def get_runtime_preset_rotation():
    global _RUNTIME_ROTATION

    with _RUNTIME_ROTATION_LOCK:
        if _RUNTIME_ROTATION is None:
            _RUNTIME_ROTATION = (
                PresetRotationRuntime()
            )

        return _RUNTIME_ROTATION


def runtime_pixel_to_bearing(
    preset,
    x_px,
    y_px,
    frame_width,
    frame_height,
    *,
    north_offset_deg=0.0,
):
    """
    Production bearing entry point.

    Current bbox pixel
        -> calibrated camera ray
        -> active site Q[preset]
        -> P1/reference ray
        -> relative azimuth
        -> optional True-North offset
    """

    runtime = (
        get_runtime_preset_rotation()
    )

    return runtime.bearing_deg(
        preset,
        x_px,
        y_px,
        frame_width,
        frame_height,
        north_offset_deg=(
            north_offset_deg
        ),
    )


# ============================================================
# Legacy static center loader
# ============================================================
#
# Kept only for old calibration/debug tools.
# Production bearing MUST use PresetRotationRuntime.
# ============================================================

def normalize_deg(value):
    return float(value) % 360.0


class PresetGeometry:
    def __init__(
        self,
        path=DEFAULT_LEGACY_GEOMETRY_FILE,
    ):
        self.path = Path(path)

        if not self.path.exists():
            raise FileNotFoundError(
                f"Preset geometry not found: "
                f"{self.path}"
            )

        payload = json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )

        if (
            payload.get("format")
            != "smart-fire-preset-geometry-v1"
        ):
            raise RuntimeError(
                "Unsupported preset geometry format"
            )

        presets = payload.get(
            "presets"
        )

        if not isinstance(
            presets,
            dict,
        ):
            raise RuntimeError(
                "Invalid presets geometry"
            )

        parsed = {}

        for preset in range(
            1,
            10,
        ):
            key = str(preset)

            if key not in presets:
                raise RuntimeError(
                    f"Missing preset P{preset}"
                )

            value = presets[key]

            if isinstance(
                value,
                dict,
            ):
                value = value[
                    "center_relative_deg"
                ]

            parsed[preset] = (
                normalize_deg(
                    float(value)
                )
            )

        self.centers = parsed
        self.metadata = payload


    def center_deg(
        self,
        preset,
    ):
        preset = int(preset)

        if preset not in self.centers:
            raise ValueError(
                f"Unknown preset P{preset}"
            )

        return self.centers[
            preset
        ]


def load_preset_geometry(
    path=DEFAULT_LEGACY_GEOMETRY_FILE,
):
    return PresetGeometry(
        path
    )
