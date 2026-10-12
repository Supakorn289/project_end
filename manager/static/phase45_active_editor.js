(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let snapshot = null;
  const msg = s => { if ($('sf-p45-status')) $('sf-p45-status').textContent = String(s); };
  async function api(path, method='GET', value) {
    const session = await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'}).then(r=>r.json());
    if(!session.authenticated) throw Error('Unlock Manager ก่อนใช้งาน');
    const res=await fetch(path,{method,credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':session.csrf})},
      body:value===undefined?undefined:JSON.stringify(value)});
    const data=await res.json();
    if(!res.ok || data.ok===false) throw Error(data.error||`HTTP ${res.status}`);
    return data;
  }
  const formValue = () => {
    const coordinates={};
    for(const k of ['x_a_px','y_a_px','x_b_px','y_b_px']){
      const el=$('sf-p45-'+k);
      if(el.value.trim()==='' || !el.checkValidity())throw Error('กรุณากรอกพิกัดให้ครบและถูกต้อง');
      coordinates[k]=Number(el.value);
    }
    return {phase:$('sf-p45-phase').value, pair:$('sf-p45-pair').value, mark:coordinates};
  };
  function show(state) {
    snapshot=state;
    $('sf-p45-current').textContent=`${state.site_id} / ${state.revision_id} · ${state.source}`;
    $('sf-p45-config').textContent=JSON.stringify(state.overview,null,2);
    $('sf-p45-dirty').textContent=state.geometry_dirty?'Landmarks เปลี่ยนแล้ว — ต้อง Solve/Verify Geometry ใหม่':'ค่าปัจจุบันยังไม่ถูกแก้';
    $('sf-p45-edit-state').textContent=state.editable?'Working Copy: EDITABLE':'Read-only: ต้องสร้าง Working Copy ก่อน';
    $('sf-p45-make-draft').disabled=state.editable;
    const list=$('sf-p45-mark-list');list.replaceChildren();
    let count=0;
    for (const phase of ['train','holdout']) {
      const records=state.marks?.[phase]||{};
      for (const [pair, marks] of Object.entries(records)) {
        for(let index=0;index<marks.length;index++) {
          count++;
          const mark=marks[index], row=document.createElement('div');row.className='sf-p45-mark';
          const label=document.createElement('span');label.textContent=`${phase} · ${pair} #${index+1} · `+
            ['x_a_px','y_a_px','x_b_px','y_b_px'].map(k=>Number(mark[k]).toFixed(1)).join(' / ');
          const btn=document.createElement('button');btn.textContent='แก้ค่า';btn.type='button';btn.disabled=!state.editable;
          btn.onclick=()=>{ $('sf-p45-phase').value=phase;$('sf-p45-pair').value=pair;$('sf-p45-index').value=String(index);
            for (const k of ['x_a_px','y_a_px','x_b_px','y_b_px'])$('sf-p45-'+k).value=mark[k];msg('โหลดค่าเก่าสำหรับแก้ไขแล้ว');};
          row.append(label,btn);list.append(row);
        }
      }
    }
    if(!count)list.textContent='ไม่มี Landmark ใน Wizard State ของ Revision นี้ — ตรวจ Geometry Inputs เก่าก่อนเพิ่มใหม่';
    for (const id of ['sf-p45-add','sf-p45-update','sf-p45-delete'])$(id).disabled=!state.editable;
  }
  async function load(){msg('กำลังอ่าน Active Revision...');show(await api('/api/phase45/active/editor'));msg('โหลดค่าเดิมแล้ว (ไม่แก้ Runtime)');}
  async function draft(){
    const s=snapshot;if(!s)throw Error('กดโหลดค่าก่อน');
    if(s.editable)return;
    if(!confirm(`สร้าง Working Copy จาก Active Revision\n${s.site_id}\n${s.revision_id}\nRuntime จะไม่เปลี่ยน`))return;
    const url=`/api/runtime-sites/${encodeURIComponent(s.site_id)}/revision/${encodeURIComponent(s.revision_id)}/working-copy`;
    try{await api(url,'POST',{overwrite:false});}
    catch(e){
      if(!String(e.message).includes('working_copy_exists'))throw e;
      if(!confirm('มี Candidate/Working Copy เดิมอยู่แล้ว\nหากเริ่มใหม่ ระบบจะ Archive ของเดิมเข้า Trash ก่อน\nยืนยันจะเริ่มจาก Active Revision ปัจจุบันหรือไม่?'))return;
      await api(url,'POST',{overwrite:true});
    }
    await load();
  }
  async function modify(action){
    const s=snapshot;if(!s?.editable)throw Error('ต้องสร้าง Working Copy ของ Active Site ก่อน');
    const values = action==='delete'? {phase:$('sf-p45-phase').value,pair:$('sf-p45-pair').value}:formValue();
    const index=$('sf-p45-index').value;
    const payload={site_id:s.site_id,revision_id:s.revision_id,expected_digest:s.geometry_digest,
      action,phase:values.phase,pair:values.pair};
    if(action!=='add'){if(!/^\d+$/.test(index))throw Error('เลือกมาร์คจากรายการเดิมก่อน');payload.index=Number(index);}
    if(action!=='delete')payload.mark=values.mark;
    if(!confirm(`${action.toUpperCase()} ${values.phase} ${values.pair}?\nGeometry Verify จะต้องทำใหม่ก่อน Publish`))return;
    await api('/api/phase45/active/marks','POST',payload);await load();
    msg('บันทึก Working Copy สำเร็จ · ยังไม่เปลี่ยน Runtime · Geometry ต้อง Verify ใหม่');
  }
  function boot(){
    const host=$('sf-simple');if(!host || $('sf-active-editor'))return false;
    const panel=document.createElement('details');panel.id='sf-active-editor';panel.className='rsm-panel';
    panel.innerHTML=`<summary><strong>แก้ไข Active Site — ดูค่าเดิม / เพิ่ม-แก้-ลบ Landmark</strong></summary>
      <p>แสดงค่าจาก Active Revision จริง ค่าแก้ไขทั้งหมดอยู่ใน Working Copy เท่านั้น ไม่แก้ Runtime ทันที</p>
      <p id="sf-p45-current">ยังไม่โหลด</p><div class="sf-simple-actions"><button id="sf-p45-load" type="button">โหลดค่าเดิม</button>
      <button id="sf-p45-make-draft" type="button" disabled>สร้าง Working Copy</button>
      <button id="sf-p45-wizard" type="button">เปิด Setup Wizard สำหรับหมวดอื่น</button></div>
      <p id="sf-p45-edit-state"></p><pre id="sf-p45-config" style="overflow:auto;max-height:280px">-</pre>
      <h4>Correlation / Geometry Landmark</h4><p id="sf-p45-dirty"></p>
      <div id="sf-p45-mark-list" style="max-height:300px;overflow:auto"></div>
      <div class="sf-simple-grid"><label>ชุด <select id="sf-p45-phase"><option value="train">Train</option><option value="holdout">Holdout</option></select></label>
      <label>คู่ Preset <input id="sf-p45-pair" value="1-2" pattern="[1-9]-[1-9]"/></label></div>
      <div class="sf-simple-grid"><label>Mark Index (เริ่ม 0) <input id="sf-p45-index" type="number" min="0" placeholder="เลือกรายการด้านบน"/></label><label>X A <input id="sf-p45-x_a_px" type="number" step="0.1" value="100"/></label>
      <label>Y A <input id="sf-p45-y_a_px" type="number" step="0.1" value="100"/></label><label>X B <input id="sf-p45-x_b_px" type="number" step="0.1" value="100"/></label>
      <label>Y B <input id="sf-p45-y_b_px" type="number" step="0.1" value="100"/></label></div>
      <div class="sf-simple-actions"><button id="sf-p45-add" type="button" disabled>เพิ่มมาร์ค</button><button id="sf-p45-update" type="button" disabled>แก้ไขมาร์คที่เลือก</button>
      <button id="sf-p45-delete" type="button" disabled>ลบมาร์คที่เลือก</button></div>
      <pre id="sf-p45-status">โหลด Active Site ก่อน</pre>
      <p>หมายเหตุ: ต้อง Prepare Geometry Inputs → Solve → Final Verification → New Revision ก่อนใช้งานค่าที่แก้ไข</p>`;
    host.append(panel);
    const safely=fn=>async()=>{try{await fn();}catch(e){msg('ERROR: '+e.message);}};
    $('sf-p45-load').onclick=safely(load);
    $('sf-p45-make-draft').onclick=safely(draft);
    $('sf-p45-add').onclick=safely(()=>modify('add'));
    $('sf-p45-update').onclick=safely(()=>modify('update'));
    $('sf-p45-delete').onclick=safely(()=>modify('delete'));
    $('sf-p45-wizard').onclick=()=>{if(snapshot)location.assign(`/setup-wizard?mode=existing&site=${encodeURIComponent(snapshot.site_id)}`);};
    panel.addEventListener('toggle',()=>{if(panel.open&&!snapshot)safely(load)();});
    return true;
  }
  let count=0;const timer=setInterval(()=>{if(boot()||++count>100)clearInterval(timer);},150);
})();
