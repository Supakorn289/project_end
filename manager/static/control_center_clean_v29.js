/* Smart Fire Control Center UX v2.9 — consolidated control center (legacy lazy-loaded).
   Backend and immutable revision lifecycle remain authoritative. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const enc = encodeURIComponent;
  const state = {inventory:null, site:'', revision:'', plan:null, csrf:'', busy:false, generation:0, deleteSitePreview:null, deleteRevisionPreview:null, previewRequest:0, trash:[], trashLoading:false};
  const site = () => state.inventory?.sites?.find(s => s.site_id === state.site);
  const rev = () => site()?.revisions?.find(r => r.revision_id === state.revision);
  const active = () => state.inventory?.active_site === state.site;
  const current = () => active() && state.inventory?.active_revision === state.revision;
  const isFirstSetup = s => !!s && !s.active && (!s.revisions || !s.revisions.length)
    && !['UNKNOWN','UNREGISTERED'].includes(String(s.lifecycle || '').toUpperCase());
  const plainReason = {
    revision_not_found:'ไม่พบเวอร์ชันนี้แล้ว',
    active_revision:'เวอร์ชันนี้กำลังใช้ตรวจจับอยู่',
    runtime_pointers_uncertain:'ยังตรวจสอบไฟล์ที่ระบบใช้งานอยู่ได้ไม่ครบ',
    working_copy_parent:'ชุดแก้ไขปัจจุบันสร้างจากเวอร์ชันนี้',
    published_revision:'เวอร์ชันนี้เป็นชุดที่บันทึกเผยแพร่ไว้',
    wizard_draft_parent:'ข้อมูลตั้งค่าที่ยังแก้อยู่เชื่อมกับเวอร์ชันนี้',
    wizard_latest_revision:'ประวัติการบันทึกล่าสุดยังอ้างถึงเวอร์ชันนี้',
    historical_landmark_draft:'จุดอ้างอิงภาพ (Landmark) ที่กำลังแก้เชื่อมกับเวอร์ชันนี้',
    revision_reference_check_failed:'ตรวจสอบความเชื่อมโยงของข้อมูลไม่สำเร็จ จึงไม่อนุญาตให้ลบ',
    unsafe_revision_path:'พบตำแหน่งไฟล์ที่ต้องให้ผู้ดูแลตรวจสอบ',
    deployment_requires_privileged_cleanup:'ไฟล์ส่วนใช้งานมีสิทธิ์ป้องกันอยู่ ต้องให้ผู้ดูแลจัดการสิทธิ์อย่างปลอดภัย',
    active_site:'พื้นที่นี้กำลังใช้งานตรวจจับอยู่',
    site_registry_or_wizard_invalid:'ตรวจสอบประวัติพื้นที่ติดตั้งได้ไม่ครบ',
    site_registry_unavailable:'ไม่สามารถอ่านทะเบียนพื้นที่ติดตั้ง',
    revision_integrity_check_failed:'ตรวจสอบความสมบูรณ์ของเวอร์ชันไม่สำเร็จ',
    site_integrity_check_failed:'ตรวจสอบข้อมูลพื้นที่ติดตั้งไม่สำเร็จ',
    site_path_unsafe:'ตำแหน่งไฟล์ของพื้นที่นี้ไม่ปลอดภัย ต้องให้ผู้ดูแลตรวจสอบ',
    site_registry_active_revision_id:'ทะเบียนพื้นที่ยังระบุว่าเวอร์ชันนี้ใช้งานอยู่',
    site_registry_last_published_revision:'ทะเบียนพื้นที่ยังอ้างถึงเวอร์ชันที่เผยแพร่',
    site_registry_last_revision_id:'ทะเบียนพื้นที่ยังอ้างถึงเวอร์ชันนี้',
  };
  function reasons(p) {
    const codes=Array.isArray(p?.blocked_reasons) ? p.blocked_reasons :
      p?.blocked_reason ? [p.blocked_reason] : [];
    return [...new Set(codes)].map(c=>plainReason[c] || `ต้องตรวจสอบเพิ่มเติม (${c})`);
  }
  function resetDeletePreviews() {
    ++state.previewRequest;
    state.deleteSitePreview=null;
    state.deleteRevisionPreview=null;
    value('sf29-site-delete-hint','กำลังตรวจสอบว่าสามารถลบพื้นที่นี้ได้หรือไม่');
    value('sf29-delete-revision-hint','กำลังตรวจสอบความปลอดภัยก่อนลบเวอร์ชัน');
    updateActions();
  }
  async function loadDeletePreviews() {
    const request=++state.previewRequest, s=state.site,r=state.revision;
    if (!state.csrf || !s) return;
    const items=await Promise.allSettled([
      api(`/api/runtime-sites/${enc(s)}/delete-preview`),
      r ? api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}/delete-preview`) : Promise.resolve(null)
    ]);
    if (request!==state.previewRequest || s!==state.site || r!==state.revision) return;
    state.deleteSitePreview=items[0].status==='fulfilled' ? items[0].value : null;
    state.deleteRevisionPreview=items[1].status==='fulfilled' ? items[1].value : null;
    const sp=state.deleteSitePreview, rp=state.deleteRevisionPreview;
    value('sf29-site-delete-hint', items[0].status!=='fulfilled' ? 'ตรวจสอบการลบพื้นที่ไม่สำเร็จ — กรุณาลองใหม่' :
      sp?.deletable ? 'ลบได้: ระบบจะย้ายข้อมูลและเวอร์ชันทั้งหมดไปถังเก็บสำรอง' :
      `ยังลบพื้นที่นี้ไม่ได้: ${reasons(sp).join('; ') || 'ระบบไม่อนุญาต'}`);
    value('sf29-delete-revision-hint', !r ? 'ยังไม่มีเวอร์ชันที่บันทึกไว้' :
      items[1].status!=='fulfilled' ? 'ตรวจสอบการลบเวอร์ชันไม่สำเร็จ — กรุณาลองใหม่' :
      rp?.deletable ? 'ลบได้: เวอร์ชันนี้ไม่ถูกใช้งานหรืออ้างอิง และจะย้ายไปถังเก็บสำรอง' :
      `ยังลบเวอร์ชันนี้ไม่ได้: ${reasons(rp).join('; ') || 'ระบบไม่อนุญาต'}`);
    updateActions();
  }
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
    value('sf29-readiness','ตรวจความพร้อมของเวอร์ชันก่อนเลือกใช้งาน');
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
      box.add(new Option(`${r.revision_id} · ${r.active ? 'กำลังใช้งาน' : r.status === 'VALIDATED_CANDIDATE' ? 'ตรวจแล้ว' : 'บันทึกไว้'}${suffix}`,r.revision_id));
    }
    if (!revisions.length) box.add(new Option('ยังไม่มีเวอร์ชันที่บันทึกไว้',''));
    state.revision = revisions.find(r=>r.revision_id===requested)?.revision_id ||
      revisions.find(r=>r.active)?.revision_id || revisions[0]?.revision_id || '';
    box.value = state.revision;
    resetPlan();
  }
  function fillSites(requested='') {
    const box = $('sf29-site');box.replaceChildren();
    const inventory = state.inventory;
    for (const s of inventory.sites || []) {
      const stateText = s.active ? 'ใช้งานอยู่' : s.revisions?.length ? 'มีเวอร์ชันที่บันทึกไว้' : 'ยังตั้งค่าไม่ครบ';
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
    value('sf29-sitecount',`${state.inventory?.sites?.length || 0} พื้นที่`);
    value('sf29-selected-name',s?.display_name || s?.site_id || 'ยังไม่ได้เลือก');
    value('sf29-selected-id',s?.site_id || '—');
    value('sf29-selected-status',label);
    $('sf29-selected-status').dataset.kind=kind;
    value('sf29-mode',s?.mode==='LAB' ? 'ทดสอบ (LAB)' : s?.mode==='PRODUCTION' ? 'ใช้งานจริง (Production)' : s?.mode || '—');
    value('sf29-draft',w.state === 'PUBLISHED' ? `บันทึกเป็นเวอร์ชันแล้ว · ${w.published_revision || 'เวอร์ชันล่าสุด'}` :
      w.exists ? `มีชุดแก้ไข (Draft) · ${w.state || ''}` : 'ยังไม่มีชุดแก้ไข (Draft)');
    value('sf29-tip', !s ? 'กรุณาเพิ่มพื้นที่ติดตั้งเพื่อเริ่มต้น' :
      s.active && w.state === 'PUBLISHED' ? 'มีเวอร์ชันที่บันทึกแล้วรอใช้งาน คุณสามารถตรวจความพร้อมเพื่อเลือกใช้งาน หรือเปิดชุดแก้ไขเดิมหลังระบบตรวจความถูกต้อง' :
      s.active ? 'ตั้งค่ากล้องและปรับเทียบได้ในหน้าตั้งค่าเดิม การแก้ไขจะยังไม่มีผลกับระบบตรวจจับจนกว่าจะบันทึกและนำเวอร์ชันใหม่มาใช้' :
      isFirstSetup(s) ? 'พื้นที่นี้ยังตั้งค่าไม่ครบ ให้เข้าหน้าตั้งค่าเพื่อบันทึกภาพ ปรับเทียบ และตรวจสอบ' :
      w.offline_only ? 'ชุดแก้ไขออฟไลน์: แก้การเชื่อมต่อกล้องได้ แต่ห้ามทดสอบกล้อง/จับภาพ/บันทึกเวอร์ชันจนกว่าจะตรวจอุปกรณ์อย่างปลอดภัย' :
      'พื้นที่นี้ยังไม่ได้ใช้งาน สามารถเตรียมสำเนาการตั้งค่ากล้องออฟไลน์ได้ โดยไม่รบกวนระบบตรวจจับปัจจุบัน');
    const warnings = (s?.warnings || []).slice(0,3).map(String);
    const warning = $('sf29-warnings'); warning.replaceChildren();
    warnings.forEach(w => warning.append(node('p','sf29-warning-line',w)));
    warning.hidden = !warnings.length;
    const hasRevision = !!r;
    $('sf29-revision-field').hidden = !hasRevision;
    $('sf29-readiness-area').hidden = !hasRevision;
    const main = $('sf29-open-setup');
    main.textContent = s?.active ? 'แก้ไขพื้นที่และปรับเทียบ' : isFirstSetup(s) ? 'ตั้งค่าพื้นที่นี้' :
      w.offline_only ? 'ดูชุดแก้ไขกล้องออฟไลน์' : 'สร้างชุดแก้ไขกล้องออฟไลน์';
    main.disabled = state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s) && !state.revision);
    const offline = $('sf29-offline-camera');
    if (offline) {
      offline.hidden = !s || s.active || !w.offline_only;
      value('sf29-offline-warning', w.offline_only ?
        'แก้เฉพาะค่าการเชื่อมต่อกล้องออฟไลน์ · PTZ/Intrinsics เดิมเป็นหลักฐานอ่านอย่างเดียว ต้องทดสอบใหม่ในช่วงบำรุงรักษา' : '');
    }
    value('sf29-mode-label',hasRevision ? (r.active ? 'กำลังใช้งาน' : r.status==='VALIDATED_CANDIDATE' ? 'ผ่านการตรวจขั้นต้น' : 'รอตรวจสถานะ') : 'ยังไม่มีเวอร์ชันที่บันทึกไว้');
    updateActions();
  }
  function updateActions() {
    const s=site(),hasRev=!!rev();
    const isCurrent = current();
    const ready=!!state.plan && state.plan.site === state.site && state.plan.revision === state.revision &&
      state.plan.data.activatable === true && Date.now() - state.plan.checked < 120000;
    disable('sf29-refresh', state.busy);
    disable('sf29-rename', state.busy || !state.csrf || !s || !s.updated_at);
    disable('sf29-site',state.busy);
    disable('sf29-revision',state.busy);
    disable('sf29-check',state.busy || !state.csrf || !hasRev);
    disable('sf29-activate',state.busy || !state.csrf || isCurrent || !ready);
    disable('sf29-delete',state.busy || !state.csrf || !s || s.active || state.deleteSitePreview?.deletable!==true);
    disable('sf29-delete-revision',state.busy || !state.csrf || !hasRev || state.deleteRevisionPreview?.deletable!==true);
    disable('sf29-open-setup',state.busy || !state.csrf || !s || (!s.active && !isFirstSetup(s) && !state.revision));
    disable('sf29-review-save',state.busy || !state.csrf || !s?.working_copy?.offline_only || s.active || !state.offlineReview);
    disable('sf29-review-load',state.busy || !state.csrf || !s?.working_copy?.offline_only || s.active);
    disable('sf29-offline-save',state.busy || !state.csrf || !s || s.active || !s.working_copy?.offline_only);
    disable('sf29-offline-discard',state.busy || !state.csrf || !s || s.active || !s.working_copy?.offline_only);
    disable('sf29-new',state.busy);
  }
  // Read only. A running service does NOT prove autonomous operation after reboot.
  async function checkBootReadiness() {
    const target=$('sf29-autostart');
    if (!target) return;
    try {
      const system=await api('/api/system');
      const services=system && system.services;
      if (!services || typeof services !== 'object') throw new Error('service inventory unavailable');
      const detection=services.detection || {};
      const manager=services.manager || {};
      const running=detection.active === 'active';
      const automatic=detection.enabled === 'enabled';
      const managing=manager.active === 'active';
      const status=running && automatic && managing
        ? 'Detection ทำงานอยู่และตั้งให้เริ่มพร้อมเครื่อง'
        : `ตรวจสอบบริการ: Detection ${detection.active || 'ไม่ทราบ'} / เริ่มพร้อมเครื่อง ${detection.enabled || 'ไม่ทราบ'} / Manager ${manager.active || 'ไม่ทราบ'}`;
      target.textContent=status+' · ยังต้องทดสอบหลังรีบูตจริง';
      target.dataset.kind=running && automatic && managing?'success':'warn';
    } catch (e) {
      target.textContent='ยังตรวจสถานะเริ่มเองไม่ได้ — ดูเมนูระบบ · '+String(e.message || e);
      target.dataset.kind='warn';
    }
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
    resetDeletePreviews();
    await loadDeletePreviews();
    await checkBootReadiness();
    info('โหลดข้อมูลล่าสุดแล้ว ยังไม่ได้เปลี่ยนระบบที่กำลังใช้งาน','success');
  }
  async function loadTrash() {
    if (!state.csrf) {value('sf29-trash-hint','กรุณาปลดล็อก Manager ก่อน');return;}
    if (state.trashLoading) return;
    state.trashLoading=true;
    disable('sf29-trash-restore',true);
    value('sf29-trash-hint','กำลังตรวจรายการในถังเก็บสำรอง...');
    try {
      const data=await api('/api/runtime-sites/trash');
      if (!Array.isArray(data.items)) throw new Error('ข้อมูลรายการสำรองไม่ถูกต้อง');
      state.trash=data.items.filter(x=>x.restorable===true);
      const list=$('sf29-trash-select'); list.replaceChildren();
      for (const item of state.trash) {
        const kind=item.kind==='site'?'พื้นที่':'เวอร์ชัน';
        const label=`${kind} · ${item.site_id}${item.revision_id?' · '+item.revision_id:''} · ${item.archive_id}`;
        list.add(new Option(label,`${item.kind}|${item.site_id}|${item.archive_id}`));
      }
      if (!state.trash.length) list.add(new Option('ไม่มีรายการที่ตรวจผ่านและกู้คืนได้',''));
      value('sf29-trash-hint',state.trash.length ? `พบรายการที่กู้คืนได้ ${state.trash.length} รายการ · เลือกรายการและตรวจอีกครั้งก่อนกู้` : 'ไม่มีรายการที่กู้คืนได้โดยอัตโนมัติ (ข้อมูลเก่าที่ไม่มีหลักฐานต้องให้ผู้ดูแลตรวจ)');
      disable('sf29-trash-restore',!state.trash.length);
    } catch(e) {
      state.trash=[];
      $('sf29-trash-select').replaceChildren(new Option('โหลดรายการไม่สำเร็จ',''));
      value('sf29-trash-hint','ตรวจรายการสำรองไม่สำเร็จ: '+e.message);
    } finally {state.trashLoading=false;}
  }
  async function restoreTrash() {
    const raw=$('sf29-trash-select').value;
    const item=state.trash.find(x=>`${x.kind}|${x.site_id}|${x.archive_id}`===raw);
    if (!item || !state.csrf) throw new Error('กรุณาเลือกรายการที่สามารถกู้คืนได้');
    const url=`/api/runtime-sites/trash/${enc(item.kind)}/${enc(item.site_id)}/${enc(item.archive_id)}`;
    const preview=await api(url+'/restore-preview');
    if (preview.restorable!==true || preview.site_id!==item.site_id || preview.kind!==item.kind || preview.archive_id!==item.archive_id)
      throw new Error('รายการเปลี่ยนแล้ว กรุณาโหลดใหม่');
    const identity=item.kind==='site'?item.site_id:item.revision_id;
    if (!identity || (item.kind==='revision' && preview.revision_id!==identity)) throw new Error('รหัสเวอร์ชันไม่ตรง');
    const kindText=item.kind==='site'?'พื้นที่ติดตั้ง':'เวอร์ชันที่บันทึกไว้';
    if(!confirm(`กู้คืน${kindText}?\n\nพื้นที่: ${item.site_id}\n${item.revision_id?'เวอร์ชัน: '+item.revision_id+'\n':''}ไฟล์ที่ตรวจ: ${preview.file_count}\n\nการกู้คืนไม่เปิดใช้งานเวอร์ชันนี้อัตโนมัติ`)) return;
    const typed=prompt(`พิมพ์รหัส${item.kind==='site'?'พื้นที่':'เวอร์ชัน'}ตามนี้เพื่อยืนยัน:\n${identity}`);
    if (typed!==identity) {info('ยกเลิก: รหัสที่พิมพ์ไม่ตรง','warn');return;}
    const newer=await api(url+'/restore-preview');
    if (newer.proof!==preview.proof || newer.restorable!==true) throw new Error('หลักฐานเปลี่ยน กรุณาตรวจอีกครั้ง');
    const result=await api(url+'/restore','POST',{confirm_value:identity,expected_proof:newer.proof});
    if (result.ok!==true || result.runtime_changed!==false) throw new Error('ผลลัพธ์การกู้คืนไม่ถูกต้อง');
    await refresh();
    await loadTrash();
    info(`กู้คืน${kindText}เรียบร้อยแล้ว โดยยังไม่เปิดใช้งานกับระบบตรวจจับ`,'success');
  }
  function chooseSite(e) { state.site=e.target.value;state.offlineDetail=null;state.offlineReview=null;fillRevisions();render();resetDeletePreviews();void loadDeletePreviews(); }
  function chooseRevision(e) {state.revision=e.target.value;resetPlan();render();resetDeletePreviews();void loadDeletePreviews();}
  async function check() {
    const s=state.site,r=state.revision;
    if (!s || !r) throw new Error('กรุณาเลือกไซต์และ Revision');
    const plan=await api(`/api/activation/${enc(s)}/${enc(r)}/plan`);
    if (plan.site_id !== s || plan.revision_id !== r) throw new Error('IDENTITY_MISMATCH: Plan ไม่ตรงกับที่เลือก');
    if (state.site!==s || state.revision!==r) throw new Error('มีการเปลี่ยนตัวเลือก กรุณาตรวจใหม่');
    state.plan={site:s,revision:r,checked:Date.now(),data:plan};
    const result=plan.activatable===true ? 'ผ่านการตรวจเบื้องต้น · สามารถเลือกใช้งานได้ (ยังไม่ใช่การรับรองความปลอดภัย)' : 'ยังไม่พร้อมใช้งาน · กรุณาตรวจและแก้การตั้งค่าก่อน';
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
    state.inventory=after;state.plan=null;fillSites(s);fillRevisions(r);render();resetDeletePreviews();await loadDeletePreviews();
    info('สลับ Runtime สำเร็จและยืนยัน Identity จาก Backend แล้ว','success');
  }
  async function loadOfflineCamera() {
    const s=state.site;
    if (!s || state.inventory?.active_site===s) throw new Error('ต้องเลือกพื้นที่ที่ไม่ได้ใช้งาน');
    const detail=await api(`/api/runtime-sites/${enc(s)}/working-copy`);
    if (state.site!==s || detail.site_id!==s || detail.offline_only!==true || !detail.camera_sha256)
      throw new Error('ชุดแก้ไขออฟไลน์เปลี่ยน กรุณาโหลดใหม่');
    const c=detail.camera || {};
    state.offlineDetail=detail;
    for(const [id,v] of Object.entries({
      'sf29-offline-ip':c.camera_ip||'',
      'sf29-offline-port':c.camera_port||'80',
      'sf29-offline-rtsp-port':c.rtsp_port||'554',
      'sf29-offline-path':c.rtsp_path||'/',
      'sf29-offline-user':'', 'sf29-offline-password':''
    })) $(id).value=String(v);
    value('sf29-offline-status','โหลดค่าการเชื่อมต่อสำเร็จ · ชื่อผู้ใช้และรหัสผ่านเดิมถูกเก็บไว้ ไม่แสดงข้อมูลลับ');
    await loadOfflineReview();
  }
  async function loadOfflineReview() {
    const s=state.site;
    if(!s || state.inventory?.active_site===s) throw new Error('ต้องเลือกชุดแก้ไขออฟไลน์ของไซต์ที่ไม่ได้ใช้งาน');
    const r=await api(`/api/runtime-sites/${enc(s)}/working-copy/calibration-review`);
    if(state.site!==s || r.site_id!==s || r.offline_only!==true) throw new Error('ข้อมูลไซต์เปลี่ยน กรุณาโหลดใหม่');
    state.offlineReview=r;
    value('sf29-review-evidence',`Intrinsics ${r.intrinsics_model_present?'มีโมเดล':'ไม่มีโมเดล'} · ภาพ Intrinsics ${r.intrinsics_captures} ภาพ · PTZ ${r.ptz_main_captures}/9 ภาพ · Rotation ${r.ptz_model_present?'มี':'ไม่มี'}`);
    value('sf29-review-status',r.review_current ? 'มีบันทึกการตรวจที่ตรงกับหลักฐานชุดนี้ · ยังต้องทดสอบฮาร์ดแวร์จริง' : 'ยังไม่บันทึกแผนตรวจ หรือหลักฐานเปลี่ยน · ต้องตรวจทานใหม่');
    $('sf29-review-intrinsics').value=r.review?.intrinsics||'recapture_required';
    $('sf29-review-ptz').value=r.review?.ptz||'recapture_required';
    $('sf29-review-notes').value=r.review?.notes||'';
  }
  async function saveOfflineReview() {
    const s=state.site,r=state.offlineReview;
    if(!r || r.site_id!==s || state.inventory?.active_site===s) throw new Error('กรุณาโหลดรายการหลักฐานก่อน');
    if(!confirm(`บันทึกแผนตรวจ Intrinsics/PTZ ของ ${s}?\nไม่แก้ภาพและไม่รับรองความพร้อมใช้งานจริง`))return;
    const ans=await api(`/api/runtime-sites/${enc(s)}/working-copy/calibration-review`,'PATCH',{
      confirm_site_id:s,expected_updated_at:r.expected_updated_at,
      camera_sha256:r.camera_sha256,evidence_sha256:r.evidence_sha256,review_sha256:r.review_sha256,
      intrinsics:$('sf29-review-intrinsics').value,ptz:$('sf29-review-ptz').value,
      notes:$('sf29-review-notes').value
    });
    if(ans.ok!==true || ans.runtime_changed!==false || ans.requires_hardware_commissioning!==true)
      throw new Error('Backend ไม่ยืนยันการบันทึกแบบปลอดภัย');
    await loadOfflineReview();
    info('บันทึกแผนตรวจหลักฐานแล้ว ไม่แก้ Calibration และยังต้องตรวจกล้อง/PTZ จริง','success');
  }
  async function discardOfflineCamera() {
    const s=state.site,d=state.offlineDetail;
    if(!d || d.site_id!==s || !d.offline_only || state.inventory?.active_site===s)
      throw new Error('กรุณาโหลดชุดแก้ไขออฟไลน์ล่าสุด');
    if(!confirm(`ยกเลิกชุดแก้ไขกล้องออฟไลน์ของ ${s}?\n\nระบบจะย้าย Candidate ของไซต์นี้ไปเก็บสำรอง ไม่ลบ Revision ต้นฉบับและไม่เปลี่ยน Runtime`))return;
    if(prompt(`พิมพ์รหัสพื้นที่ให้ตรงเพื่อยืนยันการยกเลิก:\n${s}`)!==s)return;
    const result=await api(`/api/runtime-sites/${enc(s)}/working-copy`,'DELETE',{
      expected_updated_at:d.expected_updated_at,confirm_site_id:s
    });
    if(result.ok!==true || result.site_id!==s || result.runtime_changed!==false || result.archived!==true)
      throw new Error('Backend ไม่ยืนยันการยกเลิกชุดแก้ไข');
    state.offlineDetail=null;state.offlineReview=null;
    await refresh();
    info('ยกเลิกชุดแก้ไขออฟไลน์แล้ว · เก็บ Candidate เดิมเป็นสำรองโดยไม่เปลี่ยน Runtime','success');
  }
  async function saveOfflineCamera() {
    const s=state.site,d=state.offlineDetail;
    if(!d || d.site_id!==s || !d.offline_only || state.inventory?.active_site===s)
      throw new Error('กรุณากดดูชุดแก้ไขออฟไลน์ก่อนบันทึก');
    const payload={expected_updated_at:d.expected_updated_at,expected_camera_sha256:d.camera_sha256,
      camera_ip:$('sf29-offline-ip').value.trim(),camera_port:$('sf29-offline-port').value.trim(),
      rtsp_port:$('sf29-offline-rtsp-port').value.trim(),rtsp_path:$('sf29-offline-path').value.trim()};
    const user=$('sf29-offline-user').value.trim(), password=$('sf29-offline-password').value;
    if(user) payload.camera_user=user;
    if(password) payload.camera_password=password;
    if(!confirm(`บันทึกค่าการเชื่อมต่อกล้องในชุดแก้ไขออฟไลน์ของ ${s}?\n\nยังไม่มีการทดสอบกล้องหรือเปลี่ยน Runtime`))return;
    const result=await api(`/api/runtime-sites/${enc(s)}/working-copy/camera`,'PATCH',payload);
    if(result.ok!==true || result.offline_only!==true || result.runtime_changed!==false)
      throw new Error('Backend ไม่ยืนยันการบันทึกแบบออฟไลน์');
    $('sf29-offline-password').value='';
    await refresh();
    await loadOfflineCamera();
    info(result.unchanged ? 'ข้อมูลเหมือนเดิม ไม่มีการเปลี่ยนแปลง' : 'บันทึกค่ากล้องออฟไลน์แล้ว · ต้องตรวจ Camera/PTZ/Intrinsics ใหม่ก่อนใช้งานจริง','success');
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
        if (w.candidate_exists) {
          const detail=await api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}`);
          const preview=detail.published_resume || {};
          if (preview.eligible!==true) throw new Error('Candidate ที่ Publish แล้วต้องตรวจเพิ่มเติม: '+String(preview.reason || 'ไม่เข้าเงื่อนไข Resume'));
          if (preview.site_id!==s || preview.active_revision!==r || preview.published_revision!==w.published_revision)
            throw new Error('Revision Lineage เปลี่ยน กรุณารีเฟรช');
          if (!confirm(`Resume Candidate ที่ Publish เป็น Draft ใหม่?\n\nActive: ${r}\nPublished: ${preview.published_revision}\nไฟล์ ${preview.candidate_file_count} รายการจะคงเดิมทุก byte รวม Settings\n\nRuntime ปัจจุบันจะไม่เปลี่ยน`)) return;
          if (prompt(`พิมพ์ Site ID/Active Revision เพื่อยืนยัน:\n${s}/${r}`)!==`${s}/${r}`) return;
          await api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}/working-copy`,'POST',{
            resume_published:true,confirm_site_id:s,confirm_revision_id:r,
            confirm_published_revision_id:preview.published_revision,
            expected_fingerprint:preview.expected_fingerprint
          });
          location.assign(`/setup-wizard?mode=existing&site=${enc(s)}`);
          return;
        }
        if (!confirm(`สร้าง Working Copy จาก Revision ปัจจุบันเพื่อปรับเทียบ?\n${s}/${r}\n\nRuntime จริงจะยังไม่เปลี่ยน`)) return;
        await api(`/api/runtime-sites/${enc(s)}/revision/${enc(r)}/working-copy`,'POST',{overwrite:false});
      }
    } else if (!isFirstSetup(record)) {
      if (record.working_copy?.offline_only) {
        await loadOfflineCamera();
        $('sf29-offline-camera').scrollIntoView({block:'nearest',behavior:'smooth'});
        return;
      }
      const selected=state.revision;
      const revItem=record.revisions?.find(v=>v.revision_id===selected);
      if (!revItem || revItem.source_exists!==true) throw new Error('ไม่พบ Revision ต้นทางที่ตรวจสอบได้');
      if (record.working_copy?.candidate_exists || record.working_copy?.state)
        throw new Error('พื้นที่นี้มี Candidate/ชุดแก้ไขเดิมอยู่ ระบบไม่เขียนทับ ให้ตรวจสอบก่อน');
      if (!record.updated_at) throw new Error('กรุณาโหลดทะเบียนพื้นที่ใหม่');
      if (!confirm(`สร้างชุดแก้ไขการเชื่อมต่อกล้องแบบออฟไลน์?\n\nพื้นที่: ${s}\nต้นทาง: ${selected}\n\nไม่จับภาพ ไม่ทดสอบกล้อง ไม่เปลี่ยน Runtime และไม่ทับ Candidate เดิม`)) return;
      const currentInv=await api('/api/runtime-sites');
      const latest=currentInv.sites?.find(v=>v.site_id===s);
      if (currentInv.active_site===s || !latest || latest.updated_at!==record.updated_at ||
          !latest.revisions?.some(v=>v.revision_id===selected) || latest.working_copy?.candidate_exists || latest.working_copy?.state)
        throw new Error('ข้อมูลพื้นที่เปลี่ยน กรุณารีเฟรชก่อนสร้างชุดแก้ไข');
      const result=await api(`/api/runtime-sites/${enc(s)}/revision/${enc(selected)}/working-copy`,'POST',{
        offline_only:true,overwrite:false,expected_updated_at:record.updated_at
      });
      if(result.ok!==true || result.offline_only!==true || result.runtime_changed!==false)
        throw new Error('Backend ไม่ยืนยันชุดแก้ไขออฟไลน์');
      await refresh();
      await loadOfflineCamera();
      info('สร้างชุดแก้ไขออฟไลน์สำเร็จ · ยังไม่เปิดใช้งานกับ Detection','success');
      return;
    }
    location.assign(`/setup-wizard?mode=existing&site=${enc(s)}`);
  }
  async function renameSite() {
    const original=site();
    if (!original || !original.site_id || !original.updated_at)
      throw new Error('ยังไม่มีข้อมูลรุ่นทะเบียนพื้นที่ กรุณาโหลดใหม่');
    const id=original.site_id;
    const oldName=original.display_name || id;
    const expectedStamp=original.updated_at;
    const answer=prompt('เปลี่ยนชื่อที่แสดงของพื้นที่นี้ (ไม่เปลี่ยนรหัสไซต์หรือค่ากล้อง):',oldName);
    if (answer===null) return;
    const name=answer.trim();
    if (!name || name.length>120 || /[\r\n]/.test(name)) throw new Error('ชื่อพื้นที่ต้องมี 1–120 ตัวอักษร และห้ามขึ้นบรรทัดใหม่');
    if (name===oldName) {info('ชื่อพื้นที่ยังเหมือนเดิม ไม่มีการแก้ข้อมูล','warn');return;}
    const baseUrl=`/api/runtime-sites/${enc(id)}`;
    const preview=await api(baseUrl+'/update-preview','POST',{display_name:name});
    if (preview.site_id!==id || preview.risk!=='LOW' ||
        !Array.isArray(preview.affected) || preview.affected.length ||
        !Array.isArray(preview.changed) || preview.changed.some(v=>v!=='display_name'))
      throw new Error('ระบบไม่ยืนยันว่าแก้เฉพาะชื่อพื้นที่ จึงยกเลิก');
    if (!confirm(`เปลี่ยนชื่อพื้นที่\n\n${oldName}\n→ ${name}\n\nรหัสพื้นที่และระบบตรวจจับจะไม่เปลี่ยน`)) return;
    const freshInventory=await api('/api/runtime-sites');
    const record=freshInventory.sites?.find(v=>v.site_id===id);
    if (state.site!==id || !record || record.updated_at!==expectedStamp ||
        (record.display_name||id)!==oldName)
      throw new Error('ข้อมูลพื้นที่ถูกแก้จากอีกหน้าต่าง กรุณาโหลดใหม่ก่อนบันทึก');
    const result=await api(baseUrl,'PATCH',{display_name:name,expected_updated_at:expectedStamp});
    if (result.ok!==true || result.site?.site_id!==id || result.site.display_name!==name ||
        result.runtime_changed!==false) throw new Error('Backend ตอบผลไม่ตรงกับการแก้ชื่อ กรุณาตรวจทะเบียนพื้นที่');
    await refresh();
    if (state.site!==id || site()?.display_name!==name)
      throw new Error('บันทึกแล้วแต่แสดงรายการล่าสุดไม่ตรง กรุณาโหลดข้อมูลใหม่');
    info('เปลี่ยนชื่อพื้นที่ที่แสดงสำเร็จ · รหัสไซต์และเวอร์ชันเดิมไม่เปลี่ยน','success');
  }
  async function removeRevision() {
    const s=state.site,r=state.revision;
    if (!s || !r) throw new Error('กรุณาเลือกพื้นที่และเวอร์ชัน');
    const before=await api('/api/runtime-sites');
    if (!before.sites?.find(x=>x.site_id===s)?.revisions?.some(x=>x.revision_id===r))
      throw new Error('ไม่พบเวอร์ชันที่เลือกแล้ว กรุณาโหลดข้อมูลใหม่');
    const url=`/api/runtime-sites/${enc(s)}/revision/${enc(r)}`;
    const p=await api(url+'/delete-preview');
    if (p.site_id!==s || p.revision_id!==r || p.deletable!==true)
      throw new Error('ยังลบเวอร์ชันนี้ไม่ได้: '+reasons(p).join('; '));
    if (!confirm(`ย้ายเวอร์ชันที่บันทึกไว้นี้ไปถังเก็บสำรอง?\n\nพื้นที่: ${s}\nเวอร์ชัน: ${r}\n\nการลบไม่เปลี่ยนระบบตรวจจับที่ทำงานอยู่`)) return;
    if (prompt(`พิมพ์รหัสเวอร์ชันนี้ให้ตรงทุกตัว เพื่อยืนยันการลบ\n${r}`)!==r) {info('ยกเลิก: รหัสเวอร์ชันไม่ตรง','warn');return;}
    const next=await api('/api/runtime-sites');
    const fresh=await api(url+'/delete-preview');
    if (state.site!==s || state.revision!==r ||
        !next.sites?.find(x=>x.site_id===s)?.revisions?.some(x=>x.revision_id===r) ||
        fresh.site_id!==s || fresh.revision_id!==r || fresh.deletable!==true)
      throw new Error('สถานะเวอร์ชันเปลี่ยนระหว่างยืนยัน ระบบยกเลิกการลบ');
    const done=await api(url,'DELETE',{confirm_value:r});
    if (done.ok!==true || done.site_id!==s || done.revision_id!==r || done.runtime_changed!==false)
      throw new Error('ผลลบไม่ตรงกับเวอร์ชันที่เลือก กรุณาตรวจบันทึกระบบ');
    await refresh();
    info('ย้ายเวอร์ชันที่เลือกไปถังเก็บสำรองแล้ว ระบบที่กำลังใช้งานไม่เปลี่ยน','success');
  }
  async function removeSite() {
    const s=state.site;
    const before=await api('/api/runtime-sites');
    if (before.active_site===s || before.sites?.find(x=>x.site_id===s)?.active)
      throw new Error('ลบพื้นที่ที่กำลังใช้งานไม่ได้');
    const p=await api(`/api/runtime-sites/${enc(s)}/delete-preview`);
    if (p.site_id!==s || p.deletable!==true)
      throw new Error('ยังลบพื้นที่นี้ไม่ได้: '+reasons(p).join('; '));
    if (!confirm(`ย้ายพื้นที่ติดตั้งนี้ไปถังเก็บสำรอง?\n\nพื้นที่: ${s}\nเวอร์ชันที่เก็บ: ${p.revision_count ?? '?'}\nชุดแก้ไขและข้อมูลปรับเทียบของพื้นที่นี้จะย้ายไปด้วย\n\nระบบที่กำลังใช้งานจะไม่เปลี่ยน`)) return;
    if (prompt(`พิมพ์รหัสพื้นที่นี้ให้ตรงทุกตัว เพื่อยืนยันการลบ\n${s}`)!==s) {info('ยกเลิก: รหัสพื้นที่ไม่ตรง','warn');return;}
    const next=await api('/api/runtime-sites');
    const fresh=await api(`/api/runtime-sites/${enc(s)}/delete-preview`);
    if (state.site!==s || next.active_site===s || !next.sites?.some(x=>x.site_id===s) || fresh.site_id!==s || fresh.deletable!==true)
      throw new Error('สถานะพื้นที่เปลี่ยนระหว่างยืนยัน ระบบยกเลิกการลบ');
    const done=await api(`/api/runtime-sites/${enc(s)}`,'DELETE',{confirm_value:s});
    if (done.ok!==true || done.site_id!==s || done.runtime_changed!==false)
      throw new Error('ผลลบไม่ตรงกับพื้นที่ที่เลือก กรุณาตรวจบันทึกระบบ');
    state.site='';await refresh();info('ย้ายพื้นที่ที่เลือกไปถังเก็บสำรองแล้ว','success');
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
        <div><p class="sf29-eyebrow">พื้นที่ติดตั้งและเวอร์ชัน</p><h2>จัดการพื้นที่ติดตั้ง</h2>
        <p>เลือกพื้นที่เดิมเพื่อดู ตั้งค่า หรือจัดการเวอร์ชันที่เคยบันทึก</p></div>
        <button type="button" class="sf29-btn sf29-primary" id="sf29-new">+ เพิ่มพื้นที่ติดตั้ง</button>
      </div>
      <div class="sf29-live" role="status"><div><span class="sf29-kicker">ระบบที่กำลังใช้งาน</span>
        <strong id="sf29-current-site">กำลังโหลด...</strong>
        <small id="sf29-current-revision">—</small><small id="sf29-autostart" role="status" aria-live="polite">กำลังตรวจบริการและการเริ่มพร้อมเครื่อง...</small></div><span class="sf29-live-pill" id="sf29-sitecount">—</span></div>
      <div id="sf29-login" class="sf29-login" hidden><label for="sf29-token">เข้าสู่โหมดจัดการ (Manager)</label>
        <div class="sf29-inline"><input id="sf29-token" type="password" autocomplete="current-password" placeholder="Manager Token">
          <button type="button" class="sf29-btn sf29-primary" id="sf29-login-btn">ปลดล็อก</button></div></div>
      <div class="sf29-card">
        <div class="sf29-card-head"><div><span class="sf29-step">1</span><strong>เลือกพื้นที่</strong></div>
          <button type="button" class="sf29-textbtn" id="sf29-refresh">รีเฟรช</button></div>
        <label class="sf29-field"><span>พื้นที่ที่ต้องการจัดการ</span><select id="sf29-site" aria-label="เลือกพื้นที่ติดตั้ง"></select></label>
        <div class="sf29-info"><div class="sf29-site-title"><strong id="sf29-selected-name">—</strong><span id="sf29-selected-status" class="sf29-status">—</span></div>
          <p id="sf29-selected-id" class="sf29-id">—</p><div class="sf29-tags"><span id="sf29-mode">—</span><span id="sf29-draft">—</span></div>
          <p class="sf29-guidance" id="sf29-tip">—</p><div id="sf29-warnings" class="sf29-warnings" hidden></div></div>
        <div class="sf29-actions"><button type="button" class="sf29-btn sf29-primary" id="sf29-open-setup" disabled>เปิด Setup Wizard</button>
          <button type="button" class="sf29-btn" id="sf29-rename" disabled>เปลี่ยนชื่อที่แสดง</button>
          <button type="button" class="sf29-btn sf29-danger" id="sf29-delete" disabled>ลบพื้นที่นี้</button></div>
        <section class="sf29-offline" id="sf29-offline-camera" hidden>
          <h3>แก้การเชื่อมต่อกล้องแบบออฟไลน์</h3>
          <p id="sf29-offline-warning"></p>
          <div class="sf29-inline"><label>Camera IP <input type="text" id="sf29-offline-ip" autocomplete="off" placeholder="192.168.1.10"></label>
          <label>HTTP Port <input type="number" id="sf29-offline-port" min="1" max="65535"></label></div>
          <div class="sf29-inline"><label>RTSP Port <input type="number" id="sf29-offline-rtsp-port" min="1" max="65535"></label>
          <label>RTSP Path <input type="text" id="sf29-offline-path" placeholder="/stream"></label></div>
          <div class="sf29-inline"><label>ชื่อผู้ใช้ใหม่ (เว้นว่าง = ใช้เดิม) <input type="text" id="sf29-offline-user" autocomplete="off"></label>
          <label>รหัสผ่านใหม่ (เว้นว่าง = ใช้เดิม) <input type="password" id="sf29-offline-password" autocomplete="new-password"></label></div>
          <div class="sf29-actions"><button type="button" class="sf29-btn sf29-primary" id="sf29-offline-save" disabled>บันทึกค่ากล้องออฟไลน์</button>
          <button type="button" class="sf29-btn" id="sf29-offline-reload">โหลดค่าล่าสุด</button>
          <button type="button" class="sf29-btn sf29-danger" id="sf29-offline-discard" disabled>ยกเลิกชุดแก้ไขออฟไลน์</button></div>
          <p role="status" id="sf29-offline-status">ยังไม่ได้โหลดข้อมูล</p>
          <details class="sf29-review" id="sf29-review-panel">
            <summary>ตรวจหลักฐาน Intrinsics / PTZ แบบออฟไลน์</summary>
            <p id="sf29-review-evidence">กดโหลดเพื่อดูจำนวนภาพและโมเดล</p>
            <p id="sf29-review-status" role="status">ไม่เปลี่ยนผล Calibration เดิม</p>
            <label>Intrinsics <select id="sf29-review-intrinsics"><option value="recapture_required">ต้องเก็บภาพและปรับเทียบใหม่</option><option value="reference_only">เก็บหลักฐานเดิมไว้อ้างอิงเท่านั้น</option></select></label>
            <label>PTZ <select id="sf29-review-ptz"><option value="recapture_required">ต้องสแกนและตรวจใหม่</option><option value="reference_only">เก็บภาพ PTZ เดิมไว้อ้างอิงเท่านั้น</option></select></label>
            <label>หมายเหตุแผนตรวจ (ไม่ใส่รหัสผ่าน) <textarea id="sf29-review-notes" maxlength="500" rows="2"></textarea></label>
            <div class="sf29-actions"><button type="button" class="sf29-btn" id="sf29-review-load">โหลดหลักฐานล่าสุด</button>
            <button type="button" class="sf29-btn sf29-primary" id="sf29-review-save">บันทึกแผนตรวจ</button></div>
            <p class="sf29-guidance">การบันทึกนี้ไม่แก้โมเดล รูปถ่าย หรือสถานะผ่าน Production · ต้องทดสอบจริงก่อน Activate</p>
          </details>
        </section>
        <p class="sf29-action-hint" id="sf29-site-delete-hint" role="status">กำลังตรวจสอบสิทธิ์การลบ</p>
      </div>
      <div class="sf29-card" id="sf29-readiness-area">
        <div class="sf29-card-head"><div><span class="sf29-step">2</span><strong>เลือกเวอร์ชันสำหรับใช้งาน</strong></div></div>
        <label class="sf29-field" id="sf29-revision-field"><span>เวอร์ชันที่บันทึกไว้ (Revision)</span><select id="sf29-revision"></select></label>
        <div class="sf29-readiness"><strong id="sf29-readiness">—</strong><small id="sf29-mode-label">—</small>
          <pre id="sf29-plan-result" aria-live="polite"></pre></div>
        <div class="sf29-actions"><button type="button" class="sf29-btn" id="sf29-check" disabled>ตรวจความพร้อม</button>
          <button type="button" class="sf29-btn sf29-primary" id="sf29-activate" disabled>ใช้เวอร์ชันนี้กับระบบ</button>
          <button type="button" class="sf29-btn sf29-danger" id="sf29-delete-revision" disabled>ลบเวอร์ชันที่เลือก</button></div>
        <p class="sf29-action-hint" id="sf29-delete-revision-hint" role="status">กำลังตรวจสอบความปลอดภัยก่อนลบเวอร์ชัน</p>
      </div>
      <details class="sf29-trash" id="sf29-trash">
        <summary>ถังเก็บสำรอง (Trash) — กู้คืนพื้นที่หรือเวอร์ชันที่ลบไป</summary>
        <p class="sf29-trash-note">กู้กลับมาเป็นข้อมูลที่บันทึกไว้เท่านั้น ไม่เปลี่ยนระบบตรวจจับที่กำลังใช้งาน</p>
        <div class="sf29-trash-controls"><label class="sf29-field"><span>รายการที่ต้องการกู้คืน</span>
          <select id="sf29-trash-select" aria-label="เลือกรายการจากถังสำรอง"><option value="">เปิดส่วนนี้เพื่อโหลดรายการ</option></select></label>
          <div class="sf29-actions"><button type="button" class="sf29-btn" id="sf29-trash-refresh">โหลดรายการอีกครั้ง</button>
          <button type="button" class="sf29-btn sf29-primary" id="sf29-trash-restore" disabled>กู้คืนรายการที่เลือก</button></div>
          <p class="sf29-action-hint" id="sf29-trash-hint" role="status">จะตรวจข้อมูลและยืนยันก่อนกู้คืน</p>
        </div>
      </details>
      <div class="sf29-minilinks"><button type="button" class="sf29-textbtn" id="sf29-calibration">ดูสถานะการปรับเทียบ</button>
        <a href="/settings">ตั้งค่าระบบและการแจ้งเตือน</a><span id="sf29-auth-label">—</span></div>
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
        if(i===6) await waitFor('sfw26');
        if(i===7) await waitFor('sf27');
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
    const title=node('summary','', 'เครื่องมือเดิมสำหรับงานเฉพาะทาง (Compatibility)');
    const intro=node('p','sf29-expert-note','ใช้การจัดการพื้นที่และเวอร์ชันจากส่วนด้านบน เครื่องมือเดิมด้านในเก็บไว้สำหรับงานเฉพาะทางที่ยังจำเป็น');
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
    $('sf29-offline-save').addEventListener('click',()=>perform(saveOfflineCamera));
    $('sf29-offline-reload').addEventListener('click',()=>perform(loadOfflineCamera));
    $('sf29-review-load').addEventListener('click',()=>perform(loadOfflineReview));
    $('sf29-review-save').addEventListener('click',()=>perform(saveOfflineReview));
    $('sf29-offline-discard').addEventListener('click',()=>perform(discardOfflineCamera));
    $('sf29-rename').addEventListener('click',()=>perform(renameSite));
    $('sf29-delete').addEventListener('click',()=>perform(removeSite));
    $('sf29-delete-revision').addEventListener('click',()=>perform(removeRevision));
    $('sf29-new').addEventListener('click',()=>{location.assign('/setup-wizard?mode=new');});
    $('sf29-calibration').addEventListener('click',navigateCalibration);
    $('sf29-trash').addEventListener('toggle',()=>{if($('sf29-trash').open) void loadTrash();});
    $('sf29-trash-refresh').addEventListener('click',()=>void loadTrash());
    $('sf29-trash-restore').addEventListener('click',()=>perform(restoreTrash));
    refresh().catch(e=>info('โหลดข้อมูลไซต์ไม่ได้: '+e.message,'error'));
    return true;
  }
  function boot(){let attempts=0;const timer=setInterval(()=>{if(mount() || ++attempts>100) clearInterval(timer);},150);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
