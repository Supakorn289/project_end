let overviewData = null;

const titles = {
    overview: ["Overview", "Runtime and installation status"],
    setup: ["Setup", "Site setup and commissioning entry points"],
    sites: ["Sites", "Site lifecycle and runtime status"],
    calibration: ["Calibration", "Active calibration discovery"],
    tests: ["Tests", "Verification center"],
    events: ["Events", "Detection and alert history"],
    system: ["System", "Server and service status"],
};

function clsForStatus(status) {
    const value = String(status || "").toUpperCase();

    if (
        value.includes("READY")
        || value.includes("ACTIVE")
        || value.includes("VALIDATED")
        || value === "PASS"
    ) {
        return "good";
    }

    if (
        value.includes("REQUIRED")
        || value.includes("FAIL")
        || value.includes("ERROR")
    ) {
        return "bad";
    }

    if (
        value.includes("DRAFT")
        || value.includes("CANDIDATE")
        || value.includes("DEFERRED")
        || value.includes("UNVERIFIED")
        || value.includes("DISABLED")
    ) {
        return "warn";
    }

    return "info";
}

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function card(label, value, className = "") {
    return `
        <div class="card">
            <div class="card-label">${escapeHTML(label)}</div>
            <div class="card-value ${className}">
                ${escapeHTML(value ?? "—")}
            </div>
        </div>
    `;
}

function statusItem(title, value, className = "") {
    return `
        <div class="status-item">
            <div class="status-title">${escapeHTML(title)}</div>
            <div class="status-value ${className}">
                ${escapeHTML(value ?? "—")}
            </div>
        </div>
    `;
}

async function getJSON(url) {
    const response = await fetch(url, {cache: "no-store"});

    if (!response.ok) {
        throw new Error(`${response.status} ${url}`);
    }

    return await response.json();
}

function renderPlan(plan, targetId = "readiness") {
    const target = document.getElementById(targetId);

    if (!target || !plan || !Array.isArray(plan.checklist)) {
        return;
    }

    target.innerHTML = plan.checklist.map(
        item => `
            <div class="wizard-item">
                <div>
                    <strong>${escapeHTML(item.label)}</strong>
                    <div class="wizard-detail">
                        ${escapeHTML(item.detail)}
                    </div>
                </div>
                <div class="${clsForStatus(item.status)}">
                    ${escapeHTML(item.status)}
                </div>
            </div>
        `
    ).join("");
}

function renderSites(data) {
    const target = document.getElementById("sites-list");

    if (!target) {
        return;
    }

    const registry =
        data?.manager_registry?.sites
        || {};

    const runtimeSites =
        Array.isArray(data?.runtime_sites)
        ? data.runtime_sites
        : [];

    const runtimeActive = new Set(
        runtimeSites
            .filter(site => site && site.active)
            .map(site => String(site.site_id || ""))
    );

    const entries = Object.entries(registry);

    entries.sort((a, b) => {
        const aActive =
            Boolean(a[1]?.runtime_active)
            || runtimeActive.has(a[0]);

        const bActive =
            Boolean(b[1]?.runtime_active)
            || runtimeActive.has(b[0]);

        if (aActive !== bActive) {
            return aActive ? -1 : 1;
        }

        return String(b[1]?.updated_at || "")
            .localeCompare(String(a[1]?.updated_at || ""));
    });

    if (entries.length === 0) {
        target.innerHTML = `
            <div class="empty">
                ยังไม่มี Site ใน Manager registry
            </div>
        `;
        return;
    }

    target.innerHTML = entries.map(([id, site]) => {
        const active =
            Boolean(site?.runtime_active)
            || runtimeActive.has(id);

        const lifecycle =
            site?.lifecycle
            || "UNKNOWN";

        const validation =
            site?.validation_state
            || "UNKNOWN";

        const location =
            site?.location?.installation_location
            || "—";

        const actionLabel =
            lifecycle === "DRAFT"
            ? "ดำเนินการต่อ"
            : active
                ? "ตรวจ / ตั้งค่า"
                : "เปิด Site";

        const href =
            `/setup-wizard?mode=existing&site=${encodeURIComponent(id)}`;

        return `
            <article class="site-card ${active ? "runtime-active" : ""}">
                <div class="site-card-head">
                    <div>
                        <div class="site-name">
                            ${escapeHTML(site?.display_name || id)}
                        </div>
                        <div class="site-id">
                            ${escapeHTML(id)}
                        </div>
                    </div>

                    <div class="site-badges">
                        ${active ? '<span class="site-badge good">ACTIVE RUNTIME</span>' : ""}
                        <span class="site-badge ${clsForStatus(lifecycle)}">
                            ${escapeHTML(lifecycle)}
                        </span>
                    </div>
                </div>

                <div class="site-meta-grid">
                    <div>
                        <span>Mode</span>
                        <strong>${escapeHTML(site?.mode || "UNKNOWN")}</strong>
                    </div>
                    <div>
                        <span>Validation</span>
                        <strong class="${clsForStatus(validation)}">
                            ${escapeHTML(validation)}
                        </strong>
                    </div>
                    <div>
                        <span>Location</span>
                        <strong>${escapeHTML(location)}</strong>
                    </div>
                    <div>
                        <span>Source</span>
                        <strong>${escapeHTML(site?.source || "—")}</strong>
                    </div>
                </div>

                <div class="site-actions">
                    <a class="site-action" href="${href}">
                        ${actionLabel}
                    </a>
                </div>
            </article>
        `;
    }).join("");
}

async function loadOverview() {
    const [data, sitesData] = await Promise.all([
        getJSON("/api/overview"),
        getJSON("/api/sites"),
    ]);

    overviewData = data;

    const discovery = data.discovery;
    const setup = data.setup;
    const install = discovery.installation;
    const services = discovery.system.services;
    const core = discovery.runtime_core;

    document
        .getElementById("manager-dot")
        .classList
        .add("ok");

    document.getElementById("site-mode").textContent =
        install.mode || "UNKNOWN";

    document.getElementById("site-name").textContent =
        install.active_site || "No active site";

    document.getElementById("overview-cards").innerHTML =
        card(
            "Installation",
            install.detected,
            install.detected === "EXISTING" ? "good" : "warn"
        )
        + card(
            "Detection",
            services.detection.active,
            clsForStatus(services.detection.active)
        )
        + card(
            "Dashboard",
            services.dashboard.active,
            clsForStatus(services.dashboard.active)
        )
        + card(
            "Setup readiness",
            setup.ready
                ? "READY"
                : `${setup.blocker_count} blocker(s)`,
            setup.ready ? "good" : "warn"
        );

    document.getElementById("core-grid").innerHTML =
        statusItem(
            "Dynamic Geometry",
            core.dynamic_geometry ? "ACTIVE" : "INACTIVE",
            core.dynamic_geometry ? "good" : "bad"
        )
        + statusItem(
            "Cross-Preset Fusion",
            core.cross_preset_fusion ? "ACTIVE" : "INACTIVE",
            core.cross_preset_fusion ? "good" : "bad"
        )
        + statusItem(
            "Anchor max age",
            `${core.anchor_max_age_sec ?? "—"} s`,
            "info"
        )
        + statusItem(
            "Alert finalization",
            core.pending_mode,
            clsForStatus(core.pending_mode)
        )
        + statusItem(
            "Safety timeout",
            `${core.pending_safety_sec ?? "—"} s`,
            "info"
        )
        + statusItem(
            "Temporal consensus",
            `${core.temporal_consensus.minimum_confirm ?? "?"}/${core.temporal_consensus.frames_per_scan ?? "?"}`,
            "good"
        );

    renderPlan(setup, "readiness");
    renderSites(sitesData);

    const cal = discovery.calibration;

    document.getElementById("calibration-grid").innerHTML =
        statusItem(
            "Intrinsics",
            cal.intrinsics.exists ? "CALIBRATED" : "MISSING",
            cal.intrinsics.exists ? "good" : "bad"
        )
        + statusItem(
            "Preset Rotation",
            cal.rotation.loaded
                ? (cal.rotation.status || "LOADED")
                : "MISSING",
            cal.rotation.loaded ? "good" : "bad"
        )
        + statusItem(
            "Distance",
            cal.distance.loaded
                ? "CALIBRATED_UNVERIFIED"
                : "MISSING",
            cal.distance.loaded ? "warn" : "bad"
        );

    document.getElementById("system-json").textContent =
        JSON.stringify(discovery.system, null, 2);
}

document
    .querySelectorAll(".nav")
    .forEach(button => {
        button.addEventListener("click", () => {
            const page = button.dataset.page;

            document
                .querySelectorAll(".nav")
                .forEach(item => item.classList.remove("active"));

            button.classList.add("active");

            document
                .querySelectorAll(".page")
                .forEach(section => section.classList.remove("active"));

            document
                .getElementById(`page-${page}`)
                .classList
                .add("active");

            document.getElementById("page-title").textContent =
                titles[page][0];

            document.getElementById("page-subtitle").textContent =
                titles[page][1];
        });
    });

loadOverview().catch(error => {
    console.error(error);
    document.getElementById("manager-dot").classList.remove("ok");
});

setInterval(() => {
    loadOverview().catch(console.error);
}, 10000);
