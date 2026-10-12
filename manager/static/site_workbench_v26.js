(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = encodeURIComponent;
  const state = {inventory: null, site: '', revision: '', plan: null, csrf: '', busy: false, seq: 0};
  const at = (obj, key, fallback = '') => obj && obj[key] !== undefined && obj[key] !== null ? obj[key] : fallback;
  const selected = () => (state.inventory?.sites || []).find(x => x.site_id === state.site);
  const selectedRevision = () => (selected()?.revisions || []).find(x => x.revision_id === state.revision);

  function message(text, kind = 'info') {
    const el = $('sfw26-message');
    if (!el) return;
    el.textContent = text;
    el.dataset.kind = kind;
  }
  function text(id, value) { const el = $(id); if (el) el.textContent = String(value ?? '—'); }
  function setDisabled(id, value) { const el = $(id); if (el) el.disabled = Boolean(value); }
  function invalidatePlan() {
    state.plan = null;
    text('sfw26-plan-summary', 'ยังไม่ได้ตรวจ Activation Plan สำหรับรายการที่เลือก');
    text('sfw26-plan-details', '');
    updateButtons();
  }
  async function request(path, method = 'GET', payload) {
    const headers = {'Accept': 'application/json'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      if (!state.csrf) throw new Error('กรุณา Unlock Manager ใหม่ก่อนดำเนินการ');
      headers['X-CSRF-Token'] = state.csrf;
    }
    const response = await fetch(path, {
      method, headers, cache: 'no-store', credentials: 'same-origin',
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Error(`API ไม่คืน JSON (HTTP ${response.status})`); }
    if (!response.ok || data?.ok === false && method !== 'GET') {
      const reason = data?.reason || data?.error || `HTTP ${response.status}`;
      const error = new Error(String(reason));
      error.data = data;
      error.status = response.status;
      throw error;
    }
    return data;
  }
  async function authenticated() {
    const session = await request('/api/auth/session');
    state.csrf = session.authenticated && typeof session.csrf === 'string' ? session.csrf : '';
    if (!state.csrf) {
      message('กรุณากด Unlock Manager ก่อน แล้วกดรีเฟรชอีกครั้ง', 'warn');
      $('rsm-login')?.classList.remove('rsm-hidden');
      updateButtons();
      return false;
    }
    return true;
  }
  function sameSelection(site, revision) {
    return state.site === site && state.revision === revision;
  }
  function updateButtons() {
    const record = selected();
    const rev = selectedRevision();
    const activeSite = state.inventory?.active_site;
    const activeRevision = state.inventory?.active_revision;
    const initial = record && !record.active && record.revisions?.length === 0 &&
      !['UNREGISTERED', 'UNKNOWN'].includes(String(record.lifecycle).toUpperCase());
    const activeEdit = record && state.site === activeSite && state.revision === activeRevision && Boolean(rev);
    const readyPlan = state.plan && state.plan.site === state.site && state.plan.revision === state.revision &&
      state.plan.data?.activatable === true && Date.now() - state.plan.checkedAt < 120000;
    const isCurrent = state.site === activeSite && state.revision === activeRevision;
    setDisabled('sfw26-refresh', state.busy);
    setDisabled('sfw26-site', state.busy);
    setDisabled('sfw26-revision', state.busy);
    setDisabled('sfw26-plan', state.busy || !state.csrf || !rev);
    setDisabled('sfw26-activate', state.busy || !state.csrf || !readyPlan || isCurrent);
    setDisabled('sfw26-edit', state.busy || !state.csrf || !activeEdit);
    setDisabled('sfw26-setup', state.busy || !state.csrf || !initial);
    setDisabled('sfw26-delete', state.busy || !state.csrf || !record || record.active);
    setDisabled('sfw26-new', state.busy || !state.csrf);
  }
  function summary() {
    const record = selected();
    const revision = selectedRevision();
    const sites = state.inventory?.sites || [];
    text('sfw26-active', state.inventory?.active_site
      ? `${state.inventory.active_site}  /  ${state.inventory.active_revision || '—'}`
      : 'ไม่สามารถระบุ Active Site ได้');
    text('sfw26-count', `${sites.length} Site`);
    text('sfw26-mode', record?.mode || '—');
    text('sfw26-lifecycle', record?.lifecycle || '—');
    text('sfw26-working', record?.working_copy?.exists
      ? `Working Copy: ${record.working_copy.state || 'EDITING'}` : 'ยังไม่มี Working Copy ที่แก้ไขอยู่');
    text('sfw26-revision-status', revision
      ? `${revision.status || 'UNKNOWN'}${revision.candidate_ready ? ' · Validation snapshot: READY' : ' · Validation snapshot: NOT READY'}`
      : 'ยังไม่มี Revision — ไป Setup Site');
    text('sfw26-site-hint', !record ? 'ยังไม่ได้เลือก Site'
      : record.active ? 'Active Site: แก้ไขผ่าน Working Copy เท่านั้น'
      : !record.revisions?.length ? 'Site ใหม่: กรุณาตั้งค่าและ Verify ใน Setup Wizard'
      : 'Inactive Site: อ่านได้ แต่ห้ามแก้ไขจนกว่าจะ Activate สำเร็จ');
    text('sfw26-warning', (record?.warnings || []).slice(0, 4).join(' · ') || '');
    updateButtons();
  }
  function refillSites(requested) {
    const select = $('sfw26-site');
    if (!select) return;
    select.replaceChildren();
    const sites = state.inventory?.sites || [];
    for (const s of sites) {
      const label = s.active ? 'ACTIVE' : s.revisions?.length ? 'HAS REVISION' : 'NEEDS SETUP';
      const opt = new Option(`${s.display_name || s.site_id} · ${label}`, s.site_id);
      select.add(opt);
    }
    const candidate = sites.some(s => s.site_id === requested) ? requested :
      (sites.some(s => s.site_id === state.inventory?.active_site) ? state.inventory.active_site : sites[0]?.site_id || '');
    state.site = candidate;
    select.value = candidate;
    refillRevisions();
  }
  function refillRevisions(requested = '') {
    const select = $('sfw26-revision');
    if (!select) return;
    select.replaceChildren();
    const revisions = selected()?.revisions || [];
    for (const r of revisions) {
      const opt = new Option(`${r.revision_id} · ${r.status || 'UNKNOWN'}${r.active ? ' · ACTIVE' : ''}`, r.revision_id);
      select.add(opt);
    }
    const candidate = revisions.find(x => x.revision_id === requested)?.revision_id ||
      revisions.find(x => x.active)?.revision_id ||
      revisions.find(x => x.candidate_ready === true)?.revision_id ||
      revisions[0]?.revision_id || '';
    if (!revisions.length) select.add(new Option('ยังไม่มี Revision', ''));
    state.revision = candidate;
    select.value = candidate;
    invalidatePlan();
    summary();
  }
  async function refresh() {
    const requestSeq = ++state.seq;
    if (!(await authenticated())) return;
    const oldSite = state.site, oldRevision = state.revision;
    const inventory = await request('/api/runtime-sites');
    if (requestSeq !== state.seq) return;
    if (!inventory.ok || !Array.isArray(inventory.sites)) throw new Error('Inventory schema ไม่ถูกต้อง');
    state.inventory = inventory;
    refillSites(oldSite);
    if (state.site === oldSite) refillRevisions(oldRevision);
    message('อ่านรายการ Site ล่าสุดเรียบร้อย ยังไม่มีการแก้ Runtime', 'success');
  }
  function previewText(plan) {
    const parts = [
      `Site: ${plan.site_id || '—'}`,
      `Revision: ${plan.revision_id || '—'}`,
      `Activatable: ${plan.activatable === true ? 'YES' : 'NO'}`,
      `Mode: ${plan.mode || '—'}`,
      `Blocker: ${plan.error || '—'}`
    ];
    if (Array.isArray(plan.blockers)) parts.push(`Blockers: ${plan.blockers.map(String).join(' | ')}`);
    if (plan.safety_warning) parts.push(`Safety: ${plan.safety_warning}`);
    return parts.join('\n');
  }
  async function checkPlan() {
    if (!(await authenticated())) return;
    const site = state.site, rev = state.revision;
    if (!site || !rev || !selectedRevision()) throw new Error('กรุณาเลือก Site/Revision ที่มีอยู่จริง');
    invalidatePlan();
    text('sfw26-plan-summary', 'กำลังตรวจ Activation Plan จาก Backend...');
    let result;
    try { result = await request(`/api/activation/${esc(site)}/${esc(rev)}/plan`); }
    catch (error) {
      const payload = error.data || {};
      text('sfw26-plan-details', previewText({...payload, site_id: site, revision_id: rev}));
      text('sfw26-plan-summary', 'BLOCKED — Backend ไม่อนุญาตให้ Activate');
      message(String(error.message), 'warn');
      return;
    }
    if (!sameSelection(site, rev)) throw new Error('Site/Revision เปลี่ยนระหว่างตรวจ กรุณาตรวจใหม่');
    if (result.site_id !== site || result.revision_id !== rev) throw new Error('ACTIVATION_PLAN_IDENTITY_MISMATCH');
    state.plan = {site, revision: rev, checkedAt: Date.now(), data: result};
    text('sfw26-plan-details', previewText(result));
    text('sfw26-plan-summary', result.activatable === true
      ? 'READY จาก Activation Plan ปัจจุบัน — ต้องยืนยันอีกครั้งก่อนสลับ'
      : 'BLOCKED — Revision นี้ยังไม่ผ่านเกณฑ์');
    message(result.activatable ? 'ตรวจ Plan ผ่านแล้ว ไม่มีการสลับ Runtime ในขั้นตอนนี้' :
      'ยัง Activate ไม่ได้ กรุณาดู Blockers และไป Verify ใหม่', result.activatable ? 'success' : 'warn');
    updateButtons();
  }
  async function runAction(fn) {
    if (state.busy) return;
    state.busy = true; updateButtons();
    try { await fn(); }
    catch (error) { message(String(error.message || error), 'error'); }
    finally { state.busy = false; updateButtons(); }
  }
  async function activate() {
    if (!(await authenticated())) return;
    const site = state.site, rev = state.revision;
    if (!state.plan || state.plan.site !== site || state.plan.revision !== rev ||
        state.plan.data?.activatable !== true || Date.now() - state.plan.checkedAt > 120000) {
      throw new Error('Activation Plan หมดอายุหรือยังไม่ผ่าน กรุณาตรวจ Plan ใหม่');
    }
    const inventory = await request('/api/runtime-sites');
    if (inventory.active_site === site && inventory.active_revision === rev) throw new Error('Revision นี้ใช้งานอยู่แล้ว');
    if (!inventory.sites?.find(s => s.site_id === site)?.revisions?.some(r => r.revision_id === rev))
      throw new Error('Site/Revision ไม่อยู่ในรายการปัจจุบัน');
    const newPlan = await request(`/api/activation/${esc(site)}/${esc(rev)}/plan`);
    if (newPlan.site_id !== site || newPlan.revision_id !== rev || newPlan.activatable !== true)
      throw new Error('Revision ไม่ผ่าน Activation Plan ล่าสุด — ยกเลิก');
    if (state.plan.data.candidate_digest && newPlan.candidate_digest !== state.plan.data.candidate_digest)
      throw new Error('Revision digest เปลี่ยนหลังตรวจ Plan — ยกเลิก');
    if (!sameSelection(site, rev)) throw new Error('Selection เปลี่ยน — ยกเลิก');
    if (!window.confirm(`สลับ Runtime ไปที่\n${site}\n${rev}\n\nการ Activate จะหยุด/เริ่ม Detection ชั่วคราว\nโปรดตรวจพื้นที่และ PTZ ให้อยู่ในสภาพปลอดภัยก่อน`)) return;
    const typed = window.prompt(`พิมพ์ Site ID และ Revision ID เพื่อตกลงสลับ Runtime:\n${site}/${rev}`);
    if (typed !== `${site}/${rev}`) { message('ยกเลิก: ข้อความยืนยันไม่ตรง', 'warn'); return; }
    if (!sameSelection(site, rev)) throw new Error('Selection เปลี่ยนระหว่างยืนยัน');
    message('กำลังสลับ Runtime ผ่าน Activation Engine; ระบบ Detection อาจหยุดชั่วคราว', 'warn');
    const response = await request(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/activate`, 'POST',
      {confirm_site_id: site, confirm_revision_id: rev});
    if (response.ok !== true) throw new Error('Activation Engine ไม่รายงานผลสำเร็จ');
    const after = await request('/api/runtime-sites');
    if (after.active_site !== site || after.active_revision !== rev)
      throw new Error('Activation คืน success แต่ Runtime Identity ยังไม่ตรง: ตรวจ Journal/Activation Report');
    state.inventory = after;
    state.plan = null;
    refillSites(site);
    refillRevisions(rev);
    message(`Activation สำเร็จ: ${site} / ${rev} (ยืนยันจาก Runtime Inventory)`, 'success');
  }
  async function editActive() {
    if (!(await authenticated())) return;
    const site = state.site, rev = state.revision;
    const current = await request('/api/runtime-sites');
    if (current.active_site !== site || current.active_revision !== rev)
      throw new Error('อนุญาตให้แก้ Working Copy ของ Active Site/Revision ปัจจุบันเท่านั้น');
    const record = current.sites?.find(s => s.site_id === site);
    if (!record) throw new Error('ไม่พบ Active Site ใน Inventory');
    const working = record.working_copy || {};
    if (working.exists && working.parent_revision && working.parent_revision !== rev)
      throw new Error('Working Copy ผูกกับ Revision เก่า — ต้องตรวจ Conflict ก่อน');
    if (!working.exists) {
      if (working.candidate_exists) throw new Error('มี Candidate เดิมอยู่ แต่ Working Copy ไม่ Active: ให้ตรวจ Legacy UI ก่อน');
      if (!window.confirm(`สร้าง Working Copy จาก ${site}/${rev} เพื่อแก้ไข?\nRuntime จริงยังไม่เปลี่ยน`)) return;
      await request(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/working-copy`, 'POST', {overwrite: false});
    }
    window.location.assign(`/setup-wizard?mode=existing&site=${esc(site)}`);
  }
  async function setupNew() {
    if (!(await authenticated())) return;
    const site = state.site;
    const inventory = await request('/api/runtime-sites');
    const record = inventory.sites?.find(s => s.site_id === site);
    if (!record || record.active || record.revisions?.length || ['UNKNOWN','UNREGISTERED'].includes(String(record.lifecycle).toUpperCase()))
      throw new Error('สำหรับ Site ใหม่ที่ยังไม่มี Revision เท่านั้น');
    window.location.assign(`/setup-wizard?mode=existing&site=${esc(site)}`);
  }
  async function deleteInactive() {
    if (!(await authenticated())) return;
    const site = state.site;
    const inventory = await request('/api/runtime-sites');
    const record = inventory.sites?.find(s => s.site_id === site);
    if (!record || inventory.active_site === site || record.active) throw new Error('ห้ามลบ Active Site');
    const preview = await request(`/api/runtime-sites/${esc(site)}/delete-preview`);
    if (preview.site_id !== site || !preview.deletable) throw new Error(`Delete ถูกบล็อก: ${preview.blocked_reason || 'ไม่ผ่านเงื่อนไข'}`);
    const warning = (preview.warnings || []).join('\n');
    if (!window.confirm(`ลบ Site ${site} โดยย้ายไป Trash?\nRevision: ${preview.revision_count}\n${warning}`)) return;
    if (window.prompt(`พิมพ์ Site ID เพื่อยืนยันการย้ายไป Trash:\n${site}`) !== site) return;
    const fresh = await request('/api/runtime-sites');
    if (fresh.active_site === site || !fresh.sites?.some(s => s.site_id === site))
      throw new Error('Site เปลี่ยนสถานะระหว่างยืนยัน: ยกเลิก');
    const freshPreview = await request(`/api/runtime-sites/${esc(site)}/delete-preview`);
    if (!freshPreview.deletable || freshPreview.site_id !== site) throw new Error('Delete Preview เปลี่ยนสถานะ: ยกเลิก');
    const result = await request(`/api/runtime-sites/${esc(site)}`, 'DELETE', {confirm_value: site});
    if (result.ok !== true) throw new Error('Delete API ไม่ยืนยันผลสำเร็จ');
    state.site = '';
    await refresh();
    message(`ย้าย ${site} ไป Trash แล้ว — ตรวจ Audit หากต้องการกู้ข้อมูล`, 'success');
  }
  function openCreate() {
    const legacy = $('sfw26-legacy');
    if (legacy) legacy.open = true;
    const expert = $('sf-full-expert');
    if (expert) expert.open = true;
    const create = $('rsm-new-site');
    if (create) { create.click(); create.scrollIntoView({behavior:'smooth', block:'center'}); }
    else message('ใช้ปุ่ม + New Site ใน Site Manager เดิม (เครื่องมือขั้นสูง)', 'warn');
  }
  function mount() {
    const host = $('runtime-site-manager');
    if (!host || $('sfw26')) return Boolean($('sfw26'));
    const panel = document.createElement('section');
    panel.id = 'sfw26'; panel.className = 'rsm-panel';
    panel.innerHTML = `
      <header class="sfw26-head"><div><h2>Site Runtime Workbench <small>v2.6</small></h2>
      <p>เลือก Site / Revision · ตรวจความพร้อม · สลับ Runtime · แก้ไข Active Site · ลบ Inactive Site</p></div>
      <button id="sfw26-refresh" type="button">รีเฟรช</button></header>
      <div class="sfw26-current"><span>RUNTIME ปัจจุบัน</span><strong id="sfw26-active">Loading...</strong><span id="sfw26-count"></span></div>
      <div class="sfw26-grid">
        <label>Site ที่ต้องการจัดการ<select id="sfw26-site"></select></label>
        <label>Revision สำหรับ Activate<select id="sfw26-revision"></select></label>
      </div>
      <div class="sfw26-meta">
        <div><span>Mode</span><strong id="sfw26-mode">—</strong></div>
        <div><span>Lifecycle</span><strong id="sfw26-lifecycle">—</strong></div>
        <div><span>Working Copy</span><strong id="sfw26-working">—</strong></div>
      </div>
      <p id="sfw26-revision-status" class="sfw26-sub"></p><p id="sfw26-site-hint" class="sfw26-hint"></p>
      <p id="sfw26-warning" class="sfw26-warning"></p>
      <div class="sfw26-controls">
        <button id="sfw26-new" type="button">+ สร้าง Site</button>
        <button id="sfw26-setup" type="button">ตั้งค่า Site ใหม่</button>
        <button id="sfw26-edit" type="button">แก้ Active Working Copy</button>
        <button id="sfw26-delete" type="button" class="sfw26-danger">ลบ Inactive Site</button>
      </div>
      <div class="sfw26-plan"><div><h3>Activation Readiness</h3>
        <p id="sfw26-plan-summary">ยังไม่ได้ตรวจ Activation Plan สำหรับรายการที่เลือก</p></div>
        <button id="sfw26-plan" type="button">ตรวจ Plan (Read-only)</button>
        <button id="sfw26-activate" type="button" class="sfw26-primary" disabled>Activate Runtime</button>
      </div>
      <pre id="sfw26-plan-details" aria-live="polite"></pre>
      <p class="sfw26-notice" id="sfw26-message" role="status" aria-live="polite">กรุณา Unlock Manager ก่อนใช้งาน</p>
      <details id="sfw26-legacy"><summary>เครื่องมือเดิม / Advanced Tools (ยังคงใช้งานได้)</summary></details>`;
    host.insertBefore(panel, host.firstElementChild);
    const simple = $('sf-simple');
    if (simple) $('sfw26-legacy').append(simple);
    $('sfw26-site').addEventListener('change', e => {
      state.site = e.target.value; refillRevisions(); summary();
    });
    $('sfw26-revision').addEventListener('change', e => {
      state.revision = e.target.value; invalidatePlan(); summary();
    });
    const actions = {
      'sfw26-refresh': refresh,
      'sfw26-plan': checkPlan,
      'sfw26-activate': activate,
      'sfw26-edit': editActive,
      'sfw26-setup': setupNew,
      'sfw26-delete': deleteInactive,
      'sfw26-new': openCreate
    };
    for (const [id, fn] of Object.entries(actions)) {
      $(id).addEventListener('click', () => runAction(fn));
    }
    $('rsm-unlock')?.addEventListener('click', () => setTimeout(() => runAction(refresh), 500));
    refresh().catch(err => message(String(err.message || err), 'warn'));
    return true;
  }
  function boot() {
    let attempts = 0;
    const handle = setInterval(() => { if (mount() || ++attempts >= 100) clearInterval(handle); }, 150);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
