#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import pwd
import re
import socket
import struct
import subprocess
import time

from pathlib import Path

import cv2

from camera import (
    LatestFrameCamera,
    wait_until_stable,
)

from config import (
    INITIAL_PRESET_WAIT_SEC,
    POST_MOVE_FRESH_FRAMES,
    STABLE_DIFF_THRESHOLD,
    STABLE_REQUIRED_PAIRS,
    STABLE_TIMEOUT_SEC,
)

from ptz import PTZController


from manager.services.hardware_lock import (
    hardware_lock,
)

from calibrate_intrinsics import (
    PATTERN_SIZE,
    calculate_board_coverage,
    calculate_sharpness,
    checkerboard_center,
    find_corners,
)


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

CAPTURE_ROOT = (
    PROJECT_ROOT
    / "calibration"
    / ".manager"
    / "candidates"
)


INTRINSICS_CANDIDATE_ROOT = (
    PROJECT_ROOT
    / "calibration"
    / ".manager"
    / "candidates"
)

SOCKET_PATH = Path(
    "/run/"
    "smart-fire-calibration-worker/"
    "control.sock"
)

DETECTION_SERVICE = (
    "smart-fire-detection.service"
)


SITE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)


def authorize_peer(
    client,
):

    if not hasattr(
        socket,
        "SO_PEERCRED",
    ):

        raise RuntimeError(
            "SO_PEERCRED unavailable"
        )


    size = struct.calcsize(
        "3i"
    )


    raw = client.getsockopt(
        socket.SOL_SOCKET,
        socket.SO_PEERCRED,
        size,
    )


    pid, uid, gid = (
        struct.unpack(
            "3i",
            raw,
        )
    )


    fire = pwd.getpwnam(
        "fire"
    )


    allowed = bool(
        uid == 0
        or
        (
            uid == fire.pw_uid
            and
            gid == fire.pw_gid
        )
    )


    if not allowed:

        raise PermissionError(
            "unauthorized unix peer"
        )


    return {
        "pid":
            int(
                pid
            ),

        "uid":
            int(
                uid
            ),

        "gid":
            int(
                gid
            ),
    }


def result(
    ok,
    **kwargs,
):

    data = {
        "ok": bool(ok),
    }

    data.update(
        kwargs
    )

    return data


def detection_active():

    process = subprocess.run(
        [
            "/usr/bin/systemctl",
            "is-active",
            "--quiet",
            DETECTION_SERVICE,
        ],
        check=False,
        timeout=10,
    )

    return (
        process.returncode
        == 0
    )


def safe_site(
    site_id,
):

    site_id = str(
        site_id
    ).strip()

    if not SITE_PATTERN.fullmatch(
        site_id
    ):
        raise ValueError(
            "invalid site_id"
        )

    return site_id


def wait_first_frame(
    camera,
):

    deadline = (
        time.monotonic()
        + 12.0
    )

    while True:

        packet = camera.latest(
            copy=False
        )

        if packet is not None:
            return packet

        if (
            time.monotonic()
            >= deadline
        ):
            raise RuntimeError(
                "RTSP first-frame timeout"
            )

        time.sleep(
            0.1
        )


def capture_preset(
    site_id,
    preset,
    capture_set="main",
):

    if detection_active():

        raise RuntimeError(
            "Detection is active. "
            "Enter Calibration Mode first."
        )


    site_id = safe_site(
        site_id
    )

    preset = int(
        preset
    )

    if not (
        1 <= preset <= 9
    ):
        raise ValueError(
            "preset must be 1..9"
        )


    capture_set = str(
        capture_set
    )

    if capture_set not in {
        "main",
        "holdout",
    }:
        raise ValueError(
            "capture_set must be "
            "main or holdout"
        )


    target_dir = (
        CAPTURE_ROOT
        / site_id
        / "ptz_captures"
        / capture_set
    )

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    camera = (
        LatestFrameCamera()
        .start()
    )


    try:

        first = wait_first_frame(
            camera
        )


        ptz = PTZController()

        seq_before = int(
            camera.sequence
        )


        ok, wait_sec = (
            ptz.goto_preset(
                preset
            )
        )

        if not ok:
            raise RuntimeError(
                f"PTZ P{preset} failed"
            )


        wait_sec = max(
            float(wait_sec),
            float(
                INITIAL_PRESET_WAIT_SEC
            ),
        )

        time.sleep(
            wait_sec
        )


        boundary = max(
            seq_before,
            int(
                camera.sequence
            ),
        )


        fresh = None
        seq = boundary

        for _ in range(
            int(
                POST_MOVE_FRESH_FRAMES
            )
        ):

            fresh = (
                camera.wait_for_newer(
                    seq,
                    timeout=3.0,
                )
            )

            if fresh is None:
                raise RuntimeError(
                    "No fresh post-move frame"
                )

            seq = fresh.seq


        stable = wait_until_stable(
            camera,
            fresh.seq,
            STABLE_DIFF_THRESHOLD,
            STABLE_REQUIRED_PAIRS,
            STABLE_TIMEOUT_SEC,
        )


        if stable is None:
            raise RuntimeError(
                "Image did not become stable"
            )


        filename = (
            f"preset_{preset}.jpg"
        )

        path = (
            target_dir
            / filename
        )

        temp = (
            target_dir
            / (
                "."
                + filename
                + ".tmp.jpg"
            )
        )


        if not cv2.imwrite(
            str(temp),
            stable.frame,
        ):
            raise RuntimeError(
                "cv2.imwrite failed"
            )


        os.replace(
            temp,
            path,
        )


        return result(
            True,
            preset=preset,
            capture_set=capture_set,
            seq=int(
                stable.seq
            ),
            age_sec=round(
                time.time()
                - stable.timestamp,
                4,
            ),
            width=int(
                stable.frame.shape[1]
            ),
            height=int(
                stable.frame.shape[0]
            ),
            relative_url=(
                "/api/wizard/"
                f"{site_id}/"
                "capture-image/"
                f"{capture_set}/"
                f"{filename}"
            ),
        )


    finally:

        camera.stop()



def _safe_camera_source(
    source,
):

    source = str(
        source
        or ""
    ).strip()


    if (
        not source.startswith(
            "rtsp://"
        )
        or
        "\n" in source
        or
        "\r" in source
        or
        len(source) > 2048
    ):

        raise ValueError(
            "invalid camera source"
        )


    return source


def _intrinsics_capture_dir(
    site_id,
):

    site_id = safe_site(
        site_id
    )


    path = (
        INTRINSICS_CANDIDATE_ROOT
        / site_id
        / "intrinsics_workspace"
        / "captures"
    )


    path.mkdir(
        parents=True,
        exist_ok=True,
    )


    return path


def _write_jpg_atomic(
    path,
    frame,
):

    path = Path(
        path
    )


    temp = (
        path.parent
        /
        (
            "."
            + path.name
            + ".tmp.jpg"
        )
    )


    if not cv2.imwrite(
        str(temp),
        frame,
    ):

        raise RuntimeError(
            "cv2.imwrite failed"
        )


    os.replace(
        temp,
        path,
    )


def _next_intrinsics_index(
    capture_dir,
):

    numbers = []


    for path in capture_dir.glob(
        "calib_*.jpg"
    ):

        try:

            numbers.append(
                int(
                    path.stem.split(
                        "_"
                    )[-1]
                )
            )

        except ValueError:
            continue


    return (
        max(
            numbers,
            default=0,
        )
        + 1
    )


def capture_intrinsics_frame(
    site_id,
    camera_source,
    *,
    save=False,
    min_sharpness=0.0,
):

    if detection_active():

        raise RuntimeError(
            "Detection is active. "
            "กดเริ่ม Calibration Mode ก่อน"
        )


    site_id = safe_site(
        site_id
    )


    camera_source = (
        _safe_camera_source(
            camera_source
        )
    )


    min_sharpness = float(
        min_sharpness
        or 0.0
    )


    if min_sharpness < 0:

        raise ValueError(
            "min_sharpness must be >= 0"
        )


    target_dir = (
        _intrinsics_capture_dir(
            site_id
        )
    )


    camera = (
        LatestFrameCamera(
            source=camera_source
        )
        .start()
    )


    try:

        first = wait_first_frame(
            camera
        )


        packet = camera.wait_for_newer(
            int(
                first.seq
            ),
            timeout=3.0,
        )


        if packet is None:

            packet = camera.latest(
                copy=True
            )


        if packet is None:

            raise RuntimeError(
                "No fresh RTSP frame"
            )


        frame = (
            packet.frame.copy()
        )


        height, width = (
            frame.shape[:2]
        )


        corners = find_corners(
            frame
        )


        found = (
            corners is not None
        )


        sharpness = (
            calculate_sharpness(
                frame
            )
        )


        coverage = (
            calculate_board_coverage(
                corners,
                width,
                height,
            )
        )


        center = (
            checkerboard_center(
                corners
            )
        )


        rejection_reason = None


        if not found:

            rejection_reason = (
                "pattern_not_found"
            )


        elif (
            min_sharpness > 0
            and
            sharpness
            < min_sharpness
        ):

            rejection_reason = (
                "image_too_blurry"
            )


        elif coverage < 0.02:

            rejection_reason = (
                "checkerboard_too_small"
            )


        accepted = (
            rejection_reason
            is None
        )


        # -----------------------------------------------
        # Private annotated preview
        # -----------------------------------------------

        preview = (
            frame.copy()
        )


        if found:

            cv2.drawChessboardCorners(
                preview,
                PATTERN_SIZE,
                corners,
                True,
            )


        state_text = (
            "PATTERN FOUND"
            if found
            else
            "PATTERN NOT FOUND"
        )


        cv2.putText(
            preview,
            state_text,
            (
                20,
                32,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.70,
            (
                0,
                255,
                0,
            )
            if accepted
            else
            (
                0,
                0,
                255,
            ),
            2,
            cv2.LINE_AA,
        )


        cv2.putText(
            preview,
            (
                f"sharpness="
                f"{sharpness:.1f} "
                f"| coverage="
                f"{coverage * 100.0:.1f}%"
            ),
            (
                20,
                62,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (
                0,
                255,
                255,
            ),
            2,
            cv2.LINE_AA,
        )


        preview_path = (
            target_dir
            / "preview_latest.jpg"
        )


        _write_jpg_atomic(
            preview_path,
            preview,
        )


        saved = False
        filename = None


        if save and accepted:

            index = (
                _next_intrinsics_index(
                    target_dir
                )
            )


            filename = (
                f"calib_"
                f"{index:03d}.jpg"
            )


            output = (
                target_dir
                / filename
            )


            _write_jpg_atomic(
                output,
                frame,
            )


            saved = True


        saved_total = len(
            list(
                target_dir.glob(
                    "calib_*.jpg"
                )
            )
        )


        return result(
            True,

            pattern_found=
                found,

            accepted=
                accepted,

            saved=
                saved,

            filename=
                filename,

            saved_total=
                saved_total,

            sharpness=
                round(
                    sharpness,
                    3,
                ),

            coverage_fraction=
                round(
                    coverage,
                    6,
                ),

            coverage_percent=
                round(
                    coverage
                    * 100.0,
                    2,
                ),

            center=(
                None
                if center is None
                else [
                    round(
                        float(
                            center[0]
                        ),
                        2,
                    ),

                    round(
                        float(
                            center[1]
                        ),
                        2,
                    ),
                ]
            ),

            width=
                int(
                    width
                ),

            height=
                int(
                    height
                ),

            rejection_reason=
                rejection_reason,

            preview_filename=
                "preview_latest.jpg",
        )


    finally:

        camera.stop()



def handle(
    request,
):

    action = request.get(
        "action"
    )

    if action == "health":

        return result(
            True,
            detection_active=(
                detection_active()
            ),
        )


    if action == "intrinsics_probe":

        with hardware_lock(
            "worker:intrinsics_probe",
            timeout=1.0,
        ):

            return capture_intrinsics_frame(
                request.get(
                    "site_id"
                ),

                request.get(
                    "camera_source"
                ),

                save=False,

                min_sharpness=request.get(
                    "min_sharpness",
                    0.0,
                ),
            )


    if action == "intrinsics_capture":

        with hardware_lock(
            "worker:intrinsics_capture",
            timeout=1.0,
        ):

            return capture_intrinsics_frame(
                request.get(
                    "site_id"
                ),

                request.get(
                    "camera_source"
                ),

                save=True,

                min_sharpness=request.get(
                    "min_sharpness",
                    0.0,
                ),
            )


    if action == "capture_preset":

        with hardware_lock(
            "worker:capture_preset",
            timeout=1.0,
        ):

            return capture_preset(
                request.get(
                    "site_id"
                ),
                request.get(
                    "preset"
                ),
                request.get(
                    "capture_set",
                    "main",
                ),
            )


    return result(
        False,
        error="operation_not_allowed",
    )


def serve():

    SOCKET_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    CAPTURE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    try:
        SOCKET_PATH.unlink()

    except FileNotFoundError:
        pass


    server = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    server.bind(
        str(
            SOCKET_PATH
        )
    )

    os.chmod(
        SOCKET_PATH,
        0o660,
    )

    server.listen(
        4
    )


    while True:

        client, _ = (
            server.accept()
        )

        with client:

            try:

                authorize_peer(
                    client
                )


                raw = b""

                while (
                    b"\n" not in raw
                    and
                    len(raw) < 65536
                ):

                    part = client.recv(
                        4096
                    )

                    if not part:
                        break

                    raw += part


                request = json.loads(
                    raw.decode(
                        "utf-8"
                    )
                )


                output = handle(
                    request
                )


            except Exception as exc:

                output = result(
                    False,
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


            client.sendall(
                (
                    json.dumps(
                        output,
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode(
                    "utf-8"
                )
            )


if __name__ == "__main__":
    serve()
