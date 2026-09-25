let overviewData = null;
let selectedMode = "LAB";


const titles = {
    overview: [
        "Overview",
        "Runtime and installation status",
    ],

    setup: [
        "Setup",
        "Installation workflow",
    ],

    sites: [
        "Sites",
        "Site lifecycle and configuration",
    ],

    calibration: [
        "Calibration",
        "Geometry and measurement status",
    ],

    tests: [
        "Tests",
        "Verification center",
    ],

    events: [
        "Events",
        "Detection and alert history",
    ],

    system: [
        "System",
        "Server and service status",
    ],
};


function clsForStatus(status) {

    const value = String(
        status || ""
    ).toUpperCase();

    if (
        value.includes("READY")
        ||
        value.includes("ACTIVE")
        ||
        value === "PASS"
    ) {
        return "good";
    }

    if (
        value.includes("REQUIRED")
        ||
        value.includes("FAIL")
    ) {
        return "bad";
    }

    if (
        value.includes("DEFERRED")
        ||
        value.includes("UNVERIFIED")
        ||
        value.includes("DISABLED")
    ) {
        return "warn";
    }

    return "info";
}


function card(
    label,
    value,
    className = "",
) {

    return `
        <div class="card">
            <div class="card-label">
                ${label}
            </div>

            <div class="card-value ${className}">
                ${value ?? "—"}
            </div>
        </div>
    `;
}


function statusItem(
    title,
    value,
    className = "",
) {

    return `
        <div class="status-item">
            <div class="status-title">
                ${title}
            </div>

            <div class="status-value ${className}">
                ${value ?? "—"}
            </div>
        </div>
    `;
}


async function getJSON(url) {

    const response = await fetch(
        url,
        {
            cache: "no-store",
        }
    );

    if (!response.ok) {
        throw new Error(
            `${response.status} ${url}`
        );
    }

    return await response.json();
}


async function loadOverview() {

    const data = await getJSON(
        "/api/overview"
    );

    overviewData = data;


    const discovery = data.discovery;
    const setup = data.setup;

    const install =
        discovery.installation;

    const services =
        discovery.system.services;

    const core =
        discovery.runtime_core;


    document
        .getElementById(
            "manager-dot"
        )
        .classList
        .add("ok");


    document.getElementById(
        "site-mode"
    ).textContent =
        install.mode || "UNKNOWN";


    document.getElementById(
        "site-name"
    ).textContent =
        install.active_site
        || "No active site";


    document.getElementById(
        "overview-cards"
    ).innerHTML =
        card(
            "Installation",
            install.detected,
            (
                install.detected
                === "EXISTING"
                ? "good"
                : "warn"
            )
        )
        +
        card(
            "Detection",
            services.detection.active,
            clsForStatus(
                services.detection.active
            )
        )
        +
        card(
            "Dashboard",
            services.dashboard.active,
            clsForStatus(
                services.dashboard.active
            )
        )
        +
        card(
            "Setup readiness",
            (
                setup.ready
                ? "READY"
                : `${setup.blocker_count} blocker(s)`
            ),
            (
                setup.ready
                ? "good"
                : "warn"
            )
        );


    document.getElementById(
        "core-grid"
    ).innerHTML =
        statusItem(
            "Dynamic Geometry",
            (
                core.dynamic_geometry
                ? "ACTIVE"
                : "INACTIVE"
            ),
            (
                core.dynamic_geometry
                ? "good"
                : "bad"
            )
        )
        +
        statusItem(
            "Cross-Preset Fusion",
            (
                core.cross_preset_fusion
                ? "ACTIVE"
                : "INACTIVE"
            ),
            (
                core.cross_preset_fusion
                ? "good"
                : "bad"
            )
        )
        +
        statusItem(
            "Anchor max age",
            `${core.anchor_max_age_sec ?? "—"} s`,
            "info"
        )
        +
        statusItem(
            "Alert finalization",
            core.pending_mode,
            clsForStatus(
                core.pending_mode
            )
        )
        +
        statusItem(
            "Safety timeout",
            `${core.pending_safety_sec ?? "—"} s`,
            "info"
        )
        +
        statusItem(
            "Temporal consensus",
            `${core.temporal_consensus.minimum_confirm ?? "?"}/${core.temporal_consensus.frames_per_scan ?? "?"}`,
            "good"
        );


    renderPlan(
        setup,
        "readiness"
    );


    const existing =
        document.getElementById(
            "existing-choice"
        );

    if (
        install.detected
        === "EXISTING"
    ) {
        existing.classList.add(
            "detected"
        );
    }


    document.getElementById(
        "sites-json"
    ).textContent =
        JSON.stringify(
            {
                installation:
                    discovery.installation,
            },
            null,
            2,
        );


    const cal =
        discovery.calibration;

    document.getElementById(
        "calibration-grid"
    ).innerHTML =
        statusItem(
            "Intrinsics",
            (
                cal.intrinsics.exists
                ? "CALIBRATED"
                : "MISSING"
            ),
            (
                cal.intrinsics.exists
                ? "good"
                : "bad"
            )
        )
        +
        statusItem(
            "Preset Rotation",
            (
                cal.rotation.loaded
                ? (
                    cal.rotation.status
                    || "LOADED"
                )
                : "MISSING"
            ),
            (
                cal.rotation.loaded
                ? "good"
                : "bad"
            )
        )
        +
        statusItem(
            "Distance",
            (
                cal.distance.loaded
                ? "CALIBRATED_UNVERIFIED"
                : "MISSING"
            ),
            (
                cal.distance.loaded
                ? "warn"
                : "bad"
            )
        );


    document.getElementById(
        "system-json"
    ).textContent =
        JSON.stringify(
            discovery.system,
            null,
            2,
        );


    selectedMode =
        install.mode
        || "LAB";

    await loadSetupPlan(
        selectedMode
    );
}


function renderPlan(
    plan,
    targetId = "setup-plan",
) {

    const html =
        plan.checklist.map(
            item => `
                <div class="wizard-item">

                    <div>
                        <strong>
                            ${item.label}
                        </strong>

                        <div class="wizard-detail">
                            ${item.detail}
                        </div>
                    </div>

                    <div class="${clsForStatus(item.status)}">
                        ${item.status}
                    </div>

                </div>
            `
        ).join("");


    const target =
        document.getElementById(
            targetId
        );

    if (target) {
        target.innerHTML = html;
    }
}


async function loadSetupPlan(
    mode,
) {

    selectedMode = mode;

    const plan = await getJSON(
        `/api/setup/plan?mode=${encodeURIComponent(mode)}`
    );


    document
        .querySelectorAll(
            ".mode-btn"
        )
        .forEach(
            button => {

                button.classList.toggle(
                    "active",
                    button.dataset.mode
                    === mode
                );
            }
        );


    renderPlan(
        plan,
        "setup-plan"
    );
}


document
    .querySelectorAll(".nav")
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    const page =
                        button.dataset.page;


                    document
                        .querySelectorAll(
                            ".nav"
                        )
                        .forEach(
                            item =>
                                item
                                .classList
                                .remove(
                                    "active"
                                )
                        );


                    button
                        .classList
                        .add(
                            "active"
                        );


                    document
                        .querySelectorAll(
                            ".page"
                        )
                        .forEach(
                            section =>
                                section
                                .classList
                                .remove(
                                    "active"
                                )
                        );


                    document
                        .getElementById(
                            `page-${page}`
                        )
                        .classList
                        .add(
                            "active"
                        );


                    document.getElementById(
                        "page-title"
                    ).textContent =
                        titles[page][0];


                    document.getElementById(
                        "page-subtitle"
                    ).textContent =
                        titles[page][1];
                }
            );
        }
    );


document
    .querySelectorAll(
        ".mode-btn"
    )
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    loadSetupPlan(
                        button.dataset.mode
                    );
                }
            );
        }
    );


loadOverview()
    .catch(
        error => {

            console.error(
                error
            );

            document.getElementById(
                "manager-dot"
            ).classList.remove(
                "ok"
            );
        }
    );


setInterval(
    () => {

        loadOverview().catch(
            console.error
        );

    },
    10000,
);
