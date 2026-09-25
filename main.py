#!/usr/bin/env python3
# main.py

import json
import os
import time
from dataclasses import replace
from pathlib import Path

import cv2
import psutil

from camera import (
    LatestFrameCamera,
    wait_until_stable,
)

from config import (
    SWEEP_SEQUENCE,
    PRESET_BEARING_DEG,
    INITIAL_PRESET_WAIT_SEC,
    STABLE_DIFF_THRESHOLD,
    STABLE_REQUIRED_PAIRS,
    STABLE_TIMEOUT_SEC,
    POST_MOVE_FRESH_FRAMES,
    FRAMES_PER_SCAN,
    MIN_CONFIRM_FRAMES,
    FRAME_SAMPLE_GAP_SEC,
    STARTUP_WARMUP_RUNS,
    ALERT_COOLDOWN_SEC,
    ALERT_DEDUP_IOU_THRESHOLD,
    STATIC_DIR,
    DASHBOARD_WRITE_INTERVAL_SEC,
    SITE_CALIBRATION_FILE,
)

from detection import (
    FireDetector,
    consensus,
    bbox_iou,
)

from notify import (
    TelegramWorker,
    format_alert,
)

from overlay import (
    draw_detection,
    draw_status,
)

from ptz import PTZController
from preset_geometry import get_runtime_preset_rotation
from cross_preset_fusion import CrossPresetObjectFusion
from alert_finalizer import PendingAlertBuffer


# ============================================================
# Runtime paths
# ============================================================

LATEST_FRAME = (
    STATIC_DIR
    / "latest_frame.jpg"
)

LATEST_ALERT = (
    STATIC_DIR
    / "latest_alert.jpg"
)

STATUS_JSON = (
    STATIC_DIR
    / "status.json"
)


# ============================================================
# Valid GPS quality
# ============================================================

VALID_GPS_QUALITIES = {
    "calibrated",
    "calibrated-low",
}


# ============================================================
# Alert Event Deduplication
# ============================================================
#
# เหตุการณ์จะถือว่า "ซ้ำ" เมื่อ:
#
# - Class เดียวกัน
# - Preset เดียวกัน
# - Bounding Box IoU >= threshold
# - ยังอยู่ภายใน ALERT_COOLDOWN_SEC
#
# คนละ Preset จะถือเป็นคนละ Event
#
# ALERT_DEDUP_IOU_THRESHOLD ถูกโหลดและ Validate
# จาก config.py เพียงจุดเดียว
#
# ============================================================


# ============================================================
# Alert spool directory
# ============================================================
#
# Telegram worker เป็น asynchronous
#
# ไม่ควรส่ง latest_alert.jpg โดยตรงเข้า Queue
# เพราะ Alert ใหม่อาจ overwrite รูปเดิม
# ก่อน Telegram worker เปิดอ่านไฟล์
#
# จึงสร้างไฟล์เฉพาะ Event แยกออกมา
#
# ============================================================

ALERT_SPOOL_DIR = (
    STATIC_DIR
    / "alert_spool"
)

ALERT_SPOOL_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# Atomic output helpers
# ============================================================

def atomic_imwrite(
    path: Path,
    frame,
) -> bool:
    """
    Write image into a temporary file,
    then atomically replace the target.

    ลดโอกาสที่ Dashboard จะอ่าน JPEG
    ขณะที่ไฟล์กำลังถูกเขียน
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_name(
        path.stem
        + ".tmp"
        + path.suffix
    )

    try:

        ok = cv2.imwrite(
            str(tmp),
            frame,
        )

        if not ok:

            print(
                f"⚠️ Cannot write image: "
                f"{tmp}"
            )

            return False

        os.replace(
            tmp,
            path,
        )

        return True

    except Exception as exc:

        print(
            f"⚠️ Image write error "
            f"{path}: {exc}"
        )

        try:

            if tmp.exists():
                tmp.unlink()

        except OSError:
            pass

        return False


def write_status(
    data,
) -> bool:
    """
    Atomically write static/status.json.
    """

    STATUS_JSON.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = (
        STATUS_JSON
        .with_suffix(".tmp")
    )

    try:

        tmp.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        os.replace(
            tmp,
            STATUS_JSON,
        )

        return True

    except Exception as exc:

        print(
            "⚠️ status.json "
            f"write error: {exc}"
        )

        try:

            if tmp.exists():
                tmp.unlink()

        except OSError:
            pass

        return False


# ============================================================
# Camera helpers
# ============================================================

def wait_fresh_frames(
    camera,
    after_seq,
    count,
):
    """
    Wait for a number of frames newer than after_seq.

    Returns:
        newest FramePacket
        หรือ None เมื่อ Timeout
    """

    seq = after_seq
    packet = None

    for _ in range(
        max(
            1,
            int(count),
        )
    ):

        packet = (
            camera.wait_for_newer(
                seq,
                timeout=2.0,
            )
        )

        if packet is None:
            return None

        seq = packet.seq

    return packet


# ============================================================
# AI Startup Warm-up
# ============================================================

def warm_up_detector(
    camera,
    detector,
    runs,
):
    """
    Warm up AI backend ONCE at program startup.

    Warm-up results:
    - ไม่เข้า Consensus
    - ไม่สร้าง Alert
    - ไม่บันทึกเป็น Detection Event
    """

    if runs <= 0:

        print(
            "\nℹ️ AI startup "
            "warm-up disabled"
        )

        return []

    packet = (
        camera.latest(
            copy=True,
        )
    )

    if packet is None:

        raise RuntimeError(
            "No frame available "
            "for AI startup warm-up"
        )

    warmup_preset = (
        SWEEP_SEQUENCE[0]
    )

    timings_ms = []

    print(
        f"\n🔥 AI startup warm-up "
        f"({runs} runs)..."
    )

    for i in range(runs):

        t0 = (
            time.perf_counter()
        )

        detector.detect(
            packet.frame,
            warmup_preset,

            # Warm-up must use the same location-safety
            # contract as the production scan.
            apply_north_offset=ENABLE_TRUE_NORTH,
            allow_gps=(
                ENABLE_GPS
                and ENABLE_TRUE_NORTH
            ),
        )

        infer_ms = (
            time.perf_counter()
            - t0
        ) * 1000.0

        timings_ms.append(
            infer_ms
        )

        print(
            f"  Warm-up "
            f"{i + 1}/{runs} "
            f"| inference="
            f"{infer_ms:.1f} ms"
        )

    print(
        "✅ AI startup "
        "warm-up completed"
    )

    print(
        f"   first = "
        f"{timings_ms[0]:.1f} ms"
    )

    print(
        f"   last  = "
        f"{timings_ms[-1]:.1f} ms"
    )

    return timings_ms


# ============================================================
# Detection helpers
# ============================================================

def print_detection(
    prefix,
    detection,
):
    """
    Print Detection to console.
    """

    if (
        detection.distance_m
        is None
    ):

        distance_text = "N/A"

    else:

        distance_text = (
            f"{detection.distance_m:.2f} m"
        )

    if detection.gps is None:

        gps_text = "None"

    else:

        gps_text = (
            f"{detection.gps[0]:.8f},"
            f"{detection.gps[1]:.8f}"
        )

    print(
        f"{prefix}"
        f"{detection.canonical_class} "
        f"conf="
        f"{detection.confidence:.3f} "
        f"bearing="
        f"{detection.bearing_deg:.2f}° "
        f"distance="
        f"{distance_text} "
        f"quality="
        f"{detection.distance_quality} "
        f"gps="
        f"{gps_text}"
    )


# ============================================================
# Location safety
# ============================================================

def sanitize_detection_location(
    detection,
    *,
    site_bearing_calibrated,
):
    """
    Final production safety barrier.

    GPS จะใช้งานได้เมื่อ:

    1. Site bearing calibration มีอยู่
    2. Distance มีค่า
    3. Distance quality อยู่ใน calibrated range
    """

    location_valid = (
        site_bearing_calibrated
        and detection.distance_m
        is not None
        and detection.distance_quality
        in VALID_GPS_QUALITIES
    )

    if (
        detection.gps is not None
        and not location_valid
    ):

        print(
            "⚠️ GPS suppressed by "
            "production safety guard "
            f"| quality="
            f"{detection.distance_quality}"
        )

        return replace(
            detection,
            gps=None,
        )

    return detection


def detection_to_dict(
    detection,
    *,
    site_bearing_calibrated,
):
    """
    Convert Detection into JSON-safe object.
    """

    gps = None

    if detection.gps is not None:

        gps = [
            round(
                float(
                    detection.gps[0]
                ),
                8,
            ),
            round(
                float(
                    detection.gps[1]
                ),
                8,
            ),
        ]

    return {

        "class": (
            detection
            .canonical_class
        ),

        "model_class": (
            detection
            .model_class
        ),

        "confidence": round(
            float(
                detection.confidence
            ),
            6,
        ),

        "bbox": list(
            detection.bbox
        ),

        "bearing_deg": round(
            float(
                detection.bearing_deg
            ),
            6,
        ),

        "bearing_calibrated": (
            site_bearing_calibrated
        ),

        "distance_m": (
            None
            if detection.distance_m
            is None
            else round(
                float(
                    detection.distance_m
                ),
                6,
            )
        ),

        "distance_quality": (
            detection
            .distance_quality
        ),

        "gps": gps,
    }


# ============================================================
# Alert Event Deduplicator
# ============================================================

class AlertDeduplicator:
    """
    Event-based alert cooldown with cross-preset object identity.

    Priority:

    1. If both detections have object_id:
         same object_id
             -> same event across presets

    2. If object_id is unavailable:
         fallback to legacy
         class + same preset + bbox IoU

    This allows:

        P1 CENTER Fire1 -> OBJ-0001
        P2 EDGE   Fire1 -> OBJ-0001

    to remain one logical alert event.
    """

    def __init__(
        self,
        cooldown_sec,
        iou_threshold=0.50,
    ):

        self.cooldown_sec = max(
            0.0,
            float(
                cooldown_sec
            ),
        )

        self.iou_threshold = float(
            iou_threshold
        )

        if not (
            0.0
            <= self.iou_threshold
            <= 1.0
        ):
            raise ValueError(
                "ALERT_DEDUP_IOU_THRESHOLD "
                "must be between 0 and 1"
            )

        self.events = []


    @staticmethod
    def _object_id(
        detection,
    ):
        value = getattr(
            detection,
            "object_id",
            None,
        )

        if value is None:
            return None

        value = str(
            value
        ).strip()

        return (
            value
            if value
            else None
        )


    def _purge(
        self,
        now_mono,
    ):
        self.events = [
            event
            for event
            in self.events
            if (
                now_mono
                - event["alerted_at"]
                < self.cooldown_sec
            )
        ]


    def _duplicate_result(
        self,
        event,
        now_mono,
        reason,
    ):
        remaining = max(
            0.0,
            self.cooldown_sec
            - (
                now_mono
                - event[
                    "alerted_at"
                ]
            ),
        )

        return (
            False,
            (
                f"{reason} "
                f"remaining="
                f"{remaining:.1f}s"
            ),
        )


    def should_alert(
        self,
        detection,
        preset,
        now_mono,
    ):
        """
        Returns:

            (True, "new_event")

        or duplicate reason.
        """

        self._purge(
            now_mono
        )

        detection_object_id = (
            self._object_id(
                detection
            )
        )


        for event in self.events:

            # ---------------------------------------------
            # Class must match
            # ---------------------------------------------

            if (
                event["class"]
                != detection.canonical_class
            ):
                continue


            event_object_id = (
                event.get(
                    "object_id"
                )
            )


            # =============================================
            # Primary:
            # logical object identity across presets
            # =============================================

            if (
                detection_object_id
                is not None
                and
                event_object_id
                is not None
            ):

                if (
                    detection_object_id
                    != event_object_id
                ):
                    #
                    # Both have identity and disagree:
                    # they are different objects.
                    #
                    continue


                event["bbox"] = tuple(
                    detection.bbox
                )

                event["preset"] = int(
                    preset
                )

                event["last_seen"] = (
                    now_mono
                )

                return (
                    self._duplicate_result(
                        event,
                        now_mono,
                        (
                            "duplicate-object "
                            f"id="
                            f"{detection_object_id}"
                        ),
                    )
                )


            # =============================================
            # Legacy fallback:
            # same preset + bbox IoU
            # =============================================

            if (
                event["preset"]
                != preset
            ):
                continue


            iou = bbox_iou(
                event["bbox"],
                detection.bbox,
            )


            if (
                iou
                >= self.iou_threshold
            ):

                event["bbox"] = tuple(
                    detection.bbox
                )

                event["last_seen"] = (
                    now_mono
                )

                return (
                    self._duplicate_result(
                        event,
                        now_mono,
                        (
                            "duplicate-legacy "
                            f"IoU={iou:.3f}"
                        ),
                    )
                )


        return (
            True,
            "new_event",
        )


    def record_alert(
        self,
        detection,
        preset,
        now_mono,
    ):
        """
        Register a newly alerted logical object/event.
        """

        self.events.append(
            {
                "class": (
                    detection
                    .canonical_class
                ),

                "object_id": (
                    self._object_id(
                        detection
                    )
                ),

                "preset": int(
                    preset
                ),

                "bbox": tuple(
                    detection.bbox
                ),

                "alerted_at": (
                    now_mono
                ),

                "last_seen": (
                    now_mono
                ),
            }
        )




# ============================================================
# Telegram alert spool
# ============================================================

def create_alert_spool(
    frame,
    preset,
    detection,
):
    """
    Create unique image file for Telegram queue.

    Prevents this race condition:

        Alert A -> latest_alert.jpg
                 ↓
        Alert B overwrites file
                 ↓
        Telegram A accidentally
        sends Alert B image
    """

    timestamp = (
        time.strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    unique = (
        time.time_ns()
    )

    class_name = (
        detection
        .canonical_class
        .replace("/", "_")
        .replace("\\", "_")
    )

    path = (
        ALERT_SPOOL_DIR
        / (
            f"alert_"
            f"{timestamp}_"
            f"{unique}_"
            f"p{preset}_"
            f"{class_name}.jpg"
        )
    )

    if not atomic_imwrite(
        path,
        frame,
    ):

        return None

    return path


# ============================================================
# Preset scanning
# ============================================================

def scan_preset(
    camera,
    ptz,
    detector,
    preset,
    *,
    first_move=False,
    site_bearing_calibrated=False,
):
    """
    Production scan flow:

        PTZ
          ↓
        calculated wait
          ↓
        fresh frames
          ↓
        stable frame
          ↓
        AI frame 1
          ↓
        AI frame 2
          ↓
        AI frame 3
          ↓
        IoU consensus
          ↓
        location safety
    """

    scan_start = (
        time.perf_counter()
    )

    info = {

        "status": "starting",

        "preset": preset,

        "ptz_ok": False,

        "frames_processed": 0,

        "inference_ms": [],

        "stable_seq": None,

        "scan_ms": None,

        "geometry_valid": False,

        "geometry_method": (
            "ACTIVE_ROTATION_3D"
        ),

        "geometry_quality": "INVALID",

        "geometry_source": None,
    }


    print(
        "\n"
        + "-" * 76
    )

    print(
        f"🔄 Move -> preset "
        f"{preset} "
        f"| physical_center="
        f"{PRESET_BEARING_DEG[preset]:.1f}°"
    )


    # ========================================================
    # PTZ
    # ========================================================

    ok, wait_sec = (
        ptz.goto_preset(
            preset
        )
    )

    if not ok:

        print(
            "❌ PTZ command failed"
        )

        info["status"] = (
            "ptz_failed"
        )

        info["scan_ms"] = (
            time.perf_counter()
            - scan_start
        ) * 1000.0

        return (
            [],
            None,
            info,
        )


    info["ptz_ok"] = True


    # --------------------------------------------------------
    # First movement
    # --------------------------------------------------------

    if first_move:

        wait_sec = max(
            wait_sec,
            INITIAL_PRESET_WAIT_SEC,
        )


    print(
        f"⏱️ PTZ wait "
        f"{wait_sec:.2f}s"
    )

    time.sleep(
        wait_sec
    )


    # ========================================================
    # Fresh frames
    # ========================================================

    arrival_seq = (
        camera.sequence
    )

    fresh = wait_fresh_frames(
        camera,
        arrival_seq,
        POST_MOVE_FRESH_FRAMES,
    )

    if fresh is None:

        print(
            "⚠️ No fresh "
            "post-move frame"
        )

        info["status"] = (
            "fresh_frame_timeout"
        )

        info["scan_ms"] = (
            time.perf_counter()
            - scan_start
        ) * 1000.0

        return (
            [],
            None,
            info,
        )


    # ========================================================
    # Stable frame
    # ========================================================

    stable = wait_until_stable(
        camera,
        fresh.seq,
        STABLE_DIFF_THRESHOLD,
        STABLE_REQUIRED_PAIRS,
        STABLE_TIMEOUT_SEC,
    )

    if stable is None:

        print(
            "⚠️ Image not stable; "
            "skip preset"
        )

        info["status"] = (
            "stability_timeout"
        )

        info["scan_ms"] = (
            time.perf_counter()
            - scan_start
        ) * 1000.0

        return (
            [],
            None,
            info,
        )


    info["stable_seq"] = (
        stable.seq
    )

    print(
        f"✅ Stable frame "
        f"| seq={stable.seq} "
        f"| age="
        f"{time.time() - stable.timestamp:.3f}s"
    )


    # ========================================================
    # Dynamic Site Rotation Geometry
    # ========================================================
    #
    # Production geometry source:
    #
    # calibration/preset_rotation_ACTIVE.json
    #
    # The runtime automatically detects an atomic
    # ACTIVE site swap and validates the new Q matrices.
    #
    # No reference image.
    # No ORB/SIFT.
    # No scene matching.
    # ========================================================

    try:

        runtime_rotation = (
            get_runtime_preset_rotation()
        )

        runtime_rotation.reload_if_changed()

        info["geometry_valid"] = True

        info["geometry_method"] = (
            "ACTIVE_ROTATION_3D"
        )

        info["geometry_quality"] = (
            "VALIDATED"
        )

        info["geometry_source"] = str(
            runtime_rotation.resolved_path
        )

        print(
            "🧭 Dynamic geometry ready "
            f"| P{preset} "
            "| method=ACTIVE_ROTATION_3D"
        )

    except Exception as exc:

        info["geometry_valid"] = False

        info["geometry_method"] = (
            "ACTIVE_ROTATION_INVALID"
        )

        info["geometry_quality"] = (
            "INVALID"
        )

        info["geometry_source"] = None

        print(
            "❌ Dynamic geometry invalid "
            f"| P{preset} "
            f"| {type(exc).__name__}: "
            f"{exc}"
        )

        #
        # Fail closed:
        # do not continue AI/location processing
        # with an invalid site calibration.
        #
        raise RuntimeError(
            "Active preset rotation "
            "calibration is invalid"
        ) from exc


    # ========================================================
    # AI scan
    # ========================================================

    detection_sets = []

    packet = stable

    last_packet = stable


    for i in range(
        FRAMES_PER_SCAN
    ):


        # ----------------------------------------------------
        # Frame 2+
        # ----------------------------------------------------

        if i > 0:

            time.sleep(
                FRAME_SAMPLE_GAP_SEC
            )

            packet = (
                camera.wait_for_newer(
                    last_packet.seq,
                    timeout=2.0,
                )
            )

            if packet is None:

                print(
                    f"⚠️ Frame "
                    f"{i + 1}/"
                    f"{FRAMES_PER_SCAN} "
                    "timeout"
                )

                break


        last_packet = packet


        # ----------------------------------------------------
        # AI inference
        # ----------------------------------------------------

        t0 = (
            time.perf_counter()
        )

        detections = (
            detector.detect(
                packet.frame,
                preset,

                # Relative bearing from:
                # pixel -> calibrated ray -> ACTIVE Q[preset].
                #
                # Historical True-North remains locked.
                apply_north_offset=ENABLE_TRUE_NORTH,

                # True-North re-anchor is still pending.
                allow_gps=(
                ENABLE_GPS
                and ENABLE_TRUE_NORTH
            ),
            )
        )

        infer_ms = (
            time.perf_counter()
            - t0
        ) * 1000.0


        detection_sets.append(
            detections
        )

        info[
            "inference_ms"
        ].append(
            round(
                infer_ms,
                3,
            )
        )


        print(
            f"Frame "
            f"{i + 1}/"
            f"{FRAMES_PER_SCAN} "
            f"| seq={packet.seq} "
            f"| infer="
            f"{infer_ms:.1f} ms "
            f"| detections="
            f"{len(detections)}"
        )


        for detection in detections:

            print_detection(
                "  - ",
                detection,
            )


    info[
        "frames_processed"
    ] = len(
        detection_sets
    )


    # ========================================================
    # Consensus
    # ========================================================

    if (
        len(detection_sets)
        < MIN_CONFIRM_FRAMES
    ):

        confirmed = []

        print(
            "⚠️ Not enough frames "
            "for consensus "
            f"({len(detection_sets)}/"
            f"{MIN_CONFIRM_FRAMES})"
        )

    else:

        confirmed = consensus(
            detection_sets,
            MIN_CONFIRM_FRAMES,
        )


    # ========================================================
    # Geometry safety
    # ========================================================

    if not info[
        "geometry_valid"
    ]:

        if confirmed:

            print(
                "⚠️ AI confirmed "
                f"{len(confirmed)} detection(s), "
                "but event output is suppressed "
                "because geometry is invalid"
            )

        info[
            "ai_confirmed_suppressed"
        ] = len(
            confirmed
        )

        confirmed = []


    # ========================================================
    # GPS safety
    # ========================================================

    confirmed = [

        sanitize_detection_location(
            detection,
            site_bearing_calibrated=(
                site_bearing_calibrated
            ),
        )

        for detection
        in confirmed
    ]


    # ========================================================
    # Console result
    # ========================================================

    if confirmed:

        print(
            f"🔥 CONFIRMED: "
            f"{len(confirmed)} "
            "detection(s)"
        )

        for detection in confirmed:

            print_detection(
                "  * ",
                detection,
            )

    else:

        print(
            "✅ No confirmed "
            "Fire/Smoke"
        )


    # ========================================================
    # Scan status
    # ========================================================

    if not info[
        "geometry_valid"
    ]:

        info["status"] = (
            "geometry_invalid"
        )

    elif (
        len(detection_sets)
        == FRAMES_PER_SCAN
    ):

        info["status"] = "ok"

    else:

        info["status"] = (
            "partial_frames"
        )


    info["scan_ms"] = (
        time.perf_counter()
        - scan_start
    ) * 1000.0


    return (
        confirmed,
        last_packet,
        info,
    )


# ============================================================
# Status helpers
# ============================================================

def build_status(
    *,
    timestamp,
    cycle,
    step,
    preset,
    confirmed,
    scan_info,
    site_bearing_calibrated,
):
    """
    Build Dashboard status.json.
    """

    return {

        "timestamp": (
            timestamp
        ),

        "runtime_status": (
            scan_info[
                "status"
            ]
        ),

        "cycle": (
            cycle
        ),

        "step": (
            step
        ),

        "preset": (
            preset
        ),

        "center_bearing_deg": (
            PRESET_BEARING_DEG[
                preset
            ]
        ),

        "site_bearing_calibrated": (
            site_bearing_calibrated
        ),

        "frames_processed": (
            scan_info[
                "frames_processed"
            ]
        ),

        "inference_ms": (
            scan_info[
                "inference_ms"
            ]
        ),

        "scan_ms": (
            None
            if scan_info[
                "scan_ms"
            ]
            is None
            else round(
                scan_info[
                    "scan_ms"
                ],
                3,
            )
        ),

        "detections": len(
            confirmed
        ),

        "confirmed": [

            detection_to_dict(
                detection,
                site_bearing_calibrated=(
                    site_bearing_calibrated
                ),
            )

            for detection
            in confirmed
        ],

        "cpu_percent": (
            psutil.cpu_percent(
                interval=None
            )
        ),

        "ram_percent": (
            psutil
            .virtual_memory()
            .percent
        ),
    }



# ============================================================
# Site Location Feature Flags
# ============================================================
#
# LAB default:
#
#   ENABLE_TRUE_NORTH=0
#   ENABLE_GPS=0
#
# Real-site commissioning:
#
#   validate True North
#   validate Distance
#       ↓
#   ENABLE_TRUE_NORTH=1
#   ENABLE_GPS=1
#
# No source-code change is required when moving sites.
# ============================================================

def _env_flag(name, default=False):
    value = os.getenv(
        name,
        "1" if default else "0",
    ).strip().lower()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


ENABLE_TRUE_NORTH = _env_flag(
    "ENABLE_TRUE_NORTH",
    False,
)

ENABLE_GPS = _env_flag(
    "ENABLE_GPS",
    False,
)


# ============================================================
# Main
# ============================================================


# === RUNTIME_LOCATION_FEATURE_FLAGS_V1 ===
#
# LAB:
#   ENABLE_TRUE_NORTH=0
#   ENABLE_GPS=0
#
# REAL SITE after commissioning:
#   ENABLE_TRUE_NORTH=1
#   ENABLE_GPS=1
#
# GPS is never allowed unless True North
# is enabled as well.
#






def main():

    # ========================================================
    # Header
    # ========================================================

    print(
        "=" * 76
    )

    print(
        "🔥 Smart Fire Detection v2 "
        "- Production Runtime"
    )

    print(
        f"Sweep sequence : "
        f"{SWEEP_SEQUENCE}"
    )

    print(
        f"Frames/scan    : "
        f"{FRAMES_PER_SCAN}"
    )

    print(
        f"Confirm        : "
        f"{MIN_CONFIRM_FRAMES}/"
        f"{FRAMES_PER_SCAN}"
    )

    print(
        f"Startup warm-up: "
        f"{STARTUP_WARMUP_RUNS}"
    )

    print(
        f"Alert cooldown : "
        f"{ALERT_COOLDOWN_SEC:.1f}s"
    )

    print(
        f"Alert dedup IoU: "
        f"{ALERT_DEDUP_IOU_THRESHOLD:.2f}"
    )

    print(
        "=" * 76
    )


    # ========================================================
    # Calibration state
    # ========================================================

    historical_site_calibration_exists = (
        SITE_CALIBRATION_FILE
        .exists()
    )

    # Safety lock:
    # Frozen P1 has not yet been re-anchored
    # to Absolute True North.
    site_bearing_calibrated = False

    if site_bearing_calibrated:

        print(
            "✅ Site bearing "
            "calibration found"
        )

    else:

        print(
            "⚠️ Site bearing "
            "calibration not found"
        )

        print(
            "   Bearing ยังเป็น "
            "software-calculated bearing"
        )

        print(
            "   Production GPS output "
            "will be suppressed"
        )


    # ========================================================
    # Camera
    # ========================================================

    print(
        "\n📡 กำลังเปิด RTSP..."
    )

    camera = (
        LatestFrameCamera()
        .start()
    )


    try:

        deadline = (
            time.monotonic()
            + 10.0
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
                    "เปิด RTSP "
                    "ไม่สำเร็จภายใน "
                    "10 วินาที"
                )

            time.sleep(
                0.1
            )


        print(
            "✅ RTSP พร้อม"
        )


        # ====================================================
        # AI
        # ====================================================

        print(
            "\n🧠 กำลังโหลด AI..."
        )

        detector = (
            FireDetector()
        )

        print(
            "✅ AI พร้อม"
        )


        # ====================================================
        # Dynamic Site Rotation Geometry
        # ====================================================

        print(
            "\n🧭 กำลังโหลด "
            "Dynamic Site Rotation..."
        )

        runtime_rotation = (
            get_runtime_preset_rotation()
        )

        runtime_rotation.reload(
            force=True
        )

        print(
            "✅ Dynamic Site Rotation พร้อม"
        )

        print(
            "   ACTIVE : "
            f"{runtime_rotation.resolved_path}"
        )

        print(
            "   Model  : "
            f"{runtime_rotation.metadata.get('model')}"
        )

        print(
            "   Status : "
            f"{runtime_rotation.metadata.get('status')}"
        )

        print(
            "   Holdout: "
            f"{runtime_rotation.metadata.get(
                'independent_holdout_gate',
                {},
            ).get('passed')}"
        )


        # ====================================================
        # Startup warm-up
        # ====================================================

        warm_up_detector(
            camera,
            detector,
            STARTUP_WARMUP_RUNS,
        )


        # ====================================================
        # PTZ
        # ====================================================

        ptz = (
            PTZController()
        )


        # ====================================================
        # Telegram
        # ====================================================

        notifier = (
            TelegramWorker()
        )


        # ====================================================
        # Alert Event Deduplicator
        # ====================================================

        alert_dedup = (
            AlertDeduplicator(
                cooldown_sec=(
                    ALERT_COOLDOWN_SEC
                ),
                iou_threshold=(
                    ALERT_DEDUP_IOU_THRESHOLD
                ),
            )
        )

        # ====================================================
        # Cross-Preset Object Fusion
        # ====================================================

        cross_preset_fusion = (
            CrossPresetObjectFusion()
        )

        pending_alerts = (
            PendingAlertBuffer()
        )

        print(
            "   Pending alert finalization: "
            "PRESET_AWARE"
        )

        print(
            "   Pending safety timeout: "
            f"{pending_alerts.timeout_sec:.1f}s"
        )

        print(
            "\n🧭 Cross-Preset Fusion ready"
        )

        print(
            "   CENTER > TRANSITION > EDGE"
        )

        print(
            "   Same object can reuse trusted "
            "CENTER bearing/distance"
        )


        print(
            "\n🔔 Alert system ready"
        )

        print(
            "   Cooldown    : "
            f"{ALERT_COOLDOWN_SEC:.1f}s"
        )

        print(
            "   Dedup IoU   : "
            f"{ALERT_DEDUP_IOU_THRESHOLD:.2f}"
        )

        print(
            "   Dedup scope : "
            "class + preset + bbox"
        )


        # ====================================================
        # Dashboard timer
        # ====================================================

        last_dashboard_mono = (
            -float("inf")
        )


        # ====================================================
        # Runtime sweep
        # ====================================================

        cycle = 0

        first_move = True


        while True:

            cycle += 1


            print(
                "\n"
                + "#" * 76
            )

            print(
                f"CYCLE {cycle}"
            )

            print(
                "#" * 76
            )


            # ------------------------------------------------
            # Sweep sequence
            #
            # Cycle 1:
            #   P1 → ... → P1
            #
            # Cycle 2+:
            #   เริ่ม P2 เพราะรอบก่อนเพิ่งจบ P1
            # ------------------------------------------------

            if cycle == 1:

                sequence = (
                    SWEEP_SEQUENCE
                )

                step_offset = 0

            else:

                sequence = (
                    SWEEP_SEQUENCE[1:]
                )

                step_offset = 1


            # =================================================
            # Preset loop
            # =================================================

            for (
                local_index,
                preset,
            ) in enumerate(
                sequence,
                start=1,
            ):


                logical_step = (
                    local_index
                    + step_offset
                )


                # =============================================
                # Scan preset
                # =============================================

                try:

                    (
                        confirmed,
                        packet,
                        scan_info,
                    ) = scan_preset(
                        camera,
                        ptz,
                        detector,
                        preset,
                        first_move=(
                            first_move
                        ),
                        site_bearing_calibrated=(
                            site_bearing_calibrated
                        ),
                    )


                except Exception as exc:

                    print(
                        "❌ Preset scan "
                        "exception "
                        f"| preset="
                        f"{preset} "
                        f"| "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

                    now = (
                        time.time()
                    )

                    write_status(
                        {

                            "timestamp": (
                                now
                            ),

                            "runtime_status": (
                                "scan_exception"
                            ),

                            "cycle": (
                                cycle
                            ),

                            "step": (
                                logical_step
                            ),

                            "preset": (
                                preset
                            ),

                            "error": (
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),

                            "cpu_percent": (
                                psutil
                                .cpu_percent(
                                    interval=None
                                )
                            ),

                            "ram_percent": (
                                psutil
                                .virtual_memory()
                                .percent
                            ),
                        }
                    )

                    continue


                # =============================================
                # First movement complete
                # =============================================

                if (
                    first_move
                    and scan_info[
                        "ptz_ok"
                    ]
                ):

                    first_move = False


                now_wall = (
                    time.time()
                )

                now_mono = (
                    time.monotonic()
                )


                # =============================================
                # No usable packet
                # =============================================

                if packet is None:

                    status = (
                        build_status(
                            timestamp=(
                                now_wall
                            ),
                            cycle=(
                                cycle
                            ),
                            step=(
                                logical_step
                            ),
                            preset=(
                                preset
                            ),
                            confirmed=[],
                            scan_info=(
                                scan_info
                            ),
                            site_bearing_calibrated=(
                                site_bearing_calibrated
                            ),
                        )
                    )

                    write_status(
                        status
                    )

                    print(
                        f"⚠️ Skip output "
                        f"| preset="
                        f"{preset} "
                        f"| status="
                        f"{scan_info['status']}"
                    )

                    continue


                # =============================================
                # Cross-Preset Object Fusion
                # =============================================

                if confirmed:

                    confirmed = (
                        cross_preset_fusion
                        .fuse_batch(
                            confirmed,
                            preset,
                            now_mono,
                        )
                    )

                    for detection in confirmed:

                        print(
                            "🧩 Object fusion "
                            f"| id="
                            f"{getattr(detection, 'object_id', None)} "
                            f"| zone="
                            f"{getattr(detection, 'bearing_zone', None)} "
                            f"| fused="
                            f"{getattr(detection, 'measurement_fused', False)} "
                            f"| source=P"
                            f"{getattr(detection, 'measurement_source_preset', preset)} "
                            f"| bearing="
                            f"{detection.bearing_deg:.3f}° "
                            f"| distance="
                            f"{detection.distance_m} "
                            f"| anchor_age="
                            f"{getattr(detection, 'fusion_anchor_age_sec', None)} "
                            f"| anchor_fresh="
                            f"{getattr(detection, 'fusion_anchor_fresh', None)} "
                            f"| anchor_stale="
                            f"{getattr(detection, 'fusion_anchor_stale', False)}"
                        )


                # =============================================
                # Draw frame
                # =============================================

                frame = (
                    packet
                    .frame
                    .copy()
                )


                for detection in confirmed:

                    draw_detection(
                        frame,
                        detection,
                    )


                draw_status(
                    frame,
                    preset,
                    PRESET_BEARING_DEG[
                        preset
                    ],
                    (
                        f"SCAN | "
                        f"det="
                        f"{len(confirmed)}"
                    ),
                )


                # =============================================
                # Dashboard latest frame
                # =============================================

                if (
                    now_mono
                    - last_dashboard_mono
                    >=
                    DASHBOARD_WRITE_INTERVAL_SEC
                ):

                    if atomic_imwrite(
                        LATEST_FRAME,
                        frame,
                    ):

                        last_dashboard_mono = (
                            now_mono
                        )


                # =============================================
                # status.json
                # =============================================

                status = (
                    build_status(
                        timestamp=(
                            now_wall
                        ),
                        cycle=(
                            cycle
                        ),
                        step=(
                            logical_step
                        ),
                        preset=(
                            preset
                        ),
                        confirmed=(
                            confirmed
                        ),
                        scan_info=(
                            scan_info
                        ),
                        site_bearing_calibrated=(
                            site_bearing_calibrated
                        ),
                    )
                )

                write_status(
                    status
                )


                # =============================================
                # EVENT-BASED ALERTING + DEFERRED FINALIZATION
                # =============================================
                #
                # CENTER:
                #   alert immediately.
                #
                # EDGE / TRANSITION without fusion:
                #   hold briefly for a trusted CENTER observation.
                #
                # If no trusted observation arrives:
                #   timeout fallback uses the stored observation.
                #

                alert_candidates = []


                # =============================================
                # Current confirmed detections
                # =============================================

                if confirmed:

                    for detection in confirmed:

                        zone = str(
                            getattr(
                                detection,
                                "bearing_zone",
                                "EDGE",
                            )
                        ).upper()


                        fused = bool(
                            getattr(
                                detection,
                                "measurement_fused",
                                False,
                            )
                        )


                        object_id = getattr(
                            detection,
                            "object_id",
                            None,
                        )


                        # -------------------------------------
                        # Trusted measurement available now
                        # -------------------------------------
                        #
                        # CENTER itself is trusted.
                        #
                        # A fused EDGE/TRANSITION already carries
                        # the trusted anchor measurement.
                        #

                        if (
                            zone == "CENTER"
                            or fused
                        ):

                            cancelled = (
                                pending_alerts
                                .cancel(
                                    detection,
                                    preset,
                                )
                            )


                            if (
                                cancelled
                                is not None
                            ):

                                print(
                                    "✅ Pending alert finalized "
                                    f"| id={object_id} "
                                    f"| zone={zone} "
                                    f"| source=P"
                                    f"{getattr(detection, 'measurement_source_preset', preset)}"
                                )


                            alert_candidates.append(
                                (
                                    detection,
                                    preset,
                                    frame,
                                    "trusted-measurement",
                                )
                            )


                        # -------------------------------------
                        # EDGE / TRANSITION has no trusted
                        # CENTER anchor yet.
                        # -------------------------------------

                        else:

                            verification_preset = (
                                pending_alerts
                                .verification_target(
                                    detection,
                                    preset,
                                )
                            )


                            if (
                                verification_preset
                                is None
                            ):

                                from alert_finalizer import (
                                    choose_verification_preset,
                                )

                                verification_preset = (
                                    choose_verification_preset(
                                        detection,
                                        preset,
                                    )
                                )


                            forced = (
                                pending_alerts
                                .defer(
                                    detection,
                                    preset,
                                    frame,
                                    now_mono,
                                    verification_preset=(
                                        verification_preset
                                    ),
                                )
                            )


                            verification_preset = (
                                pending_alerts
                                .verification_target(
                                    detection,
                                    preset,
                                )
                            )


                            print(
                                "⏳ Alert deferred "
                                f"| id={object_id} "
                                f"| preset={preset} "
                                f"| zone={zone} "
                                f"| verify=P"
                                f"{verification_preset} "
                                f"| pending="
                                f"{pending_alerts.pending_count} "
                                f"| safety<="
                                f"{pending_alerts.timeout_sec:.1f}s"
                            )


                            # Bounded-buffer safety fallback.
                            # Never silently drop an alert.
                            for item in forced:

                                alert_candidates.append(
                                    (
                                        item.detection,
                                        item.preset,
                                        item.frame,
                                        "buffer-pressure-fallback",
                                    )
                                )


                # =============================================
                # Preset-aware passive verification
                # =============================================
                #
                # Trusted detections above get the FIRST chance
                # to cancel pending objects.
                #
                # Only after processing current detections do we
                # mark this usable preset as scanned.
                #
                # If this preset was the verification target and
                # no trusted matching observation cancelled the
                # pending object, fallback now.
                # =============================================

                for item in (
                    pending_alerts
                    .mark_preset_scanned(
                        preset,
                        now_mono,
                    )
                ):

                    print(
                        "🔎 Pending verification complete "
                        f"| id="
                        f"{getattr(item.detection, 'object_id', None)} "
                        f"| source=P"
                        f"{item.preset} "
                        f"| verify=P"
                        f"{item.verification_preset} "
                        f"| result=no-trusted-match"
                    )


                    alert_candidates.append(
                        (
                            item.detection,
                            item.preset,
                            item.frame,
                            "verification-fallback",
                        )
                    )


                # =============================================
                # Pending timeout fallback
                # =============================================
                #
                # Run AFTER current detections.
                #
                # This is important:
                # if CENTER arrives exactly at timeout,
                # CENTER gets a chance to cancel EDGE first.
                #

                for item in (
                    pending_alerts
                    .pop_expired(
                        now_mono
                    )
                ):

                    print(
                        "⌛ Pending safety timeout "
                        f"| id="
                        f"{getattr(item.detection, 'object_id', None)} "
                        f"| preset="
                        f"{item.preset}"
                    )


                    alert_candidates.append(
                        (
                            item.detection,
                            item.preset,
                            item.frame,
                            "timeout-fallback",
                        )
                    )


                # =============================================
                # Finalized alerts only
                # =============================================

                if alert_candidates:

                    ordered_alerts = sorted(
                        alert_candidates,

                        key=lambda item: (
                            item[0].confidence
                        ),

                        reverse=True,
                    )


                    for (
                        detection,
                        alert_preset,
                        alert_frame,
                        finalization_reason,
                    ) in ordered_alerts:


                        # =====================================
                        # Event cooldown / deduplication
                        # =====================================

                        (
                            should_alert,
                            reason,
                        ) = (
                            alert_dedup
                            .should_alert(
                                detection,
                                alert_preset,
                                now_mono,
                            )
                        )


                        if not should_alert:

                            print(
                                "🔕 Alert suppressed "
                                f"| preset="
                                f"{alert_preset} "
                                f"| class="
                                f"{detection.canonical_class} "
                                f"| finalize="
                                f"{finalization_reason} "
                                f"| {reason}"
                            )

                            continue


                        # =====================================
                        # NEW FINALIZED EVENT
                        # =====================================

                        print(
                            "🆕 New alert event "
                            f"| preset="
                            f"{alert_preset} "
                            f"| class="
                            f"{detection.canonical_class} "
                            f"| finalize="
                            f"{finalization_reason}"
                        )


                        # -------------------------------------
                        # Dashboard latest alert
                        # -------------------------------------

                        atomic_imwrite(
                            LATEST_ALERT,
                            alert_frame,
                        )


                        # -------------------------------------
                        # Build message from FINAL measurement
                        # -------------------------------------

                        message = (
                            format_alert(
                                detection,

                                bearing_calibrated=(
                                    site_bearing_calibrated
                                ),
                            )
                        )


                        alert_accepted = True


                        # =====================================
                        # Telegram enabled
                        # =====================================

                        if notifier.enabled:

                            spool_path = (
                                create_alert_spool(
                                    alert_frame,
                                    alert_preset,
                                    detection,
                                )
                            )


                            if spool_path is None:

                                print(
                                    "⚠️ Alert spool "
                                    "could not be "
                                    "created"
                                )

                                alert_accepted = (
                                    False
                                )


                            else:

                                alert_accepted = (
                                    notifier.submit(
                                        message,

                                        str(
                                            spool_path
                                        ),

                                        delete_after_send=True,
                                    )
                                )


                                if alert_accepted:

                                    print(
                                        "📨 Telegram "
                                        "alert queued"
                                    )

                                else:

                                    print(
                                        "⚠️ Telegram "
                                        "queue rejected "
                                        "alert"
                                    )


                        # =====================================
                        # Telegram disabled
                        # =====================================

                        else:

                            print(
                                "ℹ️ Telegram "
                                "not configured; "
                                "local alert only"
                            )


                        # =====================================
                        # Record cooldown only after accepted
                        # =====================================

                        if alert_accepted:

                            alert_dedup.record_alert(
                                detection,
                                alert_preset,
                                now_mono,
                            )


                        # =====================================
                        # Console Alert
                        # =====================================

                        print(
                            "\n"
                            + "=" * 76
                        )

                        print(
                            "🔔 ALERT"
                        )

                        print(
                            f"Preset: "
                            f"{alert_preset}"
                        )

                        print(
                            f"Event: "
                            f"{reason}"
                        )

                        print(
                            f"Finalization: "
                            f"{finalization_reason}"
                        )

                        print(
                            message
                        )

                        print(
                            "=" * 76
                        )


    # ========================================================
    # Stop
    # ========================================================

    except KeyboardInterrupt:

        print(
            "\n🛑 Stop requested"
        )


    finally:

        print(
            "📡 Stopping camera..."
        )

        camera.stop()

        print(
            "✅ Smart Fire Detection "
            "stopped"
        )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()