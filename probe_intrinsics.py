#!/usr/bin/env python3
"""
Smart Fire Detection v2 - Checkerboard Intrinsic Probe

Probe script to verify checkerboard visibility before capture.
1. Connects to camera RTSP stream.
2. Captures a fresh 1280x720 frame.
3. Detects 9x6 inner-corner checkerboard pattern.
4. Outputs status and saves diagnostic image to calibration/intrinsics_v1/probe_latest.jpg.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
import cv2
import numpy as np

from camera import LatestFrameCamera
from config import CALIBRATION_DIR, FRAME_WIDTH, FRAME_HEIGHT

PATTERN_SIZE = (9, 6)
OUTPUT_DIR = CALIBRATION_DIR / "intrinsics_v1"
OUTPUT_PROBE_IMAGE = OUTPUT_DIR / "probe_latest.jpg"

def calculate_sharpness(img_gray: np.ndarray) -> float:
    return float(cv2.Laplacian(img_gray, cv2.CV_64F).var())

def calculate_coverage(corners: np.ndarray, w: int, h: int) -> float:
    area = cv2.contourArea(corners)
    return float(area / max(w * h, 1))

def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" Smart Fire Detection v2 - Checkerboard Probe")
    print(f" Target Pattern: {PATTERN_SIZE[0]}x{PATTERN_SIZE[1]} inner corners (10x7 squares)")
    print(f" Target Resolution: {FRAME_WIDTH}x{FRAME_HEIGHT}")
    print("=" * 60)

    print("Connecting to camera stream...")
    cam = LatestFrameCamera().start()

    deadline = time.monotonic() + 10.0
    packet = None
    while time.monotonic() < deadline:
        packet = cam.wait_for_newer(-1, timeout=1.0)
        if packet is not None:
            break
        time.sleep(0.1)

    cam.stop()

    if packet is None or packet.frame is None:
        print("❌ ERROR: Failed to obtain frame from camera stream (timeout).")
        return 1

    frame = packet.frame
    h, w = frame.shape[:2]
    print(f"Frame received: shape={frame.shape} (resolution: {w}x{h})")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = calculate_sharpness(gray)

    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
    found, corners = cv2.findChessboardCorners(gray, PATTERN_SIZE, flags=flags)

    vis = frame.copy()

    if found and corners is not None:
        # Refine corner locations
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        refined_corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        cv2.drawChessboardCorners(vis, PATTERN_SIZE, refined_corners, found)

        coverage = calculate_coverage(refined_corners, w, h)
        corner_count = len(refined_corners)

        cv2.putText(
            vis,
            f"FOUND: {corner_count} corners | Sharp: {sharpness:.1f} | Cov: {coverage*100:.1f}%",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

        cv2.imwrite(str(OUTPUT_PROBE_IMAGE), vis)

        print("\n" + "-" * 60)
        print(" Checkerboard Status: FOUND ✅")
        print(f" Detected corners  : {corner_count} / {PATTERN_SIZE[0] * PATTERN_SIZE[1]}")
        print(f" Sharpness         : {sharpness:.1f}")
        print(f" Coverage          : {coverage * 100:.1f}%")
        print(f" Diagnostic image  : {OUTPUT_PROBE_IMAGE}")
        print("-" * 60)
        return 0
    else:
        cv2.putText(
            vis,
            f"NOT FOUND | Sharp: {sharpness:.1f}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.imwrite(str(OUTPUT_PROBE_IMAGE), vis)

        print("\n" + "-" * 60)
        print(" Checkerboard Status: NOT FOUND ❌")
        print(" Reason            : 9x6 inner corners not detected in frame.")
        print(f" Frame sharpness   : {sharpness:.1f}")
        print(f" Diagnostic image  : {OUTPUT_PROBE_IMAGE}")
        print("-" * 60)
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
