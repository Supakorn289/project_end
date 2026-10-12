(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let csrf = null;

  function info(message) {
    const box = $('rsm-v2-status');
    if (box) box.textContent = typeof message === 'string' ? message : JSON.stringify(message, null, 2);
  }

  async function api(path, method = 'GET', body) {
    const headers = {'Content-Type':'application/json'};
    if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
    const response = await fetch(path, {
      method, headers, cache: 'no-store',
      credentials: 'same-origin', body: body == null ? undefined : JSON.stringify(body)
    });
    let value;
    try { value = await response.json(); }
    catch { value = {ok:false, error: `HTTP ${response.status}`}; }
    return {response, value};
  }

  async function auth() {
    const {value} = await api('/api/auth/session');
    csrf = value.authenticated ? value.csrf : null;
    return Boolean(value.authenticated);
  }

  function site() {
    return $('rsm-switch-site')?.value || '';
  }
  function revision() {
    return $('rsm-switch-revision')?.value || '';
  }

  function siteRecord() {
    const id = site();
    return [...document.querySelectorAll('[data-rsm-edit-site], [data-edit-site]')]
      .find(el => (el.dataset.rsmEditSite || el.dataset.editSite) === id)
      ?.closest('.rsm-site');
  }

  function activeSite() {
    const label = $('rsm-current-runtime')?.textContent || '';
    return label.trim().startsWith(site() + ' →');
  }

  function selectedReady() {
    const text = $('rsm-switch-status')?.textContent || '';
    return text.includes('candidate_ready: true');
  }

  function update() {
    const active = activeSite();
    const selection = Boolean(site() && revision());
    const recovered = $('rsm-v2-recover');
    const setup = $('rsm-v2-setup');
    const begin = $('rsm-v2-begin');
    if (recovered) recovered.disabled = !selection || active;
    if (begin) begin.disabled = !selection || !active;
    if (setup) setup.disabled = !site();
    const hint = $('rsm-v2-hint');
    if (hint) hint.textContent = active
      ? 'Active Site: เริ่ม Edit Working Copy ก่อนเข้า Full Calibration Setup'
      : 'Inactive Site: อ่านข้อมูลได้; แก้ไขได้เฉพาะ Legacy Recovery หรือ Site ใหม่ที่ยังไม่มี Revision';
    // Make inactive Site edit actions visibly read-only.
    document.querySelectorAll('.rsm-site').forEach(card => {
      const isActive = card.classList.contains('active');
      card.querySelectorAll('[data-rsm-edit-site],[data-edit-site],[data-rsm-edit-runtime],[data-edit-runtime]')
        .forEach(b => { b.disabled = !isActive; });
    });
    const selSite = $('rsm-switch-edit-site');
    const selRuntime = $('rsm-switch-edit-runtime');
    if (selSite) selSite.disabled = !active;
    if (selRuntime) selRuntime.disabled = !active;

  }

  async function checkPlan() {
    if (!(await auth())) { info('Unlock Manager ก่อนตรวจ Activation Plan'); return; }
    // The simple selector is authoritative for the read-only Activation Plan.
    // Older expert selectors can retain a different previous selection.
    const selectedSite = $('sf-simple-site')?.value || site();
    const selectedRev = $('sf-simple-revision')?.value || revision();
    if (!selectedSite || !selectedRev) { info('เลือก Site และ Revision ก่อน'); return; }
    const path = `/api/activation/${encodeURIComponent(selectedSite)}/${encodeURIComponent(selectedRev)}/plan`;
    const {response, value} = await api(path);
    if (!response.ok) { info({error:value.error || 'PLAN_REQUEST_FAILED', selectedSite, selectedRev}); return; }
    if (value.site_id !== selectedSite || value.revision_id !== selectedRev) {
      info({error:'ACTIVATION_PLAN_IDENTITY_MISMATCH', selectedSite, selectedRev}); return;
    }
    if (($('sf-simple-site')?.value || site()) !== selectedSite ||
        ($('sf-simple-revision')?.value || revision()) !== selectedRev) {
      info('รายการที่เลือกเปลี่ยนระหว่างตรวจแผน กรุณาลองใหม่'); return;
    }
    info({operation:'ACTIVATION_PLAN', site_id:selectedSite, revision_id:selectedRev, ...value,
      instruction: value.activatable ? 'READY — ตรวจ physical configuration ก่อน Activate' : 'BLOCKED — ดู error และ blockers ใน Final Verification'});
    if ($('rsm-output')) $('rsm-output').textContent = JSON.stringify(value, null, 2);
  }

  function clickEdit() {
    const s = site(), r = revision();
    const b = [...document.querySelectorAll('[data-rsm-edit-runtime],[data-edit-runtime]')]
      .find(x => (x.dataset.rsmEditRuntime || x.dataset.editRuntime) === `${s}|${r}`);
    if (!b) { info('ไม่พบ Revision ต้นทางที่แก้ไขได้'); return; }
    b.click();
  }

  async function startActiveEdit() {
    if (!(await auth())) { info('Unlock Manager ก่อน'); return; }
    if (!activeSite()) { info('แก้ Runtime ได้เฉพาะ Active Site'); return; }
    clickEdit();
    info('เมื่อเริ่ม Working Copy สำเร็จแล้ว กด Open Full Setup Wizard เพื่อแก้ Calibration ทุกหมวด');
  }

  async function openSetup() {
    if (!(await auth())) { info('Unlock Manager ก่อน'); return; }
    if (!site()) { info('เลือก Site ก่อน'); return; }
    // The authenticated inventory is authoritative; the server independently gates writes.
    const inventory = await api('/api/runtime-sites');
    const selected = (inventory.value.sites || []).find(x => x.site_id === site());
    const working = selected?.working_copy || {};
    const initial = (selected?.revisions || []).length === 0;
    if (!working.exists && !initial) {
      info('ต้องเปิด Working Copy ของ Active Site หรือทำ Legacy Recovery ก่อนแก้ Setup'); return;
    }
    location.assign(`/setup-wizard?mode=existing&site=${encodeURIComponent(site())}`);
  }

  async function previewRecovery() {
    if (!(await auth())) { info('Unlock Manager ก่อน'); return; }
    if (!site() || !revision()) { info('เลือก Legacy Revision ก่อน'); return; }
    const s = site(), r = revision();
    const url = `/api/runtime-sites/${encodeURIComponent(s)}/revision/${encodeURIComponent(r)}/recovery-preview`;
    const {response, value} = await api(url);
    info({operation:'LEGACY_RECOVERY_PREVIEW', ...value});
    if (!response.ok || !value.recoverable) return;
    if (confirm('Recover Legacy Calibration จาก Revision ที่เลือก?\n\n' +
      'Camera/Telegram credentials จะไม่ถูกคัดลอก\n' +
      'Candidate เดิมจะถูก Archive ถ้ามี\n' +
      'ต้องเป็นกล้อง เลนส์ มุมติดตั้ง และ PTZ Presets เดิม\n\n' +
      'OK = ยืนยันตรวจสอบเงื่อนไขความเสี่ยง และไปขั้นพิมพ์ Site ID')) {
      const typed = prompt(`พิมพ์ Site ID เพื่อยืนยัน:\n${s}`);
      if (typed !== s) { info('ยกเลิก Recovery: Site ID ไม่ตรง'); return; }
      const result = await api(
        `/api/runtime-sites/${encodeURIComponent(s)}/revision/${encodeURIComponent(r)}/recover`, 'POST',
        {confirm_site_id:s, confirm_revision_id:r, same_hardware_confirmed:true,
         maintenance_acknowledged:true, archive_existing:Boolean(value.candidate_exists)}
      );
      info(result.value);
      if (result.response.ok) {
        if (confirm('สร้าง Recovery Working Copy สำเร็จ\nเปิด Setup Wizard เพื่อกรอก Camera Credentials และตรวจการคาลิเบรตต่อหรือไม่?')) {
          location.assign(`/setup-wizard?mode=existing&site=${encodeURIComponent(s)}`);
        }
      }
    }
  }

  function init() {
    const host = $('runtime-site-manager');
    if (!host || $('rsm-v2-tools')) return false;
    const panel = document.createElement('section');
    panel.id = 'rsm-v2-tools';
    panel.className = 'rsm-panel';
    panel.innerHTML = `<h3>Site Lifecycle & Full Calibration</h3>
      <p class="rsm-sub">แก้เฉพาะ Active Site ผ่าน Working Copy; Legacy Recovery เป็นการกู้ข้อมูลเก่าแบบมีการตรวจสอบ</p>
      <div class="rsm-actions">
      <button type="button" class="rsm-btn primary" id="rsm-v2-begin">Start/Edit Active Working Copy</button>
      <button type="button" class="rsm-btn" id="rsm-v2-setup">Open Full Setup Wizard</button>
      <button type="button" class="rsm-btn" id="rsm-v2-recover">Preview / Recover Legacy Calibration</button>
      <button type="button" class="rsm-btn" id="rsm-v2-plan">Show Detailed Activation Plan</button>
      </div><div class="rsm-warning" id="rsm-v2-hint"></div>
      <pre id="rsm-v2-status" class="rsm-switch-status">Select a site and revision</pre>`;
    const selector = $('rsm-runtime-switcher');
    if (selector) selector.insertAdjacentElement('afterend', panel);
    else host.prepend(panel);
    $('rsm-v2-begin').onclick = () => startActiveEdit().catch(e=>info(String(e)));
    $('rsm-v2-setup').onclick = () => openSetup().catch(e=>info(String(e)));
    $('rsm-v2-recover').onclick = () => previewRecovery().catch(e=>info(String(e)));
    $('rsm-v2-plan').onclick = () => checkPlan().catch(e=>info(String(e)));
    $('rsm-switch-site')?.addEventListener('change',()=>setTimeout(update,0));
    $('rsm-switch-revision')?.addEventListener('change',()=>setTimeout(update,0));
    // Recovery/active mode UI receives updates even if v1.1 selector is rebuilt.
    setInterval(update, 1500);
    update();
    return true;
  }
  async function start() {
    for (let n=0;n<60;n++) {
      if (init()) return;
      await new Promise(resolve => setTimeout(resolve,100));
    }
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
