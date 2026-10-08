#!/usr/bin/env bash
set -euo pipefail

cd /opt/smart-fire-detection-v2

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="calibration/.manager/patch-backups/control-center-operational-v1.3-${STAMP}"
mkdir -p "$BACKUP"

for f in \
  manager/templates/index.html \
  manager/static/manager.js \
  manager/static/manager.css
do
  cp -a "$f" "$BACKUP/$(basename "$f")"
done

if [ -f manager/static/control_center_operational.js ]; then
  cp -a \
    manager/static/control_center_operational.js \
    "$BACKUP/control_center_operational.js"
fi

echo "Backup: $BACKUP"

echo
echo "=== PRECHECK ==="

for marker in \
  'id="runtime-test-grid"' \
  'id="system-services"' \
  'id="system-summary-grid"' \
  'id="overview-runtime-warning"' \
  'id="calibration-runtime-note"'
do
  if grep -q "$marker" manager/templates/index.html; then
    echo "OK: $marker"
  else
    echo "ERROR: missing HTML marker: $marker"
    exit 1
  fi
done

if grep -q 'data-page="events"' manager/templates/index.html; then
  echo "ERROR: Events nav still exists"
  exit 1
fi

echo "Events nav: REMOVED"

python3 - <<'PY'
from pathlib import Path

p = Path("manager/templates/index.html")
text = p.read_text(encoding="utf-8")

if 'id="system-json"' not in text:
    pos = text.find('id="system-network"')
    if pos < 0:
        raise SystemExit("system-network marker not found")

    section_end = text.find("</section>", pos)
    if section_end < 0:
        raise SystemExit("system section end not found")

    compatibility = """
                <pre
                    id="system-json"
                    class="hidden"
                    aria-hidden="true"
                ></pre>

"""

    text = (
        text[:section_end]
        + compatibility
        + text[section_end:]
    )

if '/static/control_center_operational.js' not in text:
    marker = "</body>"
    if marker not in text:
        raise SystemExit("body end marker not found")

    tag = """
<script
    src="/static/control_center_operational.js"
></script>

"""

    text = text.replace(
        marker,
        tag + marker,
        1,
    )

p.write_text(text, encoding="utf-8")
print("CONTROL_CENTER_HTML_COMPAT=PATCHED")
PY

cat > manager/static/control_center_operational.js <<'JS'
(() => {
    "use strict";

    let csrf = null;

    const TEST_IDS = [
        "camera.test",
        "ptz.test",
        "ptz.frame_sync",
        "model.inspect",
        "full_sweep",
        "preflight.offline",
        "telegram.test",
    ];

    const $ = id =>
        document.getElementById(id);

    const esc = value =>
        String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");

    async function requestJSON(
        url,
        options = {},
    ) {
        const config = {
            cache: "no-store",
            ...options,
        };

        config.headers = {
            ...(config.headers || {}),
            "Content-Type":
                "application/json",
        };

        const method =
            String(
                config.method
                || "GET"
            ).toUpperCase();

        if (
            csrf
            &&
            ![
                "GET",
                "HEAD",
                "OPTIONS",
            ].includes(method)
        ) {
            config.headers[
                "X-CSRF-Token"
            ] = csrf;
        }

        const response =
            await fetch(
                url,
                config,
            );

        const data =
            await response.json();

        if (!response.ok) {
            throw new Error(
                data.error
                ||
                JSON.stringify(data)
            );
        }

        return data;
    }

    function statusClass(
        value
    ) {
        const text =
            String(
                value
                || ""
            ).toUpperCase();

        if (
            text.includes("FAIL")
            ||
            text.includes("ERROR")
            ||
            text.includes("INACTIVE")
        ) {
            return "bad";
        }

        if (
            text.includes("WARN")
            ||
            text.includes("UNVERIFIED")
            ||
            text.includes("DISABLED")
            ||
            text.includes("FORCED")
            ||
            text.includes("UNKNOWN")
        ) {
            return "warn";
        }

        if (
            text.includes("ACTIVE")
            ||
            text.includes("READY")
            ||
            text.includes("ENABLED")
            ||
            text === "UP"
            ||
            text === "PASS"
        ) {
            return "good";
        }

        return "info";
    }

    function statusItem(
        title,
        value,
        className = "info",
    ) {
        return `
            <div class="status-item">
                <div class="status-title">
                    ${esc(title)}
                </div>
                <div class="status-value ${className}">
                    ${esc(value ?? "—")}
                </div>
            </div>
        `;
    }

    function formatBytes(
        value
    ) {
        let number =
            Number(value);

        if (
            !Number.isFinite(number)
            ||
            number < 0
        ) {
            return "—";
        }

        const units = [
            "B",
            "KB",
            "MB",
            "GB",
            "TB",
        ];

        let index = 0;

        while (
            number >= 1024
            &&
            index < units.length - 1
        ) {
            number /= 1024;
            index += 1;
        }

        return (
            `${number.toFixed(
                index === 0
                ? 0
                : 1
            )} ${units[index]}`
        );
    }

    function formatUptime(
        seconds
    ) {
        const value =
            Number(seconds);

        if (
            !Number.isFinite(value)
            ||
            value < 0
        ) {
            return "—";
        }

        const total =
            Math.floor(value);

        const days =
            Math.floor(
                total / 86400
            );

        const hours =
            Math.floor(
                (total % 86400)
                / 3600
            );

        const minutes =
            Math.floor(
                (total % 3600)
                / 60
            );

        if (days > 0) {
            return `${days}d ${hours}h`;
        }

        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        }

        return `${minutes}m`;
    }

    async function refreshSession() {
        const data =
            await requestJSON(
                "/api/auth/session"
            );

        csrf =
            data.authenticated
            ? data.csrf
            : null;

        const state =
            $("test-auth-state");

        const box =
            $("test-auth-box");

        if (state) {
            state.textContent =
                data.authenticated
                ? "UNLOCKED"
                : "LOCKED";

            state.className =
                (
                    "badge "
                    +
                    (
                        data.authenticated
                        ? "good"
                        : "warn"
                    )
                );
        }

        if (box) {
            box.classList.toggle(
                "hidden",
                data.authenticated,
            );
        }

        return data;
    }

    async function unlockManager() {
        const input =
            $("test-manager-token");

        const output =
            $("runtime-test-output");

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
            const data =
                await requestJSON(
                    "/api/auth/login",
                    {
                        method: "POST",
                        body:
                            JSON.stringify({
                                token,
                            }),
                    },
                );

            csrf =
                data.csrf;

            input.value = "";

            await refreshSession();

            if (output) {
                output.textContent =
                    "Manager unlocked";
            }

        } catch (error) {
            if (output) {
                output.textContent =
                    `Unlock failed: ${String(error)}`;
            }
        }
    }

    function toolCard(
        toolId,
        tool,
    ) {
        const flags = [];

        if (
            tool.requires_detection_stopped
        ) {
            flags.push(
                "Stops Detection"
            );
        }

        if (
            tool.hardware_motion
        ) {
            flags.push(
                "Moves PTZ"
            );
        }

        if (
            tool.heavy
        ) {
            flags.push(
                "Heavy"
            );
        }

        return `
            <div class="test operational-test">
                <div class="test-title">
                    ${esc(tool.label || toolId)}
                </div>

                <div class="test-description">
                    ${esc(tool.description || toolId)}
                </div>

                <div class="test-flags">
                    ${
                        (
                            flags.length
                            ? flags
                            : ["Safe inspection"]
                        )
                        .map(
                            flag =>
                                (
                                    '<span class="mini-badge">'
                                    +
                                    esc(flag)
                                    +
                                    '</span>'
                                )
                        )
                        .join("")
                    }
                </div>

                <div class="test-actions">
                    <button
                        type="button"
                        class="secondary-btn"
                        data-cc-detail="${esc(toolId)}"
                    >
                        Details
                    </button>

                    <button
                        type="button"
                        class="action-btn"
                        data-cc-run="${esc(toolId)}"
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

    async function loadTests() {
        const target =
            $("runtime-test-grid");

        if (!target) {
            return;
        }

        const catalog =
            await requestJSON(
                "/api/commissioning/catalog"
            );

        const tools =
            catalog.tools
            || {};

        const available =
            TEST_IDS.filter(
                id =>
                    tools[id]
            );

        target.innerHTML =
            available.length
            ? available
                .map(
                    id =>
                        toolCard(
                            id,
                            tools[id],
                        )
                )
                .join("")
            : `
                <div class="empty">
                    ไม่พบ Runtime Test ที่ register ไว้
                </div>
            `;

        target
            .querySelectorAll(
                "[data-cc-detail]"
            )
            .forEach(
                button => {
                    button.addEventListener(
                        "click",
                        () =>
                            previewTest(
                                button.dataset.ccDetail
                            ),
                    );
                }
            );

        target
            .querySelectorAll(
                "[data-cc-run]"
            )
            .forEach(
                button => {
                    button.addEventListener(
                        "click",
                        () =>
                            runTest(
                                button.dataset.ccRun
                            ),
                    );
                }
            );
    }

    async function previewTest(
        toolId
    ) {
        const output =
            $("runtime-test-output");

        try {
            const plan =
                await requestJSON(
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
                `Details failed: ${String(error)}`;
        }
    }

    async function runTest(
        toolId
    ) {
        const output =
            $("runtime-test-output");

        const session =
            await refreshSession();

        if (
            !session.authenticated
        ) {
            output.textContent =
                "Manager ยัง LOCKED — Unlock ก่อนรัน Test";

            return;
        }

        try {
            const plan =
                await requestJSON(
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
                `Run ${plan.label || toolId}?`;

            if (
                Array.isArray(
                    plan.warnings
                )
                &&
                plan.warnings.length
            ) {
                message +=
                    "\n\n"
                    +
                    plan.warnings.join(
                        "\n"
                    );
            }

            if (
                !window.confirm(
                    message
                )
            ) {
                return;
            }

            output.textContent =
                (
                    `Running ${plan.label || toolId}...`
                    +
                    "\n\nPlease wait."
                );

            const result =
                await requestJSON(
                    `/api/commissioning/tool/${encodeURIComponent(toolId)}/run`,
                    {
                        method: "POST",
                        body:
                            JSON.stringify({
                                confirm: true,
                            }),
                    },
                );

            output.textContent =
                JSON.stringify(
                    result,
                    null,
                    2,
                );

        } catch (error) {
            output.textContent =
                `Test failed: ${String(error)}`;
        }
    }

    function renderSystem(
        system
    ) {
        const summary =
            $("system-summary-grid");

        const services =
            $("system-services");

        const network =
            $("system-network");

        if (
            !summary
            ||
            !services
            ||
            !network
        ) {
            return;
        }

        const disk =
            system.disk
            || {};

        const load =
            system.load_average
            || {};

        summary.innerHTML =
            statusItem(
                "Hostname",
                system.hostname
                || "—"
            )
            +
            statusItem(
                "OS",
                system.os
                || "—"
            )
            +
            statusItem(
                "Python",
                system.python
                || "—"
            )
            +
            statusItem(
                "Architecture",
                system.architecture
                || "—"
            )
            +
            statusItem(
                "Uptime",
                formatUptime(
                    system.uptime_sec
                ),
                "good"
            )
            +
            statusItem(
                "Load average",
                (
                    load["1m"] != null
                    ? (
                        `${load["1m"]} / `
                        +
                        `${load["5m"] ?? "—"} / `
                        +
                        `${load["15m"] ?? "—"}`
                    )
                    : "—"
                )
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
                    Number(
                        disk.used_percent
                    ) >= 90
                    ? "bad"
                    : (
                        Number(
                            disk.used_percent
                        ) >= 80
                        ? "warn"
                        : "good"
                    )
                )
            )
            +
            statusItem(
                "Disk free",
                formatBytes(
                    disk.free_bytes
                )
            );

        const serviceItems =
            system.services
            || {};

        services.innerHTML =
            Object.entries(
                serviceItems
            )
            .map(
                ([name, item]) =>
                    `
                        <div class="service-row">
                            <div>
                                <strong>
                                    ${esc(name)}
                                </strong>
                                <div class="service-unit">
                                    ${esc(item.unit || "")}
                                </div>
                            </div>

                            <div class="service-states">
                                <span class="${statusClass(item.active)}">
                                    ${esc(item.active || "unknown")}
                                </span>

                                <span class="muted-text">
                                    ${esc(item.enabled || "unknown")}
                                </span>
                            </div>
                        </div>
                    `
            )
            .join("");

        const networkItems =
            Array.isArray(
                system.network
            )
            ? system.network
            : [];

        network.innerHTML =
            networkItems.length
            ? networkItems
                .map(
                    item => {
                        const addresses =
                            (
                                item.addresses
                                || []
                            )
                            .map(
                                address =>
                                    (
                                        `${esc(address.address)}`
                                        +
                                        `/${esc(address.prefix)}`
                                    )
                            )
                            .join(", ");

                        return `
                            <div class="network-row">
                                <div>
                                    <strong>
                                        ${esc(item.interface)}
                                    </strong>

                                    <div class="service-unit">
                                        ${addresses || "No IPv4"}
                                    </div>
                                </div>

                                <span class="${statusClass(item.state)}">
                                    ${esc(item.state || "UNKNOWN")}
                                </span>
                            </div>
                        `;
                    }
                )
                .join("")
            : `
                <div class="empty">
                    ไม่พบ IPv4 interface
                </div>
            `;
    }

    async function refreshSystem() {
        try {
            const system =
                await requestJSON(
                    "/api/system"
                );

            renderSystem(
                system
            );

        } catch (error) {
            const target =
                $("system-summary-grid");

            if (target) {
                target.innerHTML =
                    statusItem(
                        "System API",
                        String(error),
                        "bad",
                    );
            }
        }
    }

    function renderWarning(
        calibration
    ) {
        const overview =
            $("overview-runtime-warning");

        const calibrationNote =
            $("calibration-runtime-note");

        if (
            !overview
            ||
            !calibrationNote
        ) {
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
            overview.classList.add(
                "hidden"
            );

            calibrationNote
                .classList
                .add(
                    "hidden"
                );

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

        const html = `
            <strong>
                ⚠ Geometry: FORCED ACTIVE
            </strong>

            <span>
                Independent Holdout = FAILED
                ${
                    failedPairs.length
                    ? (
                        " | Failed pairs: "
                        +
                        esc(
                            failedPairs.join(
                                ", "
                            )
                        )
                    )
                    : ""
                }
            </span>
        `;

        overview.innerHTML =
            html;

        calibrationNote.innerHTML =
            html;

        overview.classList.remove(
            "hidden"
        );

        calibrationNote
            .classList
            .remove(
                "hidden"
            );

        const grid =
            $("calibration-grid");

        if (grid) {
            const items =
                grid.querySelectorAll(
                    ".status-item"
                );

            for (
                const item
                of items
            ) {
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
                    value.classList.remove(
                        "good"
                    );

                    value.classList.add(
                        "warn"
                    );
                }
            }
        }
    }

    async function refreshWarning() {
        try {
            const data =
                await requestJSON(
                    "/api/overview"
                );

            renderWarning(
                data.discovery?.calibration
                || {}
            );

        } catch (error) {
            console.warn(
                "Runtime warning refresh failed",
                error,
            );
        }
    }

    async function init() {
        const unlock =
            $("test-unlock-btn");

        if (unlock) {
            unlock.addEventListener(
                "click",
                unlockManager,
            );
        }

        await Promise.allSettled([
            refreshSession(),
            loadTests(),
            refreshSystem(),
            refreshWarning(),
        ]);

        window.setInterval(
            refreshSystem,
            10000,
        );

        window.setInterval(
            refreshWarning,
            5000,
        );
    }

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            init,
            {
                once: true,
            },
        );
    } else {
        init();
    }
})();
JS

if ! grep -q \
  'CONTROL_CENTER_OPERATIONAL_V1' \
  manager/static/manager.css
then

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

fi

echo
echo "=== VALIDATION ==="

git diff --check -- \
  manager/templates/index.html \
  manager/static/manager.css \
  manager/static/control_center_operational.js

if command -v node >/dev/null 2>&1; then
  node --check \
    manager/static/manager.js

  node --check \
    manager/static/control_center_operational.js
fi

grep -q \
  '/static/control_center_operational.js' \
  manager/templates/index.html \
  && echo "Standalone operational JS: LINKED"

grep -q \
  'id="system-json"' \
  manager/templates/index.html \
  && echo "Legacy system target: COMPATIBLE"

grep -q \
  'id="runtime-test-grid"' \
  manager/templates/index.html \
  && echo "Runtime Test Center: INSTALLED"

sudo systemctl restart \
  smart-fire-manager.service

READY=0

for attempt in $(seq 1 30)
do
  if curl -fsS \
    http://127.0.0.1:5050/api/health \
    >/dev/null 2>&1
  then
    READY=1
    break
  fi

  sleep 0.5
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Manager did not become ready"

  sudo systemctl status \
    smart-fire-manager.service \
    --no-pager \
    -l \
    || true

  exit 1
fi

echo
echo "=== SERVICES ==="

systemctl is-active \
  smart-fire-manager.service \
  smart-fire-detection.service \
  smart-fire-dashboard.service \
  smart-fire-manager-agent.service

echo
echo "=== HEALTH ==="

curl -fsS \
  http://127.0.0.1:5050/api/health \
  | ./venv/bin/python -m json.tool

echo
echo "=== SYSTEM API ==="

curl -fsS \
  http://127.0.0.1:5050/api/system \
  | ./venv/bin/python -c '
import json
import sys

d = json.load(sys.stdin)

print("hostname =", d.get("hostname"))
print("uptime_sec =", d.get("uptime_sec"))
print("disk =", d.get("disk"))

print("services:")
for key, item in d.get("services", {}).items():
    print(
        f"  {key:22s} "
        f"{item.get(chr(97)+chr(99)+chr(116)+chr(105)+chr(118)+chr(101))} / "
        f"{item.get(chr(101)+chr(110)+chr(97)+chr(98)+chr(108)+chr(101)+chr(100))}"
    )
'

echo
echo "=== TEST CATALOG ==="

curl -fsS \
  http://127.0.0.1:5050/api/commissioning/catalog \
  | ./venv/bin/python -c '
import json
import sys

data = json.load(sys.stdin)
tools = data.get("tools", {})

wanted = [
    "camera.test",
    "ptz.test",
    "ptz.frame_sync",
    "model.inspect",
    "full_sweep",
    "preflight.offline",
    "telegram.test",
]

for tool_id in wanted:
    item = tools.get(tool_id)

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
echo "CONTROL_CENTER_OPERATIONAL_V1_3=COMPLETE"
echo "Backup: $BACKUP"
