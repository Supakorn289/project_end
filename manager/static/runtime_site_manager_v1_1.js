(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  let inv = null;
  let csrf = null;

  async function api(url, options = {}) {
    const cfg = {cache: "no-store", ...options};
    cfg.headers = {...(cfg.headers || {}), "Content-Type": "application/json"};

    const method = String(cfg.method || "GET").toUpperCase();
    if (csrf && !["GET", "HEAD", "OPTIONS"].includes(method)) {
      cfg.headers["X-CSRF-Token"] = csrf;
    }

    const res = await fetch(url, cfg);
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || `${res.status} ${url}`);
    }

    return data;
  }

  async function loadSession() {
    const data = await api("/api/auth/session");
    csrf = data.authenticated ? data.csrf : null;
    return data;
  }

  function out(value) {
    const box = $("rsm-output");
    if (box) {
      box.textContent = typeof value === "string"
        ? value
        : JSON.stringify(value, null, 2);
    }
  }

  function msg(value, type = "") {
    const box = $("rsm-switch-status");
    if (!box) return;

    box.className = `rsm-switch-status ${type}`.trim();
    box.textContent = value;
  }

  function selectedSite() {
    const id = $("rsm-switch-site")?.value;
    return inv?.sites?.find(x => x.site_id === id) || null;
  }

  function selectedRevision() {
    const s = selectedSite();
    const id = $("rsm-switch-revision")?.value;
    return s?.revisions?.find(x => x.revision_id === id) || null;
  }

  function selectedChanged() {
    const s = selectedSite();
    const r = selectedRevision();

    if (!s || !r) return;

    const isActive =
      s.site_id === inv.active_site &&
      r.revision_id === inv.active_revision;

    $("rsm-switch-activate").disabled =
      isActive || r.candidate_ready !== true;

    $("rsm-switch-edit-runtime").disabled =
      !r.source_exists;

    $("rsm-switch-plan").disabled = false;

    let text =
      `Selected Site: ${s.site_id}\n` +
      `Selected Revision: ${r.revision_id}\n` +
      `Status: ${r.status || "UNKNOWN"}\n` +
      `candidate_ready: ${r.candidate_ready === true}\n` +
      `active_now: ${isActive}`;

    if (r.geometry?.forced) {
      text += "\nWARNING: Revision นี้ใช้ FORCED geometry และ Holdout ไม่ผ่าน";
    }

    if (r.candidate_ready !== true) {
      text += "\nRevision นี้ Activate ไม่ได้จนกว่าจะผ่าน Final Verification";
    }

    msg(text, r.geometry?.forced ? "warn" : "");
  }

  function fillRevisions() {
    const s = selectedSite();
    const select = $("rsm-switch-revision");
    const activate = $("rsm-switch-activate");
    const editRuntime = $("rsm-switch-edit-runtime");
    const plan = $("rsm-switch-plan");

    select.innerHTML = "";
    const revisions = s?.revisions || [];

    if (!revisions.length) {
      select.innerHTML = '<option value="">ไม่มี Revision</option>';
      activate.disabled = true;
      editRuntime.disabled = true;
      plan.disabled = true;
      msg("Site นี้ยังไม่มี Revision ที่สามารถเลือกเป็น Runtime", "warn");
      return;
    }

    for (const r of revisions) {
      const opt = document.createElement("option");
      opt.value = r.revision_id;
      opt.textContent =
        `${r.revision_id} · ${r.status || "UNKNOWN"} · ` +
        `${r.active ? "ACTIVE" : (r.candidate_ready ? "READY" : "NOT READY")}`;

      if (r.active) opt.selected = true;
      select.appendChild(opt);
    }

    selectedChanged();
  }

  async function refresh() {
    inv = await api("/api/runtime-sites");

    $("rsm-current-runtime").textContent =
      `${inv.active_site || "NONE"} → ${inv.active_revision || "NONE"}`;

    const sites = $("rsm-switch-site");
    sites.innerHTML = "";

    for (const s of inv.sites || []) {
      const opt = document.createElement("option");
      opt.value = s.site_id;
      opt.textContent =
        `${s.display_name || s.site_id} · ${s.site_id} · ` +
        `${s.active ? "ACTIVE" : "INACTIVE"}`;

      if (s.site_id === inv.active_site) opt.selected = true;
      sites.appendChild(opt);
    }

    fillRevisions();
  }

  async function ensureUnlocked() {
    const session = await loadSession();

    if (session.authenticated) return true;

    msg("Manager LOCKED — Unlock ก่อนแก้ไขหรือสลับ Runtime", "warn");

    const login = $("rsm-login");
    if (login) {
      login.classList.remove("rsm-hidden");
      login.scrollIntoView({behavior: "smooth", block: "center"});
    }

    return false;
  }

  async function checkPlan() {
    const s = selectedSite();
    const r = selectedRevision();

    if (!s || !r || !(await ensureUnlocked())) return;

    try {
      msg("กำลังตรวจ Activation Plan...");

      const result = await api(
        `/api/activation/${encodeURIComponent(s.site_id)}/` +
        `${encodeURIComponent(r.revision_id)}/plan`
      );

      out(result);

      msg(
        `Activation Plan: ${result.activatable ? "READY" : "BLOCKED"}` +
        (result.warnings?.length ? `\n${result.warnings.join("\n")}` : ""),
        result.activatable ? "good" : "warn"
      );
    } catch (e) {
      msg(String(e), "warn");
    }
  }

  async function activate() {
    const s = selectedSite();
    const r = selectedRevision();

    if (!s || !r || !(await ensureUnlocked())) return;

    if (r.candidate_ready !== true) {
      msg("Revision นี้ยังไม่พร้อม Activate", "warn");
      return;
    }

    const ok = confirm(
      "Switch Active Runtime?\n\n" +
      `FROM\n${inv.active_site} → ${inv.active_revision}\n\n` +
      `TO\n${s.site_id} → ${r.revision_id}\n\n` +
      "ระบบจะใช้ transaction เดิม: backup / validation / preflight / rollback"
    );

    if (!ok) return;

    try {
      msg("กำลัง Switch Runtime...");

      const result = await api(
        `/api/runtime-sites/${encodeURIComponent(s.site_id)}/revision/` +
        `${encodeURIComponent(r.revision_id)}/activate`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_site_id: s.site_id,
            confirm_revision_id: r.revision_id
          })
        }
      );

      out(result);
      msg(`Activation PASS\n${s.site_id} → ${r.revision_id}`, "good");

      setTimeout(() => location.reload(), 800);
    } catch (e) {
      msg(
        "Activation FAIL\n" + String(e) +
        "\nตรวจ Operation Result / rollback ก่อนลองใหม่",
        "warn"
      );
    }
  }

  function clickExisting(attr, value) {
    const button = [...document.querySelectorAll(`[${attr}]`)]
      .find(x => x.getAttribute(attr) === value);

    if (!button) {
      msg("ไม่พบ action ของรายการที่เลือก", "warn");
      return;
    }

    button.click();
  }

  function scrollEditor(id) {
    setTimeout(() => {
      const el = $(id);

      if (!el || el.classList.contains("rsm-hidden")) {
        return;
      }

      el.classList.add("rsm-focus-panel");
      el.scrollIntoView({behavior: "smooth", block: "start"});

      setTimeout(
        () => el.classList.remove("rsm-focus-panel"),
        1600
      );
    }, 120);
  }

  function installScrollFix() {
    document.addEventListener("click", event => {
      const b = event.target.closest("button");
      if (!b) return;

      if (b.matches("[data-rsm-edit-site]")) {
        scrollEditor("rsm-site-editor");
      }

      if (b.matches("[data-rsm-edit-runtime]")) {
        scrollEditor("rsm-runtime-editor");
      }

      if (b.id === "rsm-new-site") {
        scrollEditor("rsm-create-form");
      }
    }, true);
  }

  function install() {
    const host = $("runtime-site-manager");

    if (!host || $("rsm-runtime-switcher")) {
      return false;
    }

    const panel = document.createElement("section");
    panel.id = "rsm-runtime-switcher";
    panel.className = "rsm-panel rsm-switcher-panel";

    panel.innerHTML = `
      <div class="rsm-switcher-head">
        <div>
          <h3>Runtime Selector</h3>
          <p>เลือก Site และ Revision ที่ต้องการให้เครื่องใช้จริง</p>
        </div>

        <div class="rsm-current-box">
          <span>Current Runtime</span>
          <strong id="rsm-current-runtime" class="rsm-mono">Loading...</strong>
        </div>
      </div>

      <div class="rsm-switcher-grid">
        <label>
          <span>1. Site</span>
          <select id="rsm-switch-site"></select>
        </label>

        <label>
          <span>2. Runtime Revision</span>
          <select id="rsm-switch-revision"></select>
        </label>
      </div>

      <div class="rsm-switcher-actions">
        <button id="rsm-switch-edit-site" class="rsm-btn" type="button">
          Edit Selected Site
        </button>

        <button id="rsm-switch-edit-runtime" class="rsm-btn" type="button">
          Edit Selected Runtime
        </button>

        <button id="rsm-switch-plan" class="rsm-btn" type="button">
          Check Activation Plan
        </button>

        <button id="rsm-switch-activate" class="rsm-btn primary" type="button">
          Activate Selected Runtime
        </button>
      </div>

      <pre id="rsm-switch-status" class="rsm-switch-status">Loading...</pre>
    `;

    const first = host.querySelector(".rsm-panel");

    if (first?.nextSibling) {
      host.insertBefore(panel, first.nextSibling);
    } else {
      host.prepend(panel);
    }

    $("rsm-switch-site").onchange = fillRevisions;
    $("rsm-switch-revision").onchange = selectedChanged;
    $("rsm-switch-plan").onclick = checkPlan;
    $("rsm-switch-activate").onclick = activate;

    $("rsm-switch-edit-site").onclick = () => {
      const s = selectedSite();
      if (!s) return;

      clickExisting("data-rsm-edit-site", s.site_id);
    };

    $("rsm-switch-edit-runtime").onclick = () => {
      const s = selectedSite();
      const r = selectedRevision();

      if (!s || !r) return;

      clickExisting(
        "data-rsm-edit-runtime",
        `${s.site_id}|${r.revision_id}`
      );
    };

    return true;
  }

  async function init() {
    for (let i = 0; i < 50 && !$("runtime-site-manager"); i++) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    if (!$("runtime-site-manager")) return;

    install();
    installScrollFix();

    try {
      await loadSession();
      await refresh();
    } catch (e) {
      msg(String(e), "warn");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, {once: true});
  } else {
    init();
  }
})();
