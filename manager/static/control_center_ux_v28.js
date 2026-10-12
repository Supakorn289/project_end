/* Smart Fire Control Center UX v2.8 — presentation-only consolidation.
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
  function info(text, type='info') { const m = $('sf28-message'); if (m) {m.textContent=String(text);m.dataset.kind=type;} }
  function resetPlan() {
    state.plan = null;
    value('sf28-readiness','ตรวจความพร้อมของ Revision ก่อนสลับ Runtime');
    value('sf28-plan-result','');
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
    $('sf28-login').hidden = !!state.csrf;
    value('sf28-auth-label', state.csrf ? 'ปลดล็อกแล้ว' : 'ล็อกอยู่');
    updateActions();
    return !!state.csrf;
  }
  async function login() {
    const input = $('sf28-token');
    const token = input.value.trim();
    if (!token) throw new Error('กรุณากรอก Manager Token');
    await api('/api/auth/login','POST',{token});
    input.value = '';
    await refresh();
  }
  function fillRevisions(requested='') {
    const box = $('sf28-revision');
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
    const box = $('sf28-site');box.replaceChildren();
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
    value('sf28-current-site',state.inventory?.active_site || 'ไม่มีข้อมูล');
    value('sf28-current-revision',state.inventory?.active_revision || '—');
    value('sf28-sitecount',`${state.inventory?.sites?.length || 0} ไซต์`);
    value('sf28-selected-name',s?.display_name || s?.site_id || 'ยังไม่ได้เลือก');
    value('sf28-selected-id',s?.site_id || '—');
    value('sf28-selected-status',label);
    $('sf28-selected-status').dataset.kind=kind;
    value('sf28-mode',s?.mode || '—');
    value('sf28-draft',w.exists ? `มี Working Copy ${w.state || ''}` : 'ยังไม่มี Working Copy');
    value('sf28-tip', !s ? 'กรุณาสร้างไซต์เพื่อเริ่มต้น' :
      s.active ? 'แก้ไขไซต์นี้ใน Setup Wizard เดิม การบันทึกต้องผ่าน Working Copy และ Verify ก่อนมีผลจริง' :
      isFirstSetup(s) ? 'ไซต์ยังไม่สมบูรณ์ ใช้ Setup Wizard เดิมเพื่อตั้งค่า Capture, Calibration และ Verification' :
      'ไซต์นี้ยังไม่ได้ใช้งาน สามารถตรวจ Activation Plan และเปลี่ยน Runtime เมื่อผ่านเกณฑ์');
    const warnings = (s?.warnings || []).slice(0,3).map(String);
    const warning = $('sf28-warnings'); warning.replaceChildren();
    warnings.forEach(w => warning.append(node('p','sf28-warning-line',w)));
    warning.hidden = !warnings.length;
    const hasRevision = !!r;
    $('sf28-revision-field').hidden = !hasRevision;
    $('sf28-readiness-area').hidden = !hasRevision;
    const main = $('sf28-open-setup');
    main.textContent = s?.active ? 'แก้ไข / ปรับเทียบไซต์นี้' : isFirstSetup(s) ? 'ตั้งค่าไซต์นี้ให้ครบ' : 'ดูรายละเอียดไซต์';
    // Completed inactive sites are read-only through this main flow.
    main.disabled = state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s));
    value('sf28-mode-label',hasRevision ? (r.status || 'UNKNOWN') : 'ยังไม่มี Revision');
    updateActions();
  }
  function updateActions() {
    const s=site(),hasRev=!!rev();
    const isCurrent = current();
    const ready=!!state.plan && state.plan.site === state.site && state.plan.revision === state.revision &&
      state.plan.data.activatable === true && Date.now() - state.plan.checked < 120000;
    disable('sf28-refresh', state.busy);
    disable('sf28-site',state.busy);
    disable('sf28-revision',state.busy);
    disable('sf28-check',state.busy || !state.csrf || !hasRev);
    disable('sf28-activate',state.busy || !state.csrf || isCurrent || !ready);
    disable('sf28-delete',state.busy || !state.csrf || !s || s.active);
    disable('sf28-open-setup',state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s)));
    disable('sf28-new',state.busy);
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
    value('sf28-readiness',result);
    const details=[];
    if (plan.safety_warning) details.push(String(plan.safety_warning));
    if (Array.isArray(plan.blockers)) details.push(...plan.blockers.map(String));
    if (plan.error) details.push(String(plan.error));
    value('sf28-plan-result',details.join('\n'));
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
    const panel=node('section','sf28-root');panel.id='sf28-root';
    panel.innerHTML=`
      <div class="sf28-hero">
        <div><p class="sf28-eyebrow">SITE MANAGEMENT</p><h2>ไซต์และการตั้งค่า</h2>
        <p>เลือกไซต์ที่ต้องการ แล้วใช้ Setup Wizard เดิมสำหรับกล้องและการปรับเทียบ</p></div>
        <button type="button" class="sf28-btn sf28-primary" id="sf28-new">+ สร้างไซต์ใหม่</button>
      </div>
      <div class="sf28-live" role="status"><div><span class="sf28-kicker">RUNTIME ที่กำลังใช้งาน</span>
        <strong id="sf28-current-site">กำลังโหลด...</strong>
        <small id="sf28-current-revision">—</small></div><span class="sf28-live-pill" id="sf28-sitecount">—</span></div>
      <div id="sf28-login" class="sf28-login" hidden><label for="sf28-token">ปลดล็อก Manager เพื่อจัดการ Site</label>
        <div class="sf28-inline"><input id="sf28-token" type="password" autocomplete="current-password" placeholder="Manager Token">
          <button type="button" class="sf28-btn sf28-primary" id="sf28-login-btn">ปลดล็อก</button></div></div>
      <div class="sf28-card">
        <div class="sf28-card-head"><div><span class="sf28-step">1</span><strong>เลือกไซต์</strong></div>
          <button type="button" class="sf28-textbtn" id="sf28-refresh">รีเฟรช</button></div>
        <label class="sf28-field"><span>ไซต์ที่ต้องการจัดการ</span><select id="sf28-site" aria-label="เลือกไซต์"></select></label>
        <div class="sf28-info"><div class="sf28-site-title"><strong id="sf28-selected-name">—</strong><span id="sf28-selected-status" class="sf28-status">—</span></div>
          <p id="sf28-selected-id" class="sf28-id">—</p><div class="sf28-tags"><span id="sf28-mode">—</span><span id="sf28-draft">—</span></div>
          <p class="sf28-guidance" id="sf28-tip">—</p><div id="sf28-warnings" class="sf28-warnings" hidden></div></div>
        <div class="sf28-actions"><button type="button" class="sf28-btn sf28-primary" id="sf28-open-setup" disabled>เปิด Setup Wizard</button>
          <button type="button" class="sf28-btn sf28-danger" id="sf28-delete" disabled>ลบไซต์ที่ไม่ได้ใช้งาน</button></div>
      </div>
      <div class="sf28-card" id="sf28-readiness-area">
        <div class="sf28-card-head"><div><span class="sf28-step">2</span><strong>ตรวจและเลือก Runtime</strong></div></div>
        <label class="sf28-field" id="sf28-revision-field"><span>Revision ที่ต้องการใช้</span><select id="sf28-revision"></select></label>
        <div class="sf28-readiness"><strong id="sf28-readiness">—</strong><small id="sf28-mode-label">—</small>
          <pre id="sf28-plan-result" aria-live="polite"></pre></div>
        <div class="sf28-actions"><button type="button" class="sf28-btn" id="sf28-check" disabled>ตรวจความพร้อม</button>
          <button type="button" class="sf28-btn sf28-primary" id="sf28-activate" disabled>ใช้เป็น Runtime</button></div>
      </div>
      <div class="sf28-minilinks"><button type="button" class="sf28-textbtn" id="sf28-calibration">ดูสถานะ Calibration</button>
        <a href="/settings">ตั้งค่าระบบ / การแจ้งเตือน</a><span id="sf28-auth-label">—</span></div>
      <p id="sf28-message" class="sf28-message" role="status" aria-live="polite">กำลังตรวจ Manager...</p>`;
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
      if (page==='setup' || page==='calibration') nav.classList.add('sf28-subnav');
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
    if (page && !$('sf28-back-sites')) {
      const back=node('button','sf28-btn','← กลับไปจัดการไซต์');
      back.id='sf28-back-sites';back.type='button';back.style.marginBottom='14px';
      back.addEventListener('click',()=>document.querySelector('.nav[data-page="sites"]')?.click());
      page.prepend(back);
    }
  }
  function mount() {
    if ($('sf28-root')) return true;
    const page=$('page-sites'); const host=$('runtime-site-manager');
    if (!page || !host || !$('sfw26') || !$('sf27')) return false;
    const old=node('details','sf28-advanced');old.id='sf28-advanced';
    const summary=node('summary','', 'เครื่องมือเดิม / Advanced (เปิดเมื่อจำเป็นเท่านั้น)');
    old.append(summary);
    [...page.children].forEach(child=>old.append(child));
    page.append(buildUI(),old);
    // The former Site panels and editors are preserved under closed details, not destroyed.
    simplifyNavigation();
    $('sf28-login-btn').addEventListener('click',()=>perform(login));
    $('sf28-token').addEventListener('keydown',e=>{if(e.key==='Enter')perform(login);});
    $('sf28-refresh').addEventListener('click',()=>perform(refresh));
    $('sf28-site').addEventListener('change',chooseSite);
    $('sf28-revision').addEventListener('change',chooseRevision);
    $('sf28-check').addEventListener('click',()=>perform(check));
    $('sf28-activate').addEventListener('click',()=>perform(activate));
    $('sf28-open-setup').addEventListener('click',()=>perform(openSetup));
    $('sf28-delete').addEventListener('click',()=>perform(removeSite));
    $('sf28-new').addEventListener('click',()=>{location.assign('/setup-wizard?mode=new');});
    $('sf28-calibration').addEventListener('click',navigateCalibration);
    refresh().catch(e=>info('โหลดข้อมูลไซต์ไม่ได้: '+e.message,'error'));
    return true;
  }
  function boot(){let attempts=0;const timer=setInterval(()=>{if(mount() || ++attempts>100) clearInterval(timer);},150);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
