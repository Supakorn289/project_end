from __future__ import annotations

import json
import socket


SOCKET_PATH = (
    "/run/"
    "smart-fire-calibration-worker/"
    "control.sock"
)


def _call(
    payload,
):

    try:

        sock = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )

        sock.settimeout(
            40
        )


        with sock:

            sock.connect(
                SOCKET_PATH
            )

            sock.sendall(
                (
                    json.dumps(
                        payload
                    )
                    + "\n"
                ).encode(
                    "utf-8"
                )
            )

            raw = b""

            while (
                b"\n" not in raw
                and
                len(raw) < 131072
            ):

                part = sock.recv(
                    4096
                )

                if not part:
                    break

                raw += part


        if not raw:

            return {
                "ok": False,
                "error":
                    "calibration_worker_empty_response",
            }


        return json.loads(
            raw.decode(
                "utf-8"
            )
        )


    except Exception as exc:

        return {
            "ok": False,
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def worker_health():

    return _call({
        "action":
            "health",
    })


def capture_preset(
    site_id,
    preset,
    capture_set="main",
):

    return _call({
        "action":
            "capture_preset",

        "site_id":
            site_id,

        "preset":
            int(
                preset
            ),

        "capture_set":
            capture_set,
    })
