from __future__ import annotations

import json
import platform
import socket
import subprocess

from manager.config import (
    DASHBOARD_SERVICE,
    DETECTION_SERVICE,
)


def _run(args: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = proc.stdout.strip() or proc.stderr.strip()
        return proc.returncode, output
    except Exception as exc:
        return 255, str(exc)


def _service_state(unit: str) -> dict:
    _, active = _run(["systemctl", "is-active", unit])
    _, enabled = _run(["systemctl", "is-enabled", unit])

    return {
        "unit": unit,
        "active": active or "unknown",
        "enabled": enabled or "unknown",
    }


def _network_interfaces() -> list[dict]:
    rc, output = _run(["ip", "-j", "-4", "address", "show"])

    if rc != 0:
        return []

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []

    result = []

    for interface in payload:
        name = interface.get("ifname")

        if name == "lo":
            continue

        addresses = []

        for info in interface.get("addr_info", []):
            if info.get("family") != "inet":
                continue

            local = info.get("local")
            prefix = info.get("prefixlen")

            if local:
                addresses.append({
                    "address": local,
                    "prefix": prefix,
                })

        if addresses:
            result.append({
                "interface": name,
                "state": interface.get("operstate"),
                "addresses": addresses,
            })

    return result


def get_system_info() -> dict:
    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),

        "network": _network_interfaces(),

        "services": {
            "detection": _service_state(DETECTION_SERVICE),
            "dashboard": _service_state(DASHBOARD_SERVICE),
        },
    }
