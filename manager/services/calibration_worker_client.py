from __future__ import annotations

import json
import socket
import subprocess



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


def ensure_hardware_site_safe(site_id):
    """Reject a different site's hardware operation while detection runs.

    Never rely on an HTTP/UI flag or trust a missing/unknown systemd state.
    If detection is explicitly inactive, commissioning can proceed under its
    existing authorization and lease checks. This function makes no writes.
    """
    from manager.services.site_store import get_active_site
    active = (get_active_site() or {}).get('site_id')
    if active and str(site_id) == str(active):
        return
    try:
        process = subprocess.run(
            ['/usr/bin/systemctl', 'is-active', 'smart-fire-detection.service'],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PermissionError('other_site_hardware_state_unknown_stop') from exc
    # Only explicit inactive is accepted. active/activating/reloading/failed/
    # unknown fail closed to avoid taking over a potentially running camera.
    if process.stdout.strip() != 'inactive':
        raise PermissionError('other_site_hardware_requires_maintenance_stop')


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

    ensure_hardware_site_safe(site_id)

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


def intrinsics_probe(
    site_id,
    camera_source,
    min_sharpness=0.0,
):

    ensure_hardware_site_safe(site_id)

    return _call({
        "action":
            "intrinsics_probe",

        "site_id":
            site_id,

        "camera_source":
            camera_source,

        "min_sharpness":
            float(
                min_sharpness
            ),
    })


def intrinsics_capture(
    site_id,
    camera_source,
    min_sharpness=0.0,
):

    ensure_hardware_site_safe(site_id)

    return _call({
        "action":
            "intrinsics_capture",

        "site_id":
            site_id,

        "camera_source":
            camera_source,

        "min_sharpness":
            float(
                min_sharpness
            ),
    })
