(() => {
"use strict";

let csrf = null;
let data = null;
let editingSite = null;
let workingSite = null;

const $ = id => document.getElementById(id);
const esc = v => String(v ?? "")
  .replaceAll("&","&amp;").replaceAll("<","&lt;")
  .replaceAll(">","&gt;").replaceAll('"',"&quot;")
  .replaceAll("'","&#039;");

async function req(url, options={}) {
  const cfg = {cache:"no-store", ...options};
  cfg.headers = {...(cfg.headers||{}), "Content-Type":"application/json"};
  const method = String(cfg.method||"GET").toUpperCase();
  if (csrf && !["GET","HEAD","OPTIONS"].includes(method)) {
    cfg.headers["X-CSRF-Token"] = csrf;
  }
  const response = await fetch(url, cfg);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || JSON.stringify(body));
  return body;
}

function out(v) {
  const box = $("rsm-output");
  if (box) box.textContent = typeof v === "string" ? v : JSON.stringify(v,null,2);
}

async function session() {
  const s = await req("/api/auth/session");
  csrf = s.authenticated ? s.csrf : null;
  const badge = $("rsm-auth");
  const login = $("rsm-login");
  if (badge) {
    badge.textContent = s.authenticated ? "UNLOCKED" : "LOCKED";
    badge.className = `rsm-badge ${s.authenticated ? "rsm-good" : "rsm-warn"}`;
  }
  if (login) login.classList.toggle("rsm-hidden", s.authenticated);
  return s;
}

async function unlock() {
  const token = $("rsm-token")?.value?.trim() || "";
  if (!token) return out("กรุณาใส่ Manager Token");
  try {
    const r = await req("/api/auth/login", {
      method:"POST",
      body:JSON.stringify({token}),
    });
    csrf = r.csrf;
    $("rsm-token").value = "";
    await session();
    out("Manager unlocked");
  } catch (e) { out(String(e)); }
}

function locationText(site) {
  const l = site.location || {};
  const label = l.installation_location || "—";
  return (l.latitude == null || l.longitude == null)
    ? label : `${label} · ${l.latitude}, ${l.longitude}`;
}

function revisionHTML(site, rev) {
  const c = rev.camera || {};
  const g = rev.geometry || {};
  return `
  <div class="rsm-revision">
    <div class="rsm-row between">
      <div>
        <strong class="rsm-mono">${esc(rev.revision_id)}</strong>
        <div class="rsm-sub">${esc(rev.status||"UNKNOWN")} · ready=${rev.candidate_ready===true}</div>
      </div>
      <div class="rsm-tags">
        ${rev.active ? '<span class="rsm-badge rsm-good">ACTIVE</span>' : ""}
        ${g.status ? `<span class="rsm-badge ${g.forced?"rsm-warn":""}">${esc(g.status)}</span>` : ""}
      </div>
    </div>
    <div class="rsm-meta">
      <span>Camera ${esc(c.camera_ip||"—")}</span>
      <span>RTSP ${esc(c.rtsp_port||"—")} ${esc(c.rtsp_path||"")}</span>
      <span>source=${rev.source_exists?"yes":"no"}</span>
      <span>deployed=${rev.deployment_exists?"yes":"no"}</span>
    </div>
    <div class="rsm-actions">
      <button class="rsm-btn" data-inspect="${esc(site.site_id)}|${esc(rev.revision_id)}">Inspect</button>
      <button class="rsm-btn primary" data-activate="${esc(site.site_id)}|${esc(rev.revision_id)}"
        ${rev.active || rev.candidate_ready!==true ? "disabled" : ""}>Activate</button>
      <button class="rsm-btn" data-edit-runtime="${esc(site.site_id)}|${esc(rev.revision_id)}"
        ${!rev.source_exists ? "disabled" : ""}>Edit Runtime</button>
      <button class="rsm-btn danger" data-delete-rev="${esc(site.site_id)}|${esc(rev.revision_id)}"
        ${!rev.deletable ? "disabled" : ""}>Delete Revision</button>
    </div>
  </div>`;
}

function siteHTML(site) {
  const w = site.working_copy || {};
  return `
  <article class="rsm-site ${site.active?"active":""}">
    <div class="rsm-row between">
      <div>
        <h3>${esc(site.display_name||site.site_id)}</h3>
        <div class="rsm-sub rsm-mono">${esc(site.site_id)}</div>
      </div>
      <div class="rsm-tags">
        <span class="rsm-badge ${site.active?"rsm-good":""}">${site.active?"ACTIVE SITE":"INACTIVE"}</span>
        <span class="rsm-badge">${esc(site.mode||"UNKNOWN")}</span>
        ${site.validation_state ? `<span class="rsm-badge">${esc(site.validation_state)}</span>` : ""}
      </div>
    </div>

    <div class="rsm-grid">
      <div><span>Location</span><strong>${esc(locationText(site))}</strong></div>
      <div><span>Active Revision</span><strong class="rsm-mono">${esc(site.active_revision_id||"—")}</strong></div>
      <div><span>Config State</span><strong>${esc(site.configuration_state||"CLEAN")}</strong></div>
      <div><span>Working Copy</span><strong>${w.exists ? esc(w.parent_revision||w.state||"YES") : "NONE"}</strong></div>
    </div>

    ${(site.warnings||[]).length ? `<div class="rsm-warning">${site.warnings.map(x=>`<div>⚠ ${esc(x)}</div>`).join("")}</div>` : ""}

    <div class="rsm-actions">
      <button class="rsm-btn" data-edit-site="${esc(site.site_id)}">Edit Site</button>
      <button class="rsm-btn danger" data-delete-site="${esc(site.site_id)}" ${!site.deletable?"disabled":""}>Delete Site</button>
    </div>

    <details class="rsm-revisions">
      <summary>Revisions (${(site.revisions||[]).length})</summary>
      <div class="rsm-revision-list">
        ${(site.revisions||[]).length ? site.revisions.map(r=>revisionHTML(site,r)).join("") : '<div class="rsm-empty">ยังไม่มี Revision</div>'}
      </div>
    </details>
  </article>`;
}

function bindActions() {
  document.querySelectorAll("[data-edit-site]").forEach(b =>
    b.onclick = () => openSiteEditor(b.dataset.editSite));
  document.querySelectorAll("[data-inspect]").forEach(b =>
    b.onclick = () => {
      const [s,r] = b.dataset.inspect.split("|"); inspectRevision(s,r);
    });
  document.querySelectorAll("[data-activate]").forEach(b =>
    b.onclick = () => {
      const [s,r] = b.dataset.activate.split("|"); activateRevision(s,r);
    });
  document.querySelectorAll("[data-edit-runtime]").forEach(b =>
    b.onclick = () => {
      const [s,r] = b.dataset.editRuntime.split("|"); openRuntimeEditor(s,r);
    });
  document.querySelectorAll("[data-delete-rev]").forEach(b =>
    b.onclick = () => {
      const [s,r] = b.dataset.deleteRev.split("|"); deleteRevision(s,r);
    });
  document.querySelectorAll("[data-delete-site]").forEach(b =>
    b.onclick = () => deleteSite(b.dataset.deleteSite));
}

async function refresh() {
  data = await req("/api/runtime-sites");
  $("rsm-active").innerHTML =
    `<strong>Active Runtime</strong> <span class="rsm-mono">${esc(data.active_site||"NONE")}</span> → <span class="rsm-mono">${esc(data.active_revision||"NONE")}</span>`;
  $("rsm-sites").innerHTML = (data.sites||[]).length
    ? data.sites.map(siteHTML).join("")
    : '<div class="rsm-empty">ยังไม่มี Site</div>';
  bindActions();
}

function findSite(id) {
  return data?.sites?.find(x => x.site_id === id) || null;
}

function openSiteEditor(id) {
  const site = findSite(id); if (!site) return;
  editingSite = id;
  const l = site.location || {};
  $("rsm-edit-id").textContent = id;
  $("rsm-edit-name").value = site.display_name || id;
  $("rsm-edit-mode").value = site.mode || "LAB";
  $("rsm-edit-location").value = l.installation_location || "";
  $("rsm-edit-lat").value = l.latitude ?? "";
  $("rsm-edit-lon").value = l.longitude ?? "";
  $("rsm-site-editor").classList.remove("rsm-hidden");
}

async function saveSiteEdit() {
  if (!editingSite) return;
  const payload = {
    display_name:$("rsm-edit-name").value.trim(),
    mode:$("rsm-edit-mode").value,
    installation_location:$("rsm-edit-location").value.trim(),
    latitude:$("rsm-edit-lat").value,
    longitude:$("rsm-edit-lon").value,
  };
  try {
    const p = await req(`/api/runtime-sites/${encodeURIComponent(editingSite)}/update-preview`, {
      method:"POST", body:JSON.stringify(payload),
    });
    let msg = `Update ${editingSite}?\n\nRisk: ${p.risk}\nChanged: ${(p.changed||[]).join(", ")||"none"}\nAffected: ${(p.affected||[]).join(", ")||"none"}`;
    if (p.warnings?.length) msg += "\n\n" + p.warnings.join("\n");
    if (!confirm(msg)) return;
    const r = await req(`/api/runtime-sites/${encodeURIComponent(editingSite)}`, {
      method:"PATCH", body:JSON.stringify(payload),
    });
    out(r);
    $("rsm-site-editor").classList.add("rsm-hidden");
    editingSite = null;
    await refresh();
  } catch(e) { out(String(e)); }
}

async function createSite() {
  const payload = {
    site_id:$("rsm-new-id").value.trim(),
    display_name:$("rsm-new-name").value.trim(),
    mode:$("rsm-new-mode").value,
    installation_location:$("rsm-new-location").value.trim(),
    latitude:$("rsm-new-lat").value,
    longitude:$("rsm-new-lon").value,
  };
  try {
    const r = await req("/api/runtime-sites", {method:"POST", body:JSON.stringify(payload)});
    out(r); $("rsm-create").classList.add("rsm-hidden"); await refresh();
  } catch(e) { out(String(e)); }
}

async function inspectRevision(site, rev) {
  try { out(await req(`/api/runtime-sites/${encodeURIComponent(site)}/revision/${encodeURIComponent(rev)}`)); }
  catch(e) { out(String(e)); }
}

async function activateRevision(site, rev) {
  const s = await session();
  if (!s.authenticated) return out("Manager LOCKED");
  if (!confirm(`Activate Runtime?\n\nSite: ${site}\nRevision: ${rev}\n\nระบบจะใช้ transaction + backup + rollback เดิม`)) return;
  try {
    out("กำลัง Activate...");
    const r = await req(`/api/runtime-sites/${encodeURIComponent(site)}/revision/${encodeURIComponent(rev)}/activate`, {
      method:"POST",
      body:JSON.stringify({confirm_site_id:site, confirm_revision_id:rev}),
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function openRuntimeEditor(site, rev) {
  const s = await session();
  if (!s.authenticated) return out("Manager LOCKED");
  let overwrite = false;
  const current = findSite(site);
  if (current?.working_copy?.exists) {
    overwrite = confirm(`Site ${site} มี Working Copy อยู่แล้ว\n\nOK = Archive ของเดิมแล้วเริ่มจาก ${rev}`);
    if (!overwrite) return;
  }
  try {
    const r = await req(`/api/runtime-sites/${encodeURIComponent(site)}/revision/${encodeURIComponent(rev)}/working-copy`, {
      method:"POST", body:JSON.stringify({overwrite}),
    });
    workingSite = site;
    $("rsm-working-site").textContent = site;
    $("rsm-working-parent").textContent = rev;
    const c = r.camera || {};
    $("rsm-camera-ip").value = c.camera_ip || "";
    $("rsm-camera-port").value = c.camera_port || 81;
    $("rsm-camera-user").value = "";
    $("rsm-camera-user").placeholder = c.camera_user_hint ? `เดิม: ${c.camera_user_hint} — เว้นว่างเพื่อคงค่าเดิม` : "Camera username";
    $("rsm-camera-password").value = "";
    $("rsm-rtsp-port").value = c.rtsp_port || 10554;
    $("rsm-rtsp-path").value = c.rtsp_path || "/tcp/av0_0";
    $("rsm-runtime-editor").classList.remove("rsm-hidden");
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function saveCameraDraft() {
  if (!workingSite) return;
  const payload = {
    camera_ip:$("rsm-camera-ip").value.trim(),
    camera_port:$("rsm-camera-port").value,
    rtsp_port:$("rsm-rtsp-port").value,
    rtsp_path:$("rsm-rtsp-path").value.trim(),
  };
  const u = $("rsm-camera-user").value.trim();
  const pw = $("rsm-camera-password").value;
  if (u) payload.camera_user = u;
  if (pw) payload.camera_password = pw;
  if (!confirm("Save Camera Working Copy?\n\nActive Runtime ยังไม่เปลี่ยน และต้อง Test Camera/RTSP ใหม่")) return;
  try {
    const r = await req(`/api/runtime-sites/${encodeURIComponent(workingSite)}/working-copy/camera`, {
      method:"PATCH", body:JSON.stringify(payload),
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function testCameraDraft() {
  if (!workingSite) return;
  if (!confirm("ทดสอบ Camera / RTSP Working Copy?\n\nDetection อาจหยุดชั่วคราวและจะ restore เมื่อจบ")) return;
  try {
    out("กำลังทดสอบ Camera / RTSP...");
    const r = await req(`/api/runtime-sites/${encodeURIComponent(workingSite)}/working-copy/camera/test`, {
      method:"POST", body:"{}",
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function publishDraft() {
  if (!workingSite) return;
  if (!confirm("Publish Working Copy เป็น Immutable Revision ใหม่?\n\nระบบจะรัน Final Verification และจะไม่แก้ Revision เดิม")) return;
  try {
    out("กำลัง Final Verification และสร้าง Revision...");
    const r = await req(`/api/runtime-sites/${encodeURIComponent(workingSite)}/working-copy/publish`, {
      method:"POST", body:"{}",
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function discardDraft() {
  if (!workingSite) return;
  if (!confirm(`Discard Working Copy ของ ${workingSite}?\n\nข้อมูลจะถูก Archive ไป Trash`)) return;
  try {
    const r = await req(`/api/runtime-sites/${encodeURIComponent(workingSite)}/working-copy`, {
      method:"DELETE", body:"{}",
    });
    out(r); $("rsm-runtime-editor").classList.add("rsm-hidden"); workingSite = null; await refresh();
  } catch(e) { out(String(e)); }
}

async function deleteRevision(site, rev) {
  try {
    const p = await req(`/api/runtime-sites/${encodeURIComponent(site)}/revision/${encodeURIComponent(rev)}/delete-preview`);
    if (!p.deletable) return out(p);
    const typed = prompt(`ลบ Revision แบบย้ายไป Trash\n\n${(p.warnings||[]).join("\n")}\n\nพิมพ์ Revision ID เพื่อยืนยัน:\n${rev}`);
    if (typed !== rev) return out("ยกเลิก: confirmation ไม่ตรง");
    const r = await req(`/api/runtime-sites/${encodeURIComponent(site)}/revision/${encodeURIComponent(rev)}`, {
      method:"DELETE", body:JSON.stringify({confirm_value:typed}),
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

async function deleteSite(site) {
  try {
    const p = await req(`/api/runtime-sites/${encodeURIComponent(site)}/delete-preview`);
    if (!p.deletable) return out(p);
    const typed = prompt(`ลบ Site แบบย้ายไป Trash\n\nRevisions: ${p.revision_count}\n${(p.warnings||[]).join("\n")}\n\nพิมพ์ Site ID เพื่อยืนยัน:\n${site}`);
    if (typed !== site) return out("ยกเลิก: confirmation ไม่ตรง");
    const r = await req(`/api/runtime-sites/${encodeURIComponent(site)}`, {
      method:"DELETE", body:JSON.stringify({confirm_value:typed}),
    });
    out(r); await refresh();
  } catch(e) { out(String(e)); }
}

function installUI() {
  const page = $("page-sites");
  if (!page || $("runtime-site-manager")) return !!page;

  Array.from(page.children).forEach(child => {
    if (child.classList?.contains("panel")) child.style.display = "none";
  });

  const host = document.createElement("div");
  host.id = "runtime-site-manager";
  host.innerHTML = `
    <div class="rsm-panel">
      <div class="rsm-row between">
        <div>
          <h2>Runtime & Site Manager</h2>
          <div class="rsm-sub">CRUD Site · Immutable Revision · Safe Activation</div>
        </div>
        <div class="rsm-actions">
          <span id="rsm-auth" class="rsm-badge">LOCKED</span>
          <button id="rsm-refresh" class="rsm-btn">Refresh</button>
          <button id="rsm-new-site" class="rsm-btn primary">+ New Site</button>
        </div>
      </div>

      <div id="rsm-login" class="rsm-login rsm-hidden">
        <strong>Manager Locked</strong>
        <input id="rsm-token" type="password" placeholder="Manager Token" autocomplete="current-password">
        <button id="rsm-unlock" class="rsm-btn primary">Unlock</button>
      </div>

      <div id="rsm-active" class="rsm-active"></div>

      <div class="rsm-policy">
        <strong>Safety policy:</strong>
        Site ID และ Revision ID เป็น immutable identity ·
        Runtime edit = Working Copy → Test/Verify → New Revision → Activate ·
        Active Site/Revision ห้ามลบ · Delete จะย้ายไป Trash
      </div>
    </div>

    <div id="rsm-create" class="rsm-panel rsm-hidden">
      <h3>Create Site</h3>
      <div class="rsm-form">
        <label>Site ID <input id="rsm-new-id" placeholder="site-id"></label>
        <label>Display Name <input id="rsm-new-name"></label>
        <label>Mode <select id="rsm-new-mode"><option>LAB</option><option>PRODUCTION</option></select></label>
        <label>Location <input id="rsm-new-location"></label>
        <label>Latitude <input id="rsm-new-lat" type="number" step="any"></label>
        <label>Longitude <input id="rsm-new-lon" type="number" step="any"></label>
      </div>
      <div class="rsm-actions">
        <button id="rsm-create-save" class="rsm-btn primary">Create</button>
        <button id="rsm-create-cancel" class="rsm-btn">Cancel</button>
      </div>
    </div>

    <div id="rsm-site-editor" class="rsm-panel rsm-hidden">
      <h3>Edit Site: <span id="rsm-edit-id" class="rsm-mono"></span></h3>
      <div class="rsm-warning">Site ID แก้ไม่ได้ เพราะผูกกับ calibration/revision paths</div>
      <div class="rsm-form">
        <label>Display Name <input id="rsm-edit-name"></label>
        <label>Mode <select id="rsm-edit-mode"><option>LAB</option><option>PRODUCTION</option></select></label>
        <label>Location <input id="rsm-edit-location"></label>
        <label>Latitude <input id="rsm-edit-lat" type="number" step="any"></label>
        <label>Longitude <input id="rsm-edit-lon" type="number" step="any"></label>
      </div>
      <div class="rsm-actions">
        <button id="rsm-edit-save" class="rsm-btn primary">Preview Risk & Update</button>
        <button id="rsm-edit-cancel" class="rsm-btn">Cancel</button>
      </div>
    </div>

    <div id="rsm-runtime-editor" class="rsm-panel rsm-hidden">
      <h3>Edit Runtime Working Copy</h3>
      <div class="rsm-warning"><strong>สำคัญ:</strong> Revision เดิมจะไม่ถูกแก้ การเปลี่ยนค่าจะยังไม่เข้า Runtime จนกว่า Publish + Activate</div>
      <div class="rsm-grid">
        <div><span>Site</span><strong id="rsm-working-site" class="rsm-mono"></strong></div>
        <div><span>Parent Revision</span><strong id="rsm-working-parent" class="rsm-mono"></strong></div>
      </div>
      <h4>Camera & Network</h4>
      <div class="rsm-form">
        <label>Camera IP <input id="rsm-camera-ip"></label>
        <label>HTTP Port <input id="rsm-camera-port" type="number"></label>
        <label>Username <input id="rsm-camera-user"></label>
        <label>Password <input id="rsm-camera-password" type="password" placeholder="เว้นว่างเพื่อคงค่าเดิม"></label>
        <label>RTSP Port <input id="rsm-rtsp-port" type="number"></label>
        <label>RTSP Path <input id="rsm-rtsp-path"></label>
      </div>
      <div class="rsm-actions">
        <button id="rsm-camera-save" class="rsm-btn primary">1. Save Draft</button>
        <button id="rsm-camera-test" class="rsm-btn">2. Test Camera / RTSP</button>
        <button id="rsm-draft-publish" class="rsm-btn primary">3. Publish New Revision</button>
        <button id="rsm-draft-discard" class="rsm-btn danger">Discard Working Copy</button>
      </div>
    </div>

    <div id="rsm-sites" class="rsm-list"></div>

    <div class="rsm-panel">
      <h3>Operation Result / Audit Detail</h3>
      <pre id="rsm-output">Ready</pre>
    </div>
  `;
  page.appendChild(host);

  $("rsm-refresh").onclick = () => refresh().catch(e=>out(String(e)));
  $("rsm-new-site").onclick = () => $("rsm-create").classList.remove("rsm-hidden");
  $("rsm-create-cancel").onclick = () => $("rsm-create").classList.add("rsm-hidden");
  $("rsm-create-save").onclick = createSite;
  $("rsm-unlock").onclick = unlock;
  $("rsm-edit-save").onclick = saveSiteEdit;
  $("rsm-edit-cancel").onclick = () => { editingSite=null; $("rsm-site-editor").classList.add("rsm-hidden"); };
  $("rsm-camera-save").onclick = saveCameraDraft;
  $("rsm-camera-test").onclick = testCameraDraft;
  $("rsm-draft-publish").onclick = publishDraft;
  $("rsm-draft-discard").onclick = discardDraft;
  return true;
}

async function init() {
  if (!installUI()) return;
  await Promise.allSettled([session(), refresh()]);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, {once:true});
} else {
  init();
}
})();
