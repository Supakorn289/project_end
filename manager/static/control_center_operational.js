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
