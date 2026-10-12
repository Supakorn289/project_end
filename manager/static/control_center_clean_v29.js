/* Smart Fire Control Center UX v2.9 — consolidated control center (legacy lazy-loaded).
   Backend and immutable revision lifecycle remain authoritative. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const enc = encodeURIComponent;
  const state = {inventory:null, site:'', revision:'', plan:null, csrf:'', busy:false, generation:0};
  const site = () => state.inventory?.sites?.find(s => s.site_id === state.site);
  const rev = () => site()?.revisions?.find(r => r.revision_id === state.revision);
  const active = () => state.inventory?.active_site === state.site;
  const current = () => active() && state.inventory?.active_revision === state.revision;
  const isFirstSetup = s => !!s && !s.active && (!s.revisions || !s.revisions.length)
    && !['UNKNOWN','UNREGISTERED'].includes(String(s.lifecycle || '').toUpperCase());
  function node(tag, cls, text) {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (text !== undefined) element.textContent = String(text ?? '—');
    return element;
  }
  const value = (id, v) => { if ($(id)) $(id).textContent = String(v ?? '—'); };
  const disable = (id, v) => {if ($(id)) $(id).disabled = Boolean(v);};
  function info(text, type='info') { const m = $('sf29-message'); if (m) {m.textContent=String(text);m.dataset.kind=type;} }
  function resetPlan() {
    state.plan = null;
    value('sf29-readiness','ตรวจความพร้อมของ Revision ก่อนสลับ Runtime');
    value('sf29-plan-result','');
    updateActions();
  }
  async function api(path, method='GET', payload) {
    const headers = {'Accept':'application/json'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      // Login is the only unauthenticated write operation supported here.
      if (path !== '/api/auth/login') {
        if (!state.csrf) throw new Error('ต้องปลดล็อก Manager ก่อน');
        headers['X-CSRF-Token'] = state.csrf;
      }
    }
    const res = await fetch(path, {method,credentials:'same-origin',cache:'no-store',headers,
      body:payload === undefined ? undefined : JSON.stringify(payload)});
    let data;
    try { data = await res.json(); }
    catch {throw new Error(`API ตอบข้อมูลไม่ถูกต้อง (HTTP ${res.status})`);}
    if (!res.ok || data?.ok === false) throw new Error(String(data?.reason || data?.error || `HTTP ${res.status}`));
    return data;
  }
  async function session() {
    const r = await api('/api/auth/session');
    state.csrf = r.authenticated && typeof r.csrf === 'string' ? r.csrf : '';
    $('sf29-login').hidden = !!state.csrf;
    value('sf29-auth-label', state.csrf ? 'ปลดล็อกแล้ว' : 'ล็อกอยู่');
    updateActions();
    return !!state.csrf;
  }
  async function login() {
    const input = $('sf29-token');
    const token = input.value.trim();
    if (!token) throw new Error('กรุณากรอก Manager Token');
    await api('/api/auth/login','POST',{token});
    input.value = '';
    await refresh();
  }
  function fillRevisions(requested='') {
    const box = $('sf29-revision');
    box.replaceChildren();
    const revisions = site()?.revisions || [];
    for (const r of revisions) {
      const suffix = r.active ? ' · ใช้งานอยู่' : '';
      box.add(new Option(`${r.revision_id} · ${r.status || 'ไม่ทราบสถานะ'}${suffix}`,r.revision_id));
    }
    if (!revisions.length) box.add(new Option('ยังไม่มี Revision',''));
    state.revision = revisions.find(r=>r.revision_id===requested)?.revision_id ||
      revisions.find(r=>r.active)?.revision_id || revisions[0]?.revision_id || '';
    box.value = state.revision;
    resetPlan();
  }
  function fillSites(requested='') {
    const box = $('sf29-site');box.replaceChildren();
    const inventory = state.inventory;
    for (const s of inventory.sites || []) {
      const stateText = s.active ? 'ใช้งานอยู่' : s.revisions?.length ? 'มี Revision' : 'ยังตั้งค่าไม่ครบ';
      box.add(new Option(`${s.display_name || s.site_id} · ${stateText}`,s.site_id));
    }
    if (!box.options.length) box.add(new Option('ไม่มีไซต์',''));
    const target = (inventory.sites||[]).some(s=>s.site_id===requested) ? requested :
      inventory.active_site || inventory.sites?.[0]?.site_id || '';
    state.site = target;box.value = target;
    fillRevisions();
    render();
  }
  function status(s) {
    if (!s) return ['ยังไม่มีไซต์','none'];
    if (s.active) return ['กำลังใช้งาน','active'];
    if (s.revisions?.length) return ['ยังไม่ใช้งาน · ตรวจ Plan ก่อนสลับ','candidate'];
    return ['ต้องตั้งค่าให้ครบ','setup'];
  }
  function render() {
    const s=site(), r=rev(), w=s?.working_copy || {}, [label,kind]=status(s);
    value('sf29-current-site',state.inventory?.active_site || 'ไม่มีข้อมูล');
    value('sf29-current-revision',state.inventory?.active_revision || '—');
    value('sf29-sitecount',`${state.inventory?.sites?.length || 0} ไซต์`);
    value('sf29-selected-name',s?.display_name || s?.site_id || 'ยังไม่ได้เลือก');
    value('sf29-selected-id',s?.site_id || '—');
    value('sf29-selected-status',label);
    $('sf29-selected-status').dataset.kind=kind;
    value('sf29-mode',s?.mode || '—');
    value('sf29-draft',w.exists ? `มี Working Copy ${w.state || ''}` : 'ยังไม่มี Working Copy');
    value('sf29-tip', !s ? 'กรุณาสร้างไซต์เพื่อเริ่มต้น' :
      s.active ? 'แก้ไขไซต์นี้ใน Setup Wizard เดิม การบันทึกต้องผ่าน Working Copy และ Verify ก่อนมีผลจริง' :
      isFirstSetup(s) ? 'ไซต์ยังไม่สมบูรณ์ ใช้ Setup Wizard เดิมเพื่อตั้งค่า Capture, Calibration และ Verification' :
      'ไซต์นี้ยังไม่ได้ใช้งาน สามารถตรวจ Activation Plan และเปลี่ยน Runtime เมื่อผ่านเกณฑ์');
    const warnings = (s?.warnings || []).slice(0,3).map(String);
    const warning = $('sf29-warnings'); warning.replaceChildren();
    warnings.forEach(w => warning.append(node('p','sf29-warning-line',w)));
    warning.hidden = !warnings.length;
    const hasRevision = !!r;
    $('sf29-revision-field').hidden = !hasRevision;
    $('sf29-readiness-area').hidden = !hasRevision;
    const main = $('sf29-open-setup');
    main.textContent = s?.active ? 'แก้ไข / ปรับเทียบไซต์นี้' : isFirstSetup(s) ? 'ตั้งค่าไซต์นี้ให้ครบ' : 'ดูรายละเอียดไซต์';
    // Completed inactive sites are read-only through this main flow.
    main.disabled = state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s));
    value('sf29-mode-label',hasRevision ? (r.status || 'UNKNOWN') : 'ยังไม่มี Revision');
    updateActions();
  }
  function updateActions() {
    const s=site(),hasRev=!!rev();
    const isCurrent = current();
    const ready=!!state.plan && state.plan.site === state.site && state.plan.revision === state.revision &&
      state.plan.data.activatable === true && Date.now() - state.plan.checked < 120000;
    disable('sf29-refresh', state.busy);
    disable('sf29-site',state.busy);
    disable('sf29-revision',state.busy);
    disable('sf29-check',state.busy || !state.csrf || !hasRev);
    disable('sf29-activate',state.busy || !state.csrf || isCurrent || !ready);
    disable('sf29-delete',state.busy || !state.csrf || !s || s.active);
    disable('sf29-open-setup',state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s)));
    disable('sf29-new',state.busy);
  }
  async function refresh() {
    const gen=++state.generation;
    await session();
    if (!state.csrf) { info('ปลดล็อก Manager ก่อนดูรายการไซต์','warn'); return; }
    const priorSite=state.site, priorRevision=state.revision;
    const inventory=await api('/api/runtime-sites');
    if (gen !== state.generation) return;
    if (inventory.ok !== true || !Array.isArray(inventory.sites)) throw new Error('รูปแบบ Site Inventory ไม่ถูกต้อง');
    state.inventory=inventory;
    fillSites(priorSite);
    if (state.site===priorSite) {fillRevisions(priorRevision);render();}
    info('โหลดข้อมูลล่าสุดแล้ว ยังไม่ได้เปลี่ยน Runtime','success');
  }
  function chooseSite(e) { state.site=e.target.value;fillRevisions();render(); }
  function chooseRevision(e) {state.revision=e.target.value;resetPlan();render();}
  async function check() {
    const s=state.site,r=state.revision;
    if (!s || !r) throw new Error('กรุณาเลือกไซต์และ Revision');
    const plan=await api(`/api/activation/${enc(s)}/${enc(r)}/plan`);
    if (plan.site_id !== s || plan.revision_id !== r) throw new Error('IDENTITY_MISMATCH: Plan ไม่ตรงกับที่เลือก');
    if (state.site!==s || state.revision!==r) throw new Error('มีการเปลี่ยนตัวเลือก กรุณาตรวจใหม่');
    state.plan={site:s,revision:r,checked:Date.now(),data:plan};
    const result=plan.activatable===true ? 'ผ่าน Plan · พร้อมเปลี่ยน Runtime (ไม่ใช่ Production Certification)' : 'ไม่ผ่าน Plan · ต้องแก้ใน Setup Wizard/Verification';
    value('sf29-readiness',result);
    const details=[];
    if (plan.safety_warning) details.push(String(plan.safety_warning));
    if (Array.isArray(plan.blockers)) details.push(...plan.blockers.map(String));
    if (plan.error) details.push(String(plan.error));
    value('sf29-plan-result',details.join('\n'));
    info(plan.activatable ? 'Plan ผ่าน ยังไม่มีการสลับ Runtime' : 'Plan ไม่ผ่าน ยังไม่อนุญาตให้ Activate',plan.activatable?'success':'warn');
    updateActions();
  }
  async function activate() {
    const s=state.site,r=state.revision;
    if (!state.plan || state.plan.site!==s || state.plan.revision!==r ||
        state.plan.data.activatable!==true || Date.now()-state.plan.checked>120000) throw new Error('Plan ยังไม่ผ่านหรือหมดอายุ');
    const inventory=await api('/api/runtime-sites');
    if (inventory.active_site===s && inventory.active_revision===r) throw new Error('Revision นี้ใช้งานอยู่แล้ว');
    if (!inventory.sites?.find(x=>x.site_id===s)?.revisions?.some(x=>x.revision_id===r)) throw new Error('Revision ไม่อยู่ใน Inventory');
    const newPlan=await api(`/api/activation/${enc(s)}/${enc(r)}/plan`);
    if (newPlan.site_id!==s || newPlan.revision_id!==r || newPlan.activatable!==true) throw new Error('Activation Plan ล่าสุดไม่ผ่าน');
    if (state.plan.data.candidate_digest && state.plan.data.candidate_digest!==newPlan.candidate_digest) throw new Error('Revision มีการเปลี่ยนแปลง');
    if (state.site!==s || state.revision!==r) throw new Error('ตัวเลือกเปลี่ยนระหว่างตรวจ Plan');
    if (!confirm(`เปลี่ยน Runtime ไปที่\n${s}\n${r}\n\nการ Activate จะหยุด Detection ชั่วคราวและ Restart ผ่าน Activation Engine เดิม`)) return;
    if (prompt(`พิมพ์ Site ID/Revision ID เพื่อยืนยัน:\n${s}/${r}`)!==`${s}/${r}`) return;
    if (state.site!==s || state.revision!==r) throw new Error('ตัวเลือกเปลี่ยนระหว่างยืนยัน');
    info('กำลัง Activate ผ่าน Backend — Detection อาจหยุดชั่วคราว','warn');
    const answer=await api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}/activate`,'POST',
      {confirm_site_id:s,confirm_revision_id:r});
    if (answer.ok !== true) throw new Error('Activation ไม่ยืนยันผลสำเร็จ');
    const after=await api('/api/runtime-sites');
    if (after.active_site!==s || after.active_revision!==r) throw new Error('Activation ตอบ Success แต่ Identity ไม่ตรง: ตรวจ Journal ก่อนทำต่อ');
    state.inventory=after;state.plan=null;fillSites(s);fillRevisions(r);render();
    info('สลับ Runtime สำเร็จและยืนยัน Identity จาก Backend แล้ว','success');
  }
  async function openSetup() {
    const s=state.site;
    const inventory=await api('/api/runtime-sites');
    const record=inventory.sites?.find(x=>x.site_id===s);
    if (!record) throw new Error('Site เปลี่ยนหรือถูกลบ กรุณารีเฟรช');
    if (inventory.active_site===s) {
      const r=inventory.active_revision;
      if (!r) throw new Error('ไม่พบ Active Revision');
      const w=record.working_copy || {};
      if (w.exists && w.parent_revision && w.parent_revision!==r) throw new Error('Working Copy ผูก Revision เดิม กรุณาตรวจ Conflict');
      if (!w.exists) {
        if (w.candidate_exists) throw new Error('พบ Candidate เดิมที่ยังไม่ Active Working Copy ต้องตรวจด้วยเครื่องมือเดิมก่อน');
        if (!confirm(`สร้าง Working Copy จาก Revision ปัจจุบันเพื่อปรับเทียบ?\n${s}/${r}\n\nRuntime จริงจะยังไม่เปลี่ยน`)) return;
        await api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}/working-copy`,'POST',{overwrite:false});
      }
    } else if (!isFirstSetup(record)) {
      throw new Error('Site นี้ยังไม่ใช่ Runtime ปัจจุบัน ต้อง Activate ก่อนจึงจะแก้ไขได้');
    }
    location.assign(`/setup-wizard?mode=existing&site=${enc(s)}`);
  }
  async function removeSite() {
    const s=state.site;
    const before=await api('/api/runtime-sites');
    if (before.active_site===s || before.sites?.find(x=>x.site_id===s)?.active) throw new Error('ห้ามลบ Active Site');
    const preview=await api(`/api/runtime-sites/${enc(s)}/delete-preview`);
    if (preview.site_id!==s || preview.deletable!==true) throw new Error(String(preview.blocked_reason || 'Delete Preview บล็อก')); 
    const warnings=(preview.warnings||[]).join('\n');
    if (!confirm(`ย้ายไซต์ ${s} ไป Trash?\nจำนวน Revision: ${preview.revision_count ?? '?'}\n${warnings}`)) return;
    if (prompt(`พิมพ์ Site ID เพื่อยืนยันการลบ\n${s}`)!==s) return;
    const next=await api('/api/runtime-sites');
    const checkAgain=await api(`/api/runtime-sites/${enc(s)}/delete-preview`);
    if (state.site!==s || next.active_site===s || !next.sites?.some(x=>x.site_id===s) || checkAgain.deletable!==true || checkAgain.site_id!==s)
      throw new Error('สถานะ Site เปลี่ยนระหว่างยืนยัน — ยกเลิก');
    const result=await api(`/api/runtime-sites/${enc(s)}`,'DELETE',{confirm_value:s});
    if (result.ok!==true) throw new Error('Delete API ไม่ยืนยันผล');
    state.site=''; await refresh(); info('ย้ายไซต์ไป Trash แล้ว','success');
  }
  async function perform(fn) {
    if (state.busy) return;
    state.busy=true;updateActions();
    try {await fn();} catch(e) {info(`ไม่สำเร็จ: ${e.message || e}`,'error');}
    finally {state.busy=false;updateActions();}
  }
  function navigateCalibration() {
    const nav=document.querySelector('.nav[data-page="calibration"]');
    if (nav) nav.click();
  }
  function buildUI() {
    const panel=node('section','sf29-root');panel.id='sf29-root';
    panel.innerHTML=`
      <div class="sf29-hero">
        <div><p class="sf29-eyebrow">SITE MANAGEMENT</p><h2>ไซต์และการตั้งค่า</h2>
        <p>เลือกไซต์ที่ต้องการ แล้วใช้ Setup Wizard เดิมสำหรับกล้องและการปรับเทียบ</p></div>
        <button type="button" class="sf29-btn sf29-primary" id="sf29-new">+ สร้างไซต์ใหม่</button>
      </div>
      <div class="sf29-live" role="status"><div><span class="sf29-kicker">RUNTIME ที่กำลังใช้งาน</span>
        <strong id="sf29-current-site">กำลังโหลด...</strong>
        <small id="sf29-current-revision">—</small></div><span class="sf29-live-pill" id="sf29-sitecount">—</span></div>
      <div id="sf29-login" class="sf29-login" hidden><label for="sf29-token">ปลดล็อก Manager เพื่อจัดการ Site</label>
        <div class="sf29-inline"><input id="sf29-token" type="password" autocomplete="current-password" placeholder="Manager Token">
          <button type="button" class="sf29-btn sf29-primary" id="sf29-login-btn">ปลดล็อก</button></div></div>
      <div class="sf29-card">
        <div class="sf29-card-head"><div><span class="sf29-step">1</span><strong>เลือกไซต์</strong></div>
          <button type="button" class="sf29-textbtn" id="sf29-refresh">รีเฟรช</button></div>
        <label class="sf29-field"><span>ไซต์ที่ต้องการจัดการ</span><select id="sf29-site" aria-label="เลือกไซต์"></select></label>
        <div class="sf29-info"><div class="sf29-site-title"><strong id="sf29-selected-name">—</strong><span id="sf29-selected-status" class="sf29-status">—</span></div>
          <p id="sf29-selected-id" class="sf29-id">—</p><div class="sf29-tags"><span id="sf29-mode">—</span><span id="sf29-draft">—</span></div>
          <p class="sf29-guidance" id="sf29-tip">—</p><div id="sf29-warnings" class="sf29-warnings" hidden></div></div>
        <div class="sf29-actions"><button type="button" class="sf29-btn sf29-primary" id="sf29-open-setup" disabled>เปิด Setup Wizard</button>
          <button type="button" class="sf29-btn sf29-danger" id="sf29-delete" disabled>ลบไซต์ที่ไม่ได้ใช้งาน</button></div>
      </div>
      <div class="sf29-card" id="sf29-readiness-area">
        <div class="sf29-card-head"><div><span class="sf29-step">2</span><strong>ตรวจและเลือก Runtime</strong></div></div>
        <label class="sf29-field" id="sf29-revision-field"><span>Revision ที่ต้องการใช้</span><select id="sf29-revision"></select></label>
        <div class="sf29-readiness"><strong id="sf29-readiness">—</strong><small id="sf29-mode-label">—</small>
          <pre id="sf29-plan-result" aria-live="polite"></pre></div>
        <div class="sf29-actions"><button type="button" class="sf29-btn" id="sf29-check" disabled>ตรวจความพร้อม</button>
          <button type="button" class="sf29-btn sf29-primary" id="sf29-activate" disabled>ใช้เป็น Runtime</button></div>
      </div>
      <div class="sf29-minilinks"><button type="button" class="sf29-textbtn" id="sf29-calibration">ดูสถานะ Calibration</button>
        <a href="/settings">ตั้งค่าระบบ / การแจ้งเตือน</a><span id="sf29-auth-label">—</span></div>
      <p id="sf29-message" class="sf29-message" role="status" aria-live="polite">กำลังตรวจ Manager...</p>`;
    return panel;
  }
  function simplifyNavigation() {
    const labels={
      overview:['ภาพรวม','สถานะระบบตรวจจับและ Runtime'],
      sites:['จัดการไซต์','เลือกไซต์ ตั้งค่า และสลับ Runtime'],
      tests:['ทดสอบ','เครื่องมือทดสอบและผลตรวจ'],
      system:['ระบบ','บริการและสถานะเครื่อง'],
      setup:['ตั้งค่าไซต์','ใช้ Setup Wizard เพื่อแก้ไขค่า'],
      calibration:['สถานะ Calibration','ข้อมูล Calibration ที่ระบบใช้อยู่']
    };
    document.querySelectorAll('.nav').forEach(nav=>{
      const page=nav.dataset.page;
      if (labels[page] && !['setup','calibration'].includes(page)) nav.textContent=labels[page][0];
      if (page==='setup' || page==='calibration') nav.classList.add('sf29-subnav');
      nav.addEventListener('click',()=>{
        if (labels[page]) {
          value('page-title',labels[page][0]);
          value('page-subtitle',labels[page][1]);
        }
      });
      if (nav.classList.contains('active') && labels[page]) {
        value('page-title',labels[page][0]);
        value('page-subtitle',labels[page][1]);
      }
    });
    const settings=document.querySelector('.nav-link[href="/settings"]');
    if (settings) settings.textContent='ตั้งค่า';
    const page=$('page-calibration');
    if (page && !$('sf29-back-sites')) {
      const back=node('button','sf29-btn','← กลับไปจัดการไซต์');
      back.id='sf29-back-sites';back.type='button';back.style.marginBottom='14px';
      back.addEventListener('click',()=>document.querySelector('.nav[data-page="sites"]')?.click());
      page.prepend(back);
    }
  }
  function revealOverviewDetails() {
    const page = $('page-overview');
    if (!page || $('sf29-overview-detail')) return;
    const panels=[...page.children].filter(n=>n.classList.contains('panel'));
    if (!panels.length) return;
    const details=document.createElement('details');
    details.id='sf29-overview-detail';
    details.className='sf29-overview-detail';
    const summary=document.createElement('summary');
    summary.textContent='รายละเอียดการตรวจจับและความพร้อมการติดตั้ง';
    details.append(summary);
    for(const panel of panels) details.append(panel);
    page.append(details);
  }
  const legacyStyles=[
    '/static/runtime_site_manager.css',
    '/static/runtime_site_manager_v1_1.css',
    '/static/runtime_site_manager_v2.css',
    '/static/site_manager_simple_v2_1.css',
    '/static/site_workbench_v26.css?v=2.6.0',
    '/static/active_calibration_v27.css?v=2.7.0'
  ];
  const legacyScripts=[
    '/static/runtime_site_manager.js',
    '/static/runtime_site_manager_v1_1.js',
    '/static/runtime_site_manager_v2.js?v=2.1.2b',
    '/static/site_manager_simple_v2_1.js?v=2.1.2b',
    '/static/active_camera_connection_v25.js?v=2.5a',
    '/static/site_notifications_v22.js?v=2.2.1',
    '/static/phase45_active_editor.js?v=2.3a',
    '/static/site_workbench_v26.js?v=2.6.0',
    '/static/active_calibration_v27.js?v=2.7.0'
  ];
  function waitFor(id, maxMs=10000) {
    return new Promise((resolve,reject)=>{
      const start=Date.now();
      function check(){
        if($(id)) return resolve($(id));
        if(Date.now()-start>maxMs) return reject(new Error('เครื่องมือเดิมไม่พร้อม: '+id));
        setTimeout(check,100);
      }
      check();
    });
  }
  function addScript(src) {
    return new Promise((resolve,reject)=>{
      const element=document.createElement('script');
      element.src=src;element.async=false;
      element.onload=resolve;
      element.onerror=()=>reject(new Error('ไม่สามารถโหลด '+src));
      document.body.append(element);
    });
  }
  async function loadExpertTools() {
    const target=$('sf29-expert-target');
    if(!target || target.dataset.status==='ready' || target.dataset.status==='loading') return;
    target.dataset.status='loading';
    target.textContent='กำลังโหลดเครื่องมือเฉพาะทางที่ยังต้องรักษาความเข้ากันได้...';
    try {
      for(const url of legacyStyles){
        if(document.querySelector('link[href="'+url+'"]')) continue;
        const link=document.createElement('link');link.rel='stylesheet';link.href=url;document.head.append(link);
      }
      for(const [i,url] of legacyScripts.entries()) {
        await addScript(url);
        if(i===0) {
          const root=await waitFor('runtime-site-manager');
          target.replaceChildren(root);
        }
        if(i===3) await waitFor('sf-simple');
        if(i===7) await waitFor('sfw26');
        if(i===8) await waitFor('sf27');
      }
      target.dataset.status='ready';
      if(!target.children.length) throw new Error('เครื่องมือเดิมโหลดแต่ไม่มี UI');
    } catch(error) {
      target.dataset.status='error';
      const msg=document.createElement('p');msg.className='sf29-error';
      msg.textContent='เปิดเครื่องมือเฉพาะทางไม่สำเร็จ: '+error.message+
        ' — โปรดตรวจ Browser Console; ห้ามบันทึกข้อมูลก่อนตรวจสอบ';
      target.prepend(msg);
    }
  }
  function mount() {
    if ($('sf29-root')) return true;
    const page=$('page-sites');
    if (!page || !document.querySelector('.nav[data-page="sites"]')) return false;
    page.prepend(buildUI());
    const adv=node('details','sf29-advanced'); adv.id='sf29-advanced';
    const title=node('summary','', 'เครื่องมือเฉพาะทาง / Compatibility (ใช้เมื่อจำเป็น)');
    const intro=node('p','sf29-expert-note','การจัดการทั่วไปใช้เมนูด้านบน · ฟังก์ชันเฉพาะจากระบบเดิมยังเข้าใช้งานได้ที่นี่ โดยจะโหลดเฉพาะเมื่อเปิดส่วนนี้');
    const target=node('div','sf29-expert-target');target.id='sf29-expert-target';
    adv.append(title,intro,target);page.append(adv);
    adv.addEventListener('toggle',()=>{if(adv.open)loadExpertTools();});
    simplifyNavigation();
    revealOverviewDetails();
    $('sf29-login-btn').addEventListener('click',()=>perform(login));
    $('sf29-token').addEventListener('keydown',e=>{if(e.key==='Enter')perform(login);});
    $('sf29-refresh').addEventListener('click',()=>perform(refresh));
    $('sf29-site').addEventListener('change',chooseSite);
    $('sf29-revision').addEventListener('change',chooseRevision);
    $('sf29-check').addEventListener('click',()=>perform(check));
    $('sf29-activate').addEventListener('click',()=>perform(activate));
    $('sf29-open-setup').addEventListener('click',()=>perform(openSetup));
    $('sf29-delete').addEventListener('click',()=>perform(removeSite));
    $('sf29-new').addEventListener('click',()=>{location.assign('/setup-wizard?mode=new');});
    $('sf29-calibration').addEventListener('click',navigateCalibration);
    refresh().catch(e=>info('โหลดข้อมูลไซต์ไม่ได้: '+e.message,'error'));
    return true;
  }
  function boot(){let attempts=0;const timer=setInterval(()=>{if(mount() || ++attempts>100) clearInterval(timer);},150);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
