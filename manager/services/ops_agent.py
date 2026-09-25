from __future__ import annotations

import json
import socket


SOCKET_PATH = (
    "/run/"
    "smart-fire-manager-agent/"
    "control.sock"
)


def agent_request(
    request,
    timeout=360,
):

    try:

        sock = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )

        sock.settimeout(
            timeout
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
                and
                len(raw)
                < 131072
            ):

                part = sock.recv(
                    8192
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


def run_existing_tool(
    tool_id,
):

    return agent_request(
        {
            "action":
                "run_existing_tool",

            "tool_id":
                tool_id,
        },
        timeout=360,
    )
