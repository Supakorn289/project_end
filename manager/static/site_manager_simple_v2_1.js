(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let csrf = null, inventory = null;
  const esc = encodeURIComponent;
  const current = () => $('sf-simple-site')?.value || '';
  const revision = () => $('sf-simple-revision')?.value || '';
  function report(value) {
    const box = $('sf-simple-result');
    if (box) box.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  }
  async function api(path, method='GET', payload) {
    const headers = {'Content-Type':'application/json'};
    if (csrf && method !== 'GET') headers['X-CSRF-Token'] = csrf;
    const response = await fetch(path, {method, headers, credentials:'same-origin', cache:'no-store',
      body:payload===undefined ? undefined : JSON.stringify(payload)});
    let data;
    try { data=await response.json(); } catch { data={error:`HTTP ${response.status}`}; }
    if (!response.ok) throw Error(data.reason || data.error || `HTTP ${response.status}`);
    return data;
  }
  async function unlock() {
    const data = await api('/api/auth/session');
    csrf = data.authenticated ? data.csrf : null;
    if (!csrf) { report('กรุณากด Unlock Manager ในกล่องด้านบนก่อนใช้งาน');
      $('rsm-login')?.classList.remove('rsm-hidden'); return false; }
    return true;
  }
  async function refresh() {
    if (!(await unlock())) return;
    inventory = await api('/api/runtime-sites');
    const selected = current() || inventory.active_site;
    const s = $('sf-simple-site');
    s.replaceChildren();
    for (const site of inventory.sites || []) {
      const option = document.createElement('option');
      option.value = site.site_id;
      option.textContent = `${site.display_name || site.site_id} (${site.active?'กำลังใช้งาน':'ยังไม่ใช้งาน'})`;
      if (site.site_id === selected) option.selected = true;
      s.append(option);
    }
    updateRevisions();
    $('sf-simple-live').textContent = `${inventory.active_site} · ${inventory.active_revision}`;
    report('เลือก Site และดำเนินการจากปุ่มหลักได้เลย');
  }
  function updateRevisions() {
    const site = (inventory?.sites || []).find(s => s.site_id === current());
    const r = $('sf-simple-revision');
    const old = revision(); r.replaceChildren();
    for (const item of site?.revisions || []) {
      const option = document.createElement('option');
      option.value = item.revision_id;
      option.textContent = `${item.revision_id} · ${item.status || 'UNKNOWN'} · ${item.candidate_ready?'READY':'NOT READY'}`;
      if (old===item.revision_id || (!old && item.active)) option.selected = true;
      r.append(option);
    }
    if (!r.options.length) { const option = new Option('ยังไม่มี Revision','');r.add(option); }
  }
  async function planOnly() {
    if (!(await unlock())) return;
    const site = current(), rev = revision();
    if (!site || !rev) { report('กรุณาเลือก Site และ Revision'); return; }
    const selected = (inventory?.sites || []).find(x => x.site_id === site);
    if (!selected?.revisions?.some(x => x.revision_id === rev)) {
      report('รายการ Site/Revision ไม่ตรงกับ Inventory กรุณากดรีเฟรชสถานะ'); return;
    }
    const p = await api(`/api/activation/${esc(site)}/${esc(rev)}/plan`);
    if (p.site_id !== site || p.revision_id !== rev) {
      report({error:'ACTIVATION_PLAN_IDENTITY_MISMATCH', selected_site:site, selected_revision:rev}); return;
    }
    if (current() !== site || revision() !== rev) {
      report('รายการที่เลือกเปลี่ยนระหว่างตรวจแผน กรุณากดตรวจอีกครั้ง'); return;
    }
    report({operation:'ACTIVATION_PLAN', selected_site:site, selected_revision:rev, ...p});
  }
  async function activate() {
    if (!(await unlock())) return;
    const site = current(), rev = revision();
    if (!rev) {report('Site ที่เลือกยังไม่มี Revision สำหรับสลับ Runtime');return;}
    if (site === inventory.active_site && rev === inventory.active_revision) {
      report('Site และ Revision นี้กำลังทำงานอยู่แล้ว'); return;
    }
    const plan = await api(`/api/activation/${esc(site)}/${esc(rev)}/plan`);
    if (plan.site_id !== site || plan.revision_id !== rev) {
      report({error:'ACTIVATION_PLAN_IDENTITY_MISMATCH', selected_site:site, selected_revision:rev}); return;
    }
    report({step:'Activation Plan', ...plan});
    if (plan.activatable !== true) {report({message:'ยัง Activate ไม่ได้ กรุณาตรวจ Verification', ...plan}); return;}
    if (current() !== site || revision() !== rev) {
      report('Selection changed during Activation Plan; retry'); return;
    }
    const msg = `จะหยุด Detection ชั่วคราวและสลับ Runtime ไปที่\n${site}\n${rev}\n\n`+
                `ตรวจว่ากล้อง/PTZ อยู่ในจุดที่ปลอดภัยแล้ว\n`+
                `หากเป็น Legacy LAB Trial ยังไม่มีหลักฐาน Intrinsics lineage และห้ามใช้รับรอง Production\n\n`+
                `พิมพ์ Site ID เพื่อยืนยัน:`;
    if (!confirm('ตรวจ Activation Plan ผ่านแล้ว ต้องการสลับ Runtime จริงหรือไม่?')) return;
    if (prompt(msg) !== site) {report('ยกเลิก: Site ID ไม่ตรง');return;}
    if (current() !== site || revision() !== rev) {
      report('ยกเลิก: Site/Revision เปลี่ยนระหว่างยืนยัน'); return;
    }
    report('กำลัง Activate; อย่าปิดหน้านี้จนกว่าระบบตอบกลับ');
    const res = await api(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/activate`,'POST',
                          {confirm_site_id:site,confirm_revision_id:rev});
    await refresh(); report({message:'Activation returned', ...res});
  }
  async function editActive() {
    if (!(await unlock())) return;
    const site = inventory.active_site, rev = inventory.active_revision;
    if (current() !== site) {report(`แก้ไขได้เฉพาะ Site ปัจจุบัน (${site})`);return;}
    const selected = (inventory.sites || []).find(row => row.site_id === site);
    const working = selected?.working_copy || {};
    if (!working.exists) {
      if (!confirm(`สร้าง Working Copy จาก ${rev} ของ Active Site?\nจะยังไม่เปลี่ยน Runtime`)) return;
      await api(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/working-copy`,'POST',{overwrite:false});
    }
    location.assign(`/setup-wizard?mode=existing&site=${esc(site)}`);
  }
  async function deleteUnused() {
    if (!(await unlock())) return;
    const site=current();
    if (!site || site === inventory.active_site) {report('ห้ามลบ Active Site');return;}
    const preview = await api(`/api/runtime-sites/${esc(site)}/delete-preview`);
    report(preview);
    if (!preview.deletable) {report({message:'ระบบปฏิเสธการลบ กรุณาตรวจ blockers',...preview});return;}
    if (!confirm(`ระบบจะย้าย Site ${site} ไป Trash ตาม Delete Preview\nแน่ใจหรือไม่?`)) return;
    if (prompt(`พิมพ์ Site ID เพื่อยืนยันการลบ:\n${site}`)!==site) return;
    const result=await api(`/api/runtime-sites/${esc(site)}`,'DELETE',{confirm_value:site});
    await refresh(); report(result);
  }
  async function previewLegacy() {
    if (!(await unlock())) return;
    const p=await api(`/api/runtime-sites/${esc(current())}/legacy-geometry-preview`);
    report(p);
    return p;
  }
  async function acceptLegacy() {
    const p=await previewLegacy();
    if (!p?.eligible) return;
    if (p.accepted) {report('LAB-only review ถูกบันทึกแล้ว ตรวจ Final Verification ต่อได้');return;}
    if (!confirm('ยืนยันว่าเป็นกล้อง/เลนส์/จุดติดตั้ง/ความละเอียด/ตำแหน่ง Preset เดิม และเข้าใจว่าความแม่นยำปัจจุบันยังไม่ได้รับรอง?')) return;
    if (!confirm('คุณยอมรับการใช้สำหรับ LAB Trial เท่านั้น ไม่ใช่การตรวจจับไฟเพื่อความปลอดภัยจริง และจะทำ Geometry Validation ใหม่ก่อน Production?')) return;
    const site=current();
    if (prompt(`พิมพ์ Site ID เพื่อบันทึก LAB Trial Review:\n${site}`)!==site) {report('ยกเลิก');return;}
    const value=await api(`/api/runtime-sites/${esc(site)}/legacy-geometry-lab-accept`,'POST',{
      confirm_site_id:site,same_hardware_ack:true,unknown_intrinsics_lineage_ack:true,explicit_lab_only_ack:true});
    report(value);
  }
  async function verification() {
    if (!(await unlock())) return;
    report(await api(`/api/final-verification/${esc(current())}`));
  }
  async function publish() {
    if (!(await unlock())) return;
    const v=await api(`/api/final-verification/${esc(current())}`);
    report(v);
    if (!v.candidate_ready) {report({message:'ยังมี Blocker ห้าม Publish',blockers:v.blockers,warnings:v.warnings});return;}
    if (!confirm('สร้าง Immutable Revision ใหม่จาก Candidate ปัจจุบัน? (ยังไม่ Activate)')) return;
    const p=await api(`/api/runtime-sites/${esc(current())}/working-copy/publish`,'POST',{});
    await refresh(); report({message:'สร้าง Revision แล้ว กรุณาเลือก Revision ใหม่นี้ในเมนู', ...p});
  }
  function run(fn) {return async () => {try{await fn();}catch(e){report('ERROR: '+e.message);}};}
  function init() {
    const host=$('runtime-site-manager');
    if (!host || !$('rsm-runtime-switcher') || !$('rsm-v2-tools') || $('sf-simple')) return false;
    const panel=document.createElement('section');
    panel.className='rsm-panel';panel.id='sf-simple';
    panel.innerHTML=`
      <h3>จัดการ Site (แบบง่าย)</h3><p class="rsm-sub">เลือก Site · ตรวจความพร้อม · แก้ไข · ลบอย่างปลอดภัย</p>
      <p>Runtime ปัจจุบัน: <strong id="sf-simple-live">Loading...</strong></p>
      <div class="sf-simple-grid"><label>Site <select id="sf-simple-site"></select></label>
      <label>Revision <select id="sf-simple-revision"></select></label></div>
      <div class="sf-simple-actions">
        <button type="button" id="sf-simple-activate">1. เลือก Site ใช้งาน</button>
        <button type="button" id="sf-simple-edit">2. แก้ไข Site ปัจจุบัน</button>
        <button type="button" id="sf-simple-delete">3. ลบ Site ที่ไม่ได้ใช้</button>
      </div>
      <div class="sf-simple-actions"><button type="button" id="sf-simple-plan">ตรวจแผนก่อนสลับ (ไม่ Activate)</button><button type="button" id="sf-simple-refresh">รีเฟรชสถานะ</button></div>
      <details id="sf-simple-advanced"><summary>การทดสอบ/ขั้นสูง — Geometry, Final Verification และ Publish Revision</summary>
        <div class="sf-simple-actions">
          <button type="button" id="sf-simple-check-legacy">ตรวจ Legacy Geometry</button>
          <button type="button" id="sf-simple-accept-legacy">ยอมรับ LAB Trial (มีความเสี่ยง)</button>
          <button type="button" id="sf-simple-verify">Final Verification</button>
          <button type="button" id="sf-simple-publish">สร้าง Revision (ยังไม่ Activate)</button>
          <button type="button" id="sf-simple-wizard">เปิด Setup Wizard</button>
        </div>
        <p class="sf-simple-caution">LAB Trial ยอมรับข้อมูล Holdout เก่าเพื่อทดลองเท่านั้น ไม่ได้พิสูจน์ว่า Geometry ใช้ Intrinsics ชุดนี้ หรือแม่นยำในสนามจริง</p>
      </details>
      <pre id="sf-simple-result" aria-live="polite">กรุณา Unlock Manager</pre>`;
    host.insertBefore(panel, host.children[1] || null);
    $('sf-simple-site').onchange=updateRevisions;
    const actions={plan:planOnly,activate,edit:editActive,delete:deleteUnused,refresh,checkLegacy:previewLegacy,acceptLegacy,
      verify:verification,publish,wizard:async()=>{if(await unlock()) location.assign(`/setup-wizard?mode=existing&site=${esc(current())}`);}};
    for(const [k,v] of Object.entries(actions)){
      const id={'checkLegacy':'check-legacy','acceptLegacy':'accept-legacy'}[k] || k;
      const button=$('sf-simple-'+id); if(button)button.onclick=run(v);
    }
    // Move the old expert panels under a native disclosure without rebuilding
    // them, so original JS events, safeguards and API pathways remain intact.
    const details=document.createElement('details');details.id='sf-full-expert';
    const summary=document.createElement('summary');summary.textContent='แสดงเครื่องมือผู้เชี่ยวชาญทั้งหมด';details.append(summary);
    for(const node of [...host.children]){
      if(node===panel || node===details || node.id==='rsm-runtime-switcher' || node===host.firstElementChild)continue;
      details.append(node);
    }
    host.append(details);
    const switcher=$('rsm-runtime-switcher');
    if(switcher)details.append(switcher);
    refresh().catch(e=>report(String(e)));
    $('rsm-unlock')?.addEventListener('click',()=>setTimeout(()=>refresh().catch(e=>report(String(e))),600));
    return true;
  }
  function boot(){
    let attempts=0; const t=setInterval(()=>{if(init()||++attempts>60)clearInterval(t);},150);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
