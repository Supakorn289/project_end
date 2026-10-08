from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess

from manager.config import (
    DASHBOARD_SERVICE,
    DETECTION_SERVICE,
    PROJECT_ROOT,
)

SERVICES = {
    "detection": DETECTION_SERVICE,
    "dashboard": DASHBOARD_SERVICE,
    "manager": "smart-fire-manager.service",
    "manager_agent": "smart-fire-manager-agent.service",
    "calibration_worker": "smart-fire-calibration-worker.service",
    "calibration_watchdog": "smart-fire-calibration-watchdog.service",
}


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
    rc, output = _run([
        "ip",
        "-j",
        "-4",
        "address",
        "show",
    ])

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


def _uptime_seconds() -> float | None:
    try:
        with open(
            "/proc/uptime",
            "r",
            encoding="utf-8",
        ) as handle:
            return float(
                handle.read().split()[0]
            )
    except Exception:
        return None


def _disk_usage() -> dict:
    usage = shutil.disk_usage(PROJECT_ROOT)

    return {
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
        "used_percent": round(
            (usage.used / usage.total * 100.0)
            if usage.total
            else 0.0,
            1,
        ),
    }


def get_system_info() -> dict:
    try:
        load1, load5, load15 = os.getloadavg()
        load_average = {
            "1m": round(load1, 2),
            "5m": round(load5, 2),
            "15m": round(load15, 2),
        }
    except OSError:
        load_average = {}

    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "uptime_sec": _uptime_seconds(),
        "load_average": load_average,
        "disk": _disk_usage(),
        "network": _network_interfaces(),
        "services": {
            name: _service_state(unit)
            for name, unit in SERVICES.items()
        },
    }
