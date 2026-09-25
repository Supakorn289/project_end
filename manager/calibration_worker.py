#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import socket
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


PROJECT_ROOT = Path(
    "/opt/smart-fire-detection-v2"
)

CAPTURE_ROOT = (
    PROJECT_ROOT
    / "manager"
    / "static"
    / "calibration_sessions"
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
                "/static/"
                "calibration_sessions/"
                f"{site_id}/"
                f"{capture_set}/"
                f"{filename}"
            ),
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


    if action == "capture_preset":

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
