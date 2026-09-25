from __future__ import annotations

import json
import socket


SOCKET_PATH = (
    "/run/smart-fire-manager-agent/"
    "control.sock"
)


def _run(
    action: str,
    payload=None,
):

    request = {
        "action":
            action,
    }


    if payload is not None:

        request[
            "settings"
        ] = payload


    try:

        sock = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )

        sock.settimeout(
            70
        )


        with sock:

            sock.connect(
                SOCKET_PATH
            )


            sock.sendall(
                (
                    json.dumps(
                        request
                    )
                    + "\n"
                ).encode(
                    "utf-8"
                )
            )


            raw = b""

            while (
                b"\n" not in raw
                and len(raw)
                < 131072
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
                    "agent_empty_response",
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


def get_runtime_settings():

    return _run(
        "settings_read"
    )


def save_runtime_settings(
    payload: dict,
):

    return _run(
        "settings_write",
        payload,
    )


def apply_runtime_settings(
    payload: dict,
):

    return _run(
        "settings_apply",
        payload,
    )


def restart_detection():

    return _run(
        "restart_detection"
    )


def detection_status():

    return _run(
        "detection_status"
    )


def stop_detection():

    return _run(
        "stop_detection"
    )


def start_detection():

    return _run(
        "start_detection"
    )
