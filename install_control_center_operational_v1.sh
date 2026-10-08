#!/usr/bin/env bash
set -euo pipefail

cd /opt/smart-fire-detection-v2

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="calibration/.manager/patch-backups/control-center-cleanup-${STAMP}"
mkdir -p "$BACKUP"

for f in \
  manager/templates/index.html \
  manager/static/manager.js \
  manager/static/manager.css \
  manager/services/system_info.py
do
  cp -a "$f" "$BACKUP/"
done

echo "Backup: $BACKUP"

cat > manager/services/system_info.py <<'PY'
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


def _uptime_seconds() -> float | None:
    try:
        value = (
            open(
                "/proc/uptime",
                "r",
                encoding="utf-8",
            )
            .read()
            .split()[0]
        )
        return float(value)
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
        load = {
            "1m": round(load1, 2),
            "5m": round(load5, 2),
            "15m": round(load15, 2),
        }
    except OSError:
        load = {}

    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "uptime_sec": _uptime_seconds(),
        "load_average": load,
        "disk": _disk_usage(),
        "network": _network_interfaces(),
        "services": {
            name: _service_state(unit)
            for name, unit in SERVICES.items()
        },
    }
PY

python3 - <<'PY'
from pathlib import Path
import re

p = Path("manager/templates/index.html")
text = p.read_text(encoding="utf-8")

text = re.sub(
    r'''\s*<button
\s+class="nav"
\s+data-page="events"
\s*>
\s*Events
\s*</button>
''',
    "\n",
    text,
    count=1,
    flags=re.VERBOSE,
)

if 'id="overview-runtime-warning"' not in text:
    anchor = '''            <div
                id="overview-cards"
                class="cards"
            ></div>
'''
    replacement = anchor + '''
            <div
                id="overview-runtime-warning"
                class="runtime-warning hidden"
            ></div>
'''
    if anchor not in text:
        raise SystemExit("overview cards anchor not found")
    text = text.replace(anchor, replacement, 1)

if 'id="calibration-runtime-note"' not in text:
    anchor = '''                <div
                    id="calibration-grid"
                    class="status-grid"
                ></div>
'''
    replacement = anchor + '''
                <div
                    id="calibration-runtime-note"
                    class="runtime-warning hidden"
                ></div>
'''
    if anchor not in text:
        raise SystemExit("calibration grid anchor not found")
    text = text.replace(anchor, replacement, 1)

tests_pattern = re.compile(
    r'''        <section
            id="page-tests"
            class="page"
        >
        .*?
        </section>''',
    re.VERBOSE | re.DOTALL,
)

tests_new = '''
        <section
            id="page-tests"
            class="page"
        >
            <div class="panel">
                <div class="panel-head">
                    <div>
                        <h2>Runtime Test Center</h2>
                        <p>
                            ใช้เครื่องมือทดสอบจริงของโปรเจกต์
                            ผ่าน Manager Agent
                        </p>
                    </div>

                    <div
                        id="test-auth-state"
                        class="badge muted"
                    >
                        Checking session...
                    </div>
                </div>

                <div
                    id="test-auth-box"
                    class="test-auth hidden"
                >
                    <div>
                        ต้อง Unlock Manager ก่อนรันคำสั่งที่มีผลกับ Runtime
                    </div>

                    <input
                        id="test-manager-token"
                        type="password"
                        autocomplete="current-password"
                        placeholder="Manager Token"
                    >

                    <button
                        id="test-unlock-btn"
                        type="button"
                        class="action-btn"
                    >
                        Unlock
                    </button>
                </div>

                <div class="test-note">
                    Tests ที่ต้องใช้กล้อง/PTZ จะหยุด Detection
                    ชั่วคราวและคืนสถานะเดิมอัตโนมัติเมื่อจบ
                </div>

                <div
                    id="runtime-test-grid"
                    class="test-grid"
                ></div>
            </div>

            <div class="panel">
                <div class="panel-head">
                    <div>
                        <h2>Test Result</h2>
                        <p>ผลล่าสุดจากเครื่องมือที่รัน</p>
                    </div>
                </div>

                <pre id="runtime-test-output">ยังไม่ได้รันการทดสอบ</pre>
            </div>
        </section>'''

text, count = tests_pattern.subn(
    tests_new,
    text,
    count=1,
)
if count != 1:
    raise SystemExit("Tests section replacement failed")

events_pattern = re.compile(
    r'''        <section
            id="page-events"
            class="page"
        >
        .*?
        </section>''',
    re.VERBOSE | re.DOTALL,
)
text = events_pattern.sub("", text, count=1)

system_pattern = re.compile(
    r'''        <section
            id="page-system"
            class="page"
        >
        .*?
        </section>''',
    re.VERBOSE | re.DOTALL,
)

system_new = '''
        <section
            id="page-system"
            class="page"
        >
            <div class="panel">
                <div class="panel-head">
                    <div>
                        <h2>System Health</h2>
                        <p>
                            เครื่อง Server, Storage และ Runtime Services
                        </p>
                    </div>
                </div>

                <div
                    id="system-summary-grid"
                    class="status-grid"
                ></div>
            </div>

            <div class="panel">
                <div class="panel-head">
                    <div>
                        <h2>Services</h2>
                        <p>
                            systemd services ที่เกี่ยวข้องกับ Smart Fire
                        </p>
                    </div>
                </div>

                <div
                    id="system-services"
                    class="service-list"
                ></div>
            </div>

            <div class="panel">
                <div class="panel-head">
                    <div>
                        <h2>Network</h2>
                        <p>IPv4 interfaces ที่ใช้งานบนเครื่อง</p>
                    </div>
                </div>

                <div
                    id="system-network"
                    class="network-list"
                ></div>
            </div>
        </section>'''

text, count = system_pattern.subn(
    system_new,
    text,
    count=1,
)
if count != 1:
    raise SystemExit("System section replacement failed")

p.write_text(text, encoding="utf-8")
print("CONTROL_CENTER_HTML=PATCHED")
PY

python3 - <<'PY'
from pathlib import Path

p = Path("manager/static/manager.js")
text = p.read_text(encoding="utf-8")

old_events = '''    events: [
        "Events",
        "Detection and alert history",
    ],

'''
text = text.replace(old_events, "", 1)

old_system = '''    document.getElementById(
        "system-json"
    ).textContent =
        JSON.stringify(
            discovery.system,
            null,
            2,
        );


'''

if old_system in text:
    text = text.replace(
        old_system,
        '''    renderSystemSnapshot(
        discovery.system
    );

    renderRuntimeWarnings(
        discovery.calibration
    );


''',
        1,
    )
elif "renderSystemSnapshot(" not in text:
    marker = '''    selectedMode =
        install.mode
        || "LAB";
'''
    if marker not in text:
        raise SystemExit("loadOverview injection anchor not found")

    text = text.replace(
        marker,
        '''    renderSystemSnapshot(
        discovery.system
    );

    renderRuntimeWarnings(
        discovery.calibration
    );


''' + marker,
        1,
    )

marker = "// CONTROL_CENTER_OPERATIONAL_V1"

if marker not in text:
    addon = r'''

// CONTROL_CENTER_OPERATIONAL_V1

let controlCenterCsrf = null;

const operationalTestIds = [
    "camera.test",
    "ptz.test",
    "ptz.frame_sync",
    "model.inspect",
    "full_sweep",
    "preflight.offline",
    "telegram.test",
];


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatBytes(value) {
    const number = Number(value);

    if (!Number.isFinite(number) || number < 0) {
        return "—";
    }

    const units = [
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ];

    let current = number;
    let index = 0;

    while (
        current >= 1024
        &&
        index < units.length - 1
    ) {
        current /= 1024;
        index += 1;
    }

    return `${current.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}


function formatUptime(seconds) {
    const value = Number(seconds);

    if (!Number.isFinite(value) || value < 0) {
        return "—";
    }

    const total = Math.floor(value);
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);

    if (days > 0) {
        return `${days}d ${hours}h`;
    }

    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    }

    return `${minutes}m`;
}


function renderSystemSnapshot(system) {
    if (!system) {
        return;
    }

    const summary =
        document.getElementById(
            "system-summary-grid"
        );

    const servicesTarget =
        document.getElementById(
            "system-services"
        );

    const networkTarget =
        document.getElementById(
            "system-network"
        );

    if (!summary || !servicesTarget || !networkTarget) {
        return;
    }

    const disk = system.disk || {};
    const load = system.load_average || {};

    summary.innerHTML =
        statusItem(
            "Hostname",
            escapeHtml(system.hostname || "—"),
            "info"
        )
        +
        statusItem(
            "Operating System",
            escapeHtml(system.os || "—"),
            "info"
        )
        +
        statusItem(
            "Python",
            escapeHtml(system.python || "—"),
            "info"
        )
        +
        statusItem(
            "Architecture",
            escapeHtml(system.architecture || "—"),
            "info"
        )
        +
        statusItem(
            "Uptime",
            formatUptime(system.uptime_sec),
            "good"
        )
        +
        statusItem(
            "Load average",
            (
                load["1m"] != null
                ? `${load["1m"]} / ${load["5m"] ?? "—"} / ${load["15m"] ?? "—"}`
                : "—"
            ),
            "info"
        )
        +
        statusItem(
            "Disk used",
            (
                disk.used_percent != null
                ? `${disk.used_percent}%`
                : "—"
            ),
            (
                Number(disk.used_percent) >= 90
                ? "bad"
                : (
                    Number(disk.used_percent) >= 80
                    ? "warn"
                    : "good"
                )
            )
        )
        +
        statusItem(
            "Disk free",
            formatBytes(disk.free_bytes),
            "info"
        );

    const services = system.services || {};

    servicesTarget.innerHTML =
        Object.entries(services)
        .map(
            ([name, item]) => {
                const active =
                    String(
                        item.active
                        || "unknown"
                    );

                const enabled =
                    String(
                        item.enabled
                        || "unknown"
                    );

                return `
                    <div class="service-row">
                        <div>
                            <strong>
                                ${escapeHtml(name)}
                            </strong>

                            <div class="service-unit">
                                ${escapeHtml(item.unit || "")}
                            </div>
                        </div>

                        <div class="service-states">
                            <span class="${clsForStatus(active)}">
                                ${escapeHtml(active)}
                            </span>

                            <span class="muted-text">
                                ${escapeHtml(enabled)}
                            </span>
                        </div>
                    </div>
                `;
            }
        )
        .join("");

    const network =
        Array.isArray(system.network)
        ? system.network
        : [];

    networkTarget.innerHTML =
        network.length
        ? network.map(
            item => {
                const addresses =
                    (item.addresses || [])
                    .map(
                        address =>
                            `${escapeHtml(address.address)}/${escapeHtml(address.prefix)}`
                    )
                    .join(", ");

                return `
                    <div class="network-row">
                        <div>
                            <strong>
                                ${escapeHtml(item.interface)}
                            </strong>

                            <div class="service-unit">
                                ${addresses || "No IPv4"}
                            </div>
                        </div>

                        <span class="${clsForStatus(item.state)}">
                            ${escapeHtml(item.state || "UNKNOWN")}
                        </span>
                    </div>
                `;
            }
        ).join("")
        : `
            <div class="empty">
                ไม่พบ IPv4 interface
            </div>
        `;
}


function renderRuntimeWarnings(calibration) {
    const overview =
        document.getElementById(
            "overview-runtime-warning"
        );

    const calibrationNote =
        document.getElementById(
            "calibration-runtime-note"
        );

    if (!overview || !calibrationNote) {
        return;
    }

    const rotation =
        calibration?.rotation
        || {};

    const forced =
        rotation.forced === true
        ||
        String(
            rotation.status
            || ""
        )
        .toUpperCase()
        .includes("FORCED");

    if (!forced) {
        overview.classList.add("hidden");
        calibrationNote.classList.add("hidden");
        return;
    }

    const failedPairs =
        Object.entries(
            rotation.holdout?.pairs
            || {}
        )
        .filter(
            ([, passed]) =>
                passed === false
        )
        .map(
            ([pair]) =>
                pair
        );

    const message = `
        <strong>
            ⚠ Geometry: FORCED ACTIVE
        </strong>

        <span>
            Independent Holdout = FAILED
            ${
                failedPairs.length
                ? ` | Failed pairs: ${escapeHtml(failedPairs.join(", "))}`
                : ""
            }
        </span>
    `;

    overview.innerHTML = message;
    calibrationNote.innerHTML = message;

    overview.classList.remove("hidden");
    calibrationNote.classList.remove("hidden");

    const grid =
        document.getElementById(
            "calibration-grid"
        );

    if (grid) {
        const items =
            grid.querySelectorAll(
                ".status-item"
            );

        for (const item of items) {
            const title =
                item.querySelector(
                    ".status-title"
                );

            const value =
                item.querySelector(
                    ".status-value"
                );

            if (
                title?.textContent?.trim()
                === "Preset Rotation"
                &&
                value
            ) {
                value.classList.remove("good");
                value.classList.add("warn");
            }
        }
    }
}


async function controlCenterSession() {
    const data =
        await getJSON(
            "/api/auth/session"
        );

    controlCenterCsrf =
        data.authenticated
        ? data.csrf
        : null;

    const state =
        document.getElementById(
            "test-auth-state"
        );

    const authBox =
        document.getElementById(
            "test-auth-box"
        );

    if (state) {
        state.textContent =
            data.authenticated
            ? "UNLOCKED"
            : "LOCKED";

        state.classList.toggle(
            "good",
            data.authenticated
        );

        state.classList.toggle(
            "warn",
            !data.authenticated
        );
    }

    if (authBox) {
        authBox.classList.toggle(
            "hidden",
            data.authenticated
        );
    }

    return data;
}


async function unlockControlCenter() {
    const input =
        document.getElementById(
            "test-manager-token"
        );

    const output =
        document.getElementById(
            "runtime-test-output"
        );

    const token =
        input?.value?.trim()
        || "";

    if (!token) {
        if (output) {
            output.textContent =
                "กรุณาใส่ Manager Token";
        }
        return;
    }

    try {
        const response =
            await fetch(
                "/api/auth/login",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body:
                        JSON.stringify({
                            token,
                        }),
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            throw new Error(
                data.error
                || "Unlock failed"
            );
        }

        controlCenterCsrf = data.csrf;

        input.value = "";

        await controlCenterSession();

        if (output) {
            output.textContent =
                "Manager unlocked";
        }

    } catch (error) {
        if (output) {
            output.textContent =
                String(error);
        }
    }
}


function testCard(toolId, tool) {
    const flags = [];

    if (tool.requires_detection_stopped) {
        flags.push("Stops Detection");
    }

    if (tool.hardware_motion) {
        flags.push("Moves PTZ");
    }

    if (tool.heavy) {
        flags.push("Heavy");
    }

    return `
        <div class="test operational-test">
            <div class="test-title">
                ${escapeHtml(tool.label || toolId)}
            </div>

            <div class="test-description">
                ${escapeHtml(tool.description || "")}
            </div>

            <div class="test-flags">
                ${
                    flags.length
                    ? flags.map(
                        flag =>
                            `<span class="mini-badge">${escapeHtml(flag)}</span>`
                    ).join("")
                    : '<span class="mini-badge">Safe inspection</span>'
                }
            </div>

            <div class="test-actions">
                <button
                    type="button"
                    class="secondary-btn"
                    onclick="previewControlTest('${escapeHtml(toolId)}')"
                >
                    Details
                </button>

                <button
                    type="button"
                    class="action-btn"
                    onclick="runControlTest('${escapeHtml(toolId)}')"
                    ${
                        tool.exists === false
                        ? "disabled"
                        : ""
                    }
                >
                    Run
                </button>
            </div>
        </div>
    `;
}


async function loadControlTests() {
    const target =
        document.getElementById(
            "runtime-test-grid"
        );

    if (!target) {
        return;
    }

    const [
        catalog,
    ] = await Promise.all([
        getJSON(
            "/api/commissioning/catalog"
        ),
        controlCenterSession(),
    ]);

    const tools =
        catalog.tools
        || {};

    target.innerHTML =
        operationalTestIds
        .filter(
            id =>
                tools[id]
        )
        .map(
            id =>
                testCard(
                    id,
                    tools[id]
                )
        )
        .join("");
}


window.previewControlTest =
async toolId => {
    const output =
        document.getElementById(
            "runtime-test-output"
        );

    try {
        const plan =
            await getJSON(
                `/api/commissioning/tool/${encodeURIComponent(toolId)}/plan`
            );

        output.textContent =
            JSON.stringify(
                plan,
                null,
                2,
            );

    } catch (error) {
        output.textContent =
            String(error);
    }
};


window.runControlTest =
async toolId => {
    const output =
        document.getElementById(
            "runtime-test-output"
        );

    const session =
        await controlCenterSession();

    if (!session.authenticated) {
        output.textContent =
            "Manager ยัง LOCKED — Unlock ก่อนรัน Test";
        return;
    }

    try {
        const plan =
            await getJSON(
                `/api/commissioning/tool/${encodeURIComponent(toolId)}/plan`
            );

        if (!plan.runnable) {
            output.textContent =
                JSON.stringify(
                    plan,
                    null,
                    2,
                );
            return;
        }

        let message =
            `Run ${plan.label}?`;

        if (
            Array.isArray(plan.warnings)
            &&
            plan.warnings.length
        ) {
            message +=
                "\n\n"
                +
                plan.warnings.join("\n");
        }

        if (!confirm(message)) {
            return;
        }

        output.textContent =
            `Running ${plan.label}...\n\nPlease wait.`;

        const response =
            await fetch(
                `/api/commissioning/tool/${encodeURIComponent(toolId)}/run`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                        "X-CSRF-Token":
                            controlCenterCsrf,
                    },
                    body:
                        JSON.stringify({
                            confirm: true,
                        }),
                }
            );

        const result =
            await response.json();

        output.textContent =
            JSON.stringify(
                result,
                null,
                2,
            );

        if (!response.ok) {
            throw new Error(
                result.error
                || "Test failed"
            );
        }

        setTimeout(
            () => {
                loadOverview().catch(
                    console.error
                );
            },
            1000,
        );

    } catch (error) {
        output.textContent +=
            `\n\nERROR: ${String(error)}`;
    }
};


const testUnlockButton =
    document.getElementById(
        "test-unlock-btn"
    );

if (testUnlockButton) {
    testUnlockButton.addEventListener(
        "click",
        unlockControlCenter
    );
}


loadControlTests().catch(
    error => {
        const output =
            document.getElementById(
                "runtime-test-output"
            );

        if (output) {
            output.textContent =
                `Test Center load failed: ${String(error)}`;
        }
    }
);
'''

    text += addon

p.write_text(text, encoding="utf-8")
print("CONTROL_CENTER_JS=PATCHED")
PY

cat >> manager/static/manager.css <<'CSS'

/* CONTROL_CENTER_OPERATIONAL_V1 */

.hidden {
    display: none !important;
}

.runtime-warning {
    margin: -4px 0 18px;
    padding: 12px 14px;
    border: 1px solid rgba(242, 184, 75, 0.55);
    border-radius: 10px;
    background: rgba(242, 184, 75, 0.08);
    color: var(--warn);
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: baseline;
}

.test-auth {
    margin-bottom: 14px;
    padding: 12px;
    border: 1px solid var(--line);
    background: var(--panel2);
    border-radius: 10px;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
}

.test-auth input {
    min-width: 220px;
    flex: 1;
    background: #0a111b;
    border: 1px solid var(--line);
    border-radius: 8px;
    color: var(--text);
    padding: 9px 11px;
}

.test-note {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 14px;
}

.operational-test {
    color: var(--text);
}

.test-title {
    font-weight: 700;
}

.test-description {
    color: var(--muted);
    font-size: 12px;
    line-height: 1.45;
    margin-top: 7px;
    min-height: 34px;
}

.test-flags,
.test-actions {
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
}

.test-flags {
    margin-top: 11px;
}

.test-actions {
    margin-top: 13px;
}

.mini-badge {
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 4px 7px;
    color: var(--muted);
    font-size: 10px;
}

.action-btn,
.secondary-btn {
    border: 0;
    border-radius: 8px;
    padding: 8px 11px;
    cursor: pointer;
    color: white;
}

.action-btn {
    background: #327fe8;
}

.secondary-btn {
    background: #29384c;
}

.action-btn:disabled,
.secondary-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}

.service-list,
.network-list {
    display: grid;
    gap: 8px;
}

.service-row,
.network-row {
    background: var(--panel2);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
}

.service-unit {
    color: var(--muted);
    font-size: 11px;
    margin-top: 4px;
    word-break: break-word;
}

.service-states {
    display: flex;
    align-items: center;
    gap: 12px;
    text-align: right;
}

.muted-text {
    color: var(--muted);
}

@media (max-width: 620px) {
    .service-row,
    .network-row {
        align-items: flex-start;
        flex-direction: column;
    }

    .service-states {
        text-align: left;
    }

    .test-auth input {
        min-width: 100%;
    }
}
CSS

./venv/bin/python -m py_compile \
    manager/services/system_info.py \
    manager/app.py \
    manager/commissioning_api.py

git diff --check -- \
    manager/templates/index.html \
    manager/static/manager.js \
    manager/static/manager.css \
    manager/services/system_info.py

if command -v node >/dev/null 2>&1; then
    node --check manager/static/manager.js
fi

echo
echo "=== UI PLACEHOLDER CHECK ==="

if grep -q 'data-page="events"' manager/templates/index.html; then
    echo "ERROR: Events nav still exists"
    exit 1
else
    echo "Events placeholder: REMOVED"
fi

grep -q 'id="runtime-test-grid"' manager/templates/index.html \
    && echo "Runtime Test Center: INSTALLED"

grep -q 'id="system-services"' manager/templates/index.html \
    && echo "System Health UI: INSTALLED"

sudo systemctl restart smart-fire-manager.service

for attempt in $(seq 1 20); do
    if curl -fsS \
        http://127.0.0.1:5050/api/health \
        >/dev/null 2>&1
    then
        break
    fi

    sleep 0.5
done

echo
echo "=== SERVICES ==="

systemctl is-active \
    smart-fire-manager.service \
    smart-fire-detection.service \
    smart-fire-dashboard.service \
    smart-fire-manager-agent.service

echo
echo "=== SYSTEM API ==="

curl -fsS \
    http://127.0.0.1:5050/api/system \
    | ./venv/bin/python -m json.tool

echo
echo "=== TEST CATALOG ==="

curl -fsS \
    http://127.0.0.1:5050/api/commissioning/catalog \
    | ./venv/bin/python -c '
import json,sys

data=json.load(sys.stdin)
tools=data.get("tools",{})

wanted=[
    "camera.test",
    "ptz.test",
    "ptz.frame_sync",
    "model.inspect",
    "full_sweep",
    "preflight.offline",
    "telegram.test",
]

for tool_id in wanted:
    item=tools.get(tool_id)
    if not item:
        print(f"{tool_id:24} MISSING")
        continue

    print(
        f"{tool_id:24} "
        f"exists={item.get(chr(101)+chr(120)+chr(105)+chr(115)+chr(116)+chr(115))} "
        f"kind={item.get(chr(107)+chr(105)+chr(110)+chr(100))}"
    )
'

echo
echo "CONTROL_CENTER_OPERATIONAL_V1=COMPLETE"
echo "Backup: $BACKUP"
