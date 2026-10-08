#!/usr/bin/env bash
set -euo pipefail

cd /opt/smart-fire-detection-v2

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="calibration/.manager/patch-backups/control-center-operational-v1.2-${STAMP}"
mkdir -p "$BACKUP"

for f in \
  manager/templates/index.html \
  manager/static/manager.js \
  manager/static/manager.css \
  manager/services/system_info.py
do
  cp -a "$f" "$BACKUP/$(basename "$f")"
done

echo "Backup: $BACKUP"

echo
echo "=== PRECHECK HTML ==="

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
    echo "ERROR: required HTML marker missing: $marker"
    echo "The v1.1 HTML patch was not fully applied."
    exit 1
  fi
done

if grep -q 'data-page="events"' manager/templates/index.html; then
  echo "ERROR: Events nav still exists"
  exit 1
fi

if grep -q 'id="page-events"' manager/templates/index.html; then
  echo "ERROR: Events page still exists"
  exit 1
fi

echo "Events placeholder: REMOVED"


# ============================================================
# Patch manager.js using function boundaries, not whitespace.
# ============================================================

python3 - <<'PY'
from pathlib import Path
import re

p = Path("manager/static/manager.js")
text = p.read_text(encoding="utf-8")


def function_slice(
    source: str,
    start_marker: str,
    next_marker: str,
) -> tuple[int, int, str]:

    start = source.find(start_marker)

    if start < 0:
        raise RuntimeError(
            f"start marker not found: {start_marker}"
        )

    end = source.find(
        next_marker,
        start + len(start_marker),
    )

    if end < 0:
        raise RuntimeError(
            f"next marker not found: {next_marker}"
        )

    return (
        start,
        end,
        source[start:end],
    )


# Remove stale Events title metadata if still present.
text = re.sub(
    r'''(?ms)
^[ \t]*events:[ \t]*\[
[ \t]*"Events",[ \t]*
[ \t]*"Detection and alert history",[ \t]*
[ \t]*\],[ \t]*\n
''',
    "",
    text,
    count=1,
)


# Modify only loadOverview().
start, end, block = function_slice(
    text,
    "async function loadOverview()",
    "function renderPlan(",
)

calls = '''
    renderSystemSnapshot(
        discovery.system
    );

    renderRuntimeWarnings(
        discovery.calibration
    );


'''

if (
    "renderSystemSnapshot("
    not in block
):
    system_pos = block.find(
        '"system-json"'
    )

    if system_pos >= 0:
        statement_start = block.rfind(
            "document",
            0,
            system_pos,
        )

        if statement_start < 0:
            raise RuntimeError(
                "system-json statement start not found"
            )

        candidates = [
            pos
            for pos in (
                block.find(
                    "selectedMode",
                    system_pos,
                ),
                block.find(
                    "await loadSetupPlan",
                    system_pos,
                ),
            )
            if pos >= 0
        ]

        if not candidates:
            raise RuntimeError(
                "could not locate post-system render anchor"
            )

        statement_end = min(
            candidates
        )

        block = (
            block[:statement_start]
            +
            calls
            +
            block[statement_end:]
        )

    else:
        candidates = [
            pos
            for pos in (
                block.find(
                    "selectedMode"
                ),
                block.find(
                    "await loadSetupPlan"
                ),
            )
            if pos >= 0
        ]

        if not candidates:
            raise RuntimeError(
                "loadOverview injection point not found"
            )

        inject_at = min(
            candidates
        )

        block = (
            block[:inject_at]
            +
            calls
            +
            block[inject_at:]
        )

text = (
    text[:start]
    +
    block
    +
    text[end:]
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
    return String(
        value ?? ""
    )
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatBytes(value) {
    const number = Number(
        value
    );

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

    return (
        `${current.toFixed(
            index === 0
            ? 0
            : 1
        )} ${units[index]}`
    );
}


function formatUptime(seconds) {
    const value = Number(
        seconds
    );

    if (
        !Number.isFinite(value)
        ||
        value < 0
    ) {
        return "—";
    }

    const total = Math.floor(
        value
    );

    const days = Math.floor(
        total / 86400
    );

    const hours = Math.floor(
        (
            total % 86400
        )
        / 3600
    );

    const minutes = Math.floor(
        (
            total % 3600
        )
        / 60
    );

    if (days > 0) {
        return (
            `${days}d ${hours}h`
        );
    }

    if (hours > 0) {
        return (
            `${hours}h ${minutes}m`
        );
    }

    return `${minutes}m`;
}


function renderSystemSnapshot(
    system
) {
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

    if (
        !summary
        ||
        !servicesTarget
        ||
        !networkTarget
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
            escapeHtml(
                system.hostname
                || "—"
            ),
            "info"
        )
        +
        statusItem(
            "Operating System",
            escapeHtml(
                system.os
                || "—"
            ),
            "info"
        )
        +
        statusItem(
            "Python",
            escapeHtml(
                system.python
                || "—"
            ),
            "info"
        )
        +
        statusItem(
            "Architecture",
            escapeHtml(
                system.architecture
                || "—"
            ),
            "info"
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
            ),
            "info"
        )
        +
        statusItem(
            "Disk used",
            (
                disk.used_percent
                != null
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
            ),
            "info"
        );


    const services =
        system.services
        || {};

    servicesTarget.innerHTML =
        Object.entries(
            services
        )
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
                                ${escapeHtml(
                                    item.unit
                                    || ""
                                )}
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
        Array.isArray(
            system.network
        )
        ? system.network
        : [];

    networkTarget.innerHTML =
        network.length
        ? network.map(
            item => {
                const addresses =
                    (
                        item.addresses
                        || []
                    )
                    .map(
                        address =>
                            (
                                `${escapeHtml(address.address)}`
                                +
                                `/${escapeHtml(address.prefix)}`
                            )
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
                            ${escapeHtml(
                                item.state
                                || "UNKNOWN"
                            )}
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


function renderRuntimeWarnings(
    calibration
) {
    const overview =
        document.getElementById(
            "overview-runtime-warning"
        );

    const calibrationNote =
        document.getElementById(
            "calibration-runtime-note"
        );

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
        rotation.forced
        === true
        ||
        String(
            rotation.status
            || ""
        )
        .toUpperCase()
        .includes(
            "FORCED"
        );

    if (!forced) {
        overview.classList.add(
            "hidden"
        );

        calibrationNote.classList.add(
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

    const message = `
        <strong>
            ⚠ Geometry: FORCED ACTIVE
        </strong>

        <span>
            Independent Holdout = FAILED
            ${
                failedPairs.length
                ? (
                    ` | Failed pairs: `
                    +
                    `${escapeHtml(
                        failedPairs.join(", ")
                    )}`
                )
                : ""
            }
        </span>
    `;

    overview.innerHTML =
        message;

    calibrationNote.innerHTML =
        message;

    overview.classList.remove(
        "hidden"
    );

    calibrationNote.classList.remove(
        "hidden"
    );

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
                title
                ?.textContent
                ?.trim()
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
                    method:
                        "POST",

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

        controlCenterCsrf =
            data.csrf;

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


function testCard(
    toolId,
    tool,
) {
    const flags = [];

    if (
        tool
        .requires_detection_stopped
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
                ${escapeHtml(
                    tool.label
                    || toolId
                )}
            </div>

            <div class="test-description">
                ${escapeHtml(
                    tool.description
                    || ""
                )}
            </div>

            <div class="test-flags">
                ${
                    flags.length
                    ? flags.map(
                        flag =>
                            (
                                `<span class="mini-badge">`
                                +
                                `${escapeHtml(flag)}`
                                +
                                `</span>`
                            )
                    )
                    .join("")
                    : (
                        '<span class="mini-badge">'
                        +
                        'Safe inspection'
                        +
                        '</span>'
                    )
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
                        tool.exists
                        === false
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

    const results =
        await Promise.all([
            getJSON(
                "/api/commissioning/catalog"
            ),
            controlCenterSession(),
        ]);

    const catalog =
        results[0];

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
            (
                "Manager ยัง LOCKED — "
                +
                "Unlock ก่อนรัน Test"
            );

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
            !confirm(
                message
            )
        ) {
            return;
        }

        output.textContent =
            (
                `Running ${plan.label}...`
                +
                "\n\nPlease wait."
            );

        const response =
            await fetch(
                `/api/commissioning/tool/${encodeURIComponent(toolId)}/run`,
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json",

                        "X-CSRF-Token":
                            controlCenterCsrf,
                    },

                    body:
                        JSON.stringify({
                            confirm:
                                true,
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
                loadOverview()
                    .catch(
                        console.error
                    );
            },
            1000,
        );

    } catch (error) {
        output.textContent +=
            (
                "\n\nERROR: "
                +
                String(error)
            );
    }
};


const testUnlockButton =
    document.getElementById(
        "test-unlock-btn"
    );

if (testUnlockButton) {
    testUnlockButton
        .addEventListener(
            "click",
            unlockControlCenter
        );
}


loadControlTests()
    .catch(
        error => {
            const output =
                document.getElementById(
                    "runtime-test-output"
                );

            if (output) {
                output.textContent =
                    (
                        "Test Center load failed: "
                        +
                        String(error)
                    );
            }
        }
    );
'''

    text += addon


p.write_text(
    text,
    encoding="utf-8",
)

print(
    "CONTROL_CENTER_JS=PATCHED"
)
PY


# ============================================================
# CSS
# ============================================================

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


# ============================================================
# Validation
# ============================================================

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
    node --check \
        manager/static/manager.js
fi

echo
echo "=== STATIC CHECK ==="

grep -q \
  'renderSystemSnapshot(' \
  manager/static/manager.js \
  && echo "System renderer: INSTALLED"

grep -q \
  'CONTROL_CENTER_OPERATIONAL_V1' \
  manager/static/manager.js \
  && echo "Operational JS: INSTALLED"

if grep -q \
  '"system-json"' \
  manager/static/manager.js
then
    echo "ERROR: stale system-json reference remains"
    exit 1
else
    echo "Legacy system-json reference: REMOVED"
fi


# ============================================================
# Restart Manager only
# ============================================================

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
    echo
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
echo "CONTROL_CENTER_OPERATIONAL_V1_2=COMPLETE"
echo "Backup: $BACKUP"
