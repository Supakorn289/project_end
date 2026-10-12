(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 let settings=null;
 const stateMsg=(msg)=>{if($('v24-settings-message'))$('v24-settings-message').textContent=msg;};
 async function request(path, method='GET', body) {
   const auth=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'}).then(r=>r.json());
   if(!auth.authenticated)throw Error('Unlock Manager ก่อน');
   const res=await fetch(path,{method,credentials:'same-origin',cache:'no-store',
     headers:{'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':auth.csrf})},
     body:body===undefined?undefined:JSON.stringify(body)});
   const data=await res.json();
   if(!res.ok||data.ok===false)throw Error(data.error||`HTTP ${res.status}`);
   return data;
 }
 function valuesFromInput(){
   const o={};for(const k of Object.keys(settings.values)){
     const v=$('v24-setting-'+k).value;
     if(v.trim()===''||!Number.isFinite(Number(v)))throw Error('ค่า '+k+' ไม่ถูกต้อง');
     o[k]=v;
   }return o;
 }
 const items=[
   ['ALERT_COOLDOWN_SEC','Alert Cooldown (วินาที)','0','3600'],
   ['ALERT_DEDUP_IOU_THRESHOLD','Alert Dedup IoU','0','1'],
   ['FUSION_ANCHOR_MAX_AGE_SEC','Fusion Anchor Max Age (วินาที)','1','120'],
   ['FUSION_PENDING_SAFETY_SEC','Fusion Pending Safety (วินาที)','1','600'],
 ];
 function renderSettings(data){
   settings=data;
   $('v24-settings-site').textContent=`Active: ${data.site_id} / ${data.revision_id} · ${data.source}`;
   for(const [key] of items){$('v24-setting-'+key).value=data.values[key];$('v24-setting-'+key).disabled=!data.editable;}
   $('v24-save').disabled=!data.editable;
   $('v24-draft').disabled=data.editable;
   $('v24-settings-locked').textContent='คงค่าตาม Model Contract (แก้จากหน้านี้ไม่ได้): '+data.locked_keys.join(', ');
   stateMsg(data.editable?'Working Copy พร้อมแก้ไข — ยังไม่กระทบ Runtime':'อ่านค่าเดิมแล้ว — ต้องสร้าง Working Copy ของ Active Revision ก่อน');
 }
 async function loadSettings(){stateMsg('กำลังโหลดค่าเดิม...');renderSettings(await request('/api/phase45/site-settings'));}
 async function beginDraft(){
   if(!settings)throw Error('กดโหลดค่าเดิมก่อน');
   if(settings.editable)return;
   if(!confirm(`สร้าง Working Copy ของ Active Site\n${settings.site_id}\n${settings.revision_id}\nRuntime ยังไม่เปลี่ยน`))return;
   const url=`/api/runtime-sites/${encodeURIComponent(settings.site_id)}/revision/${encodeURIComponent(settings.revision_id)}/working-copy`;
   try{await request(url,'POST',{overwrite:false});}
   catch(e){
     if(!String(e.message).includes('working_copy_exists'))throw e;
     if(!confirm('มี Candidate/Working Copy เดิมอยู่แล้ว\nระบบจะ Archive ของเดิมเข้า Trash ก่อนเริ่มใหม่\nยืนยันไหม?'))return;
     await request(url,'POST',{overwrite:true});
   }
   await loadSettings();
 }
 async function saveSettings(){
   if(!settings?.editable)throw Error('ต้องสร้าง Working Copy ก่อน');
   const changes=valuesFromInput();
   if(!confirm(`บันทึก Settings ของ ${settings.site_id} ลง Working Copy เท่านั้น?\nต้อง Final Verify, Publish และ Activate ก่อนใช้ค่าจริง`))return;
   const r=await request('/api/phase45/site-settings','POST',{site_id:settings.site_id,revision_id:settings.revision_id,
     expected_digest:settings.expected_digest, values:changes});
   await loadSettings();
   stateMsg('บันทึก Draft สำเร็จ — Runtime เดิมยังทำงานอยู่ (ต้อง Verify → Publish → Activate)');
 }
 let deletePreview=null;
 async function loadInactive(){
   const inv=await request('/api/runtime-sites');
   const sel=$('v24-delete-site');sel.replaceChildren();
   const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='เลือก Inactive Site';sel.append(placeholder);
   for(const site of inv.sites||[]){
     if(site.active)continue;
     const opt=document.createElement('option');opt.value=site.site_id;
     opt.textContent=`${site.display_name||site.site_id} — ${site.site_id}`;sel.append(opt);
   }
   deletePreview=null;$('v24-delete-result').textContent='เลือก Site แล้วกดตรวจสอบก่อนลบ';
 }
 async function previewDelete(){
   const id=$('v24-delete-site').value;
   if(!id)throw Error('เลือก Site ที่ไม่ใช้งานก่อน');
   const data=await request(`/api/runtime-sites/${encodeURIComponent(id)}/delete-preview`);
   deletePreview=data;
   $('v24-delete-result').textContent=JSON.stringify({site_id:data.site_id,active:data.active,deletable:data.deletable,
     revision_count:data.revision_count,has_candidate:data.has_candidate,has_deployment:data.has_deployment,
     delete_mode:data.delete_mode,blocked_reason:data.blocked_reason,warnings:data.warnings},null,2);
   $('v24-delete-confirm').disabled=!data.deletable;
 }
 async function doDelete(){
   const obj=deletePreview,id=$('v24-delete-site').value;
   if(!obj||!obj.deletable||obj.site_id!==id)throw Error('ต้องตรวจ Preview ใหม่');
   const typed=prompt(`ลบ Site ที่ไม่ได้ Active?\n${id}\nระบบจะย้ายเข้า Trash เก็บไว้ตรวจสอบย้อนหลัง\nพิมพ์ Site ID เพื่อยืนยัน`);
   if(typed!==id){stateMsg('การลบถูกยกเลิก: Site ID ไม่ตรง');return;}
   const res=await request(`/api/runtime-sites/${encodeURIComponent(id)}`,'DELETE',{confirm_value:id});
   deletePreview=null;
   $('v24-delete-confirm').disabled=true;
   await loadInactive();
   $('v24-delete-result').textContent=JSON.stringify({ok:res.ok,site_id:res.site_id,trash:res.trash,runtime_changed:res.runtime_changed},null,2);
   stateMsg('ย้าย Inactive Site เข้า Trash สำเร็จ · ควรตรวจ Active Runtime อีกครั้ง');
 }
 function boot(){
   const host=$('sf-simple');if(!host||$('sf-v24-settings-panel'))return false;
   const block=document.createElement('details');block.id='sf-v24-settings-panel';block.className='rsm-panel';
   block.innerHTML=`<summary><strong>ตั้งค่า Detection / Fusion แยกตาม Active Site (v2.4)</strong></summary>
   <p>โหลดค่าเดิมจาก Active Revision หรือค่าเริ่มต้นที่ระบุชัดเจน · แก้เฉพาะ Working Copy · Revision เดิมไม่ถูกเปลี่ยน</p>
   <p id="v24-settings-site">ยังไม่โหลด</p>
   <div class="sf-simple-actions"><button type="button" id="v24-settings-load">โหลดค่าเดิม</button><button type="button" id="v24-draft" disabled>สร้าง Working Copy</button></div>
   <div class="sf-simple-grid" id="v24-settings-fields"></div>
   <p id="v24-settings-locked"></p>
   <button type="button" id="v24-save" disabled>บันทึกลง Working Copy (ยังไม่ Activate)</button>
   <pre id="v24-settings-message">ต้อง Unlock Manager ก่อนใช้งาน</pre>
   <p>ถ้าต้องแก้ Camera, PTZ, Intrinsics, Distance, Geometry หรือ Telegram ให้ใช้ Active Site Editor / Setup Wizard ที่มี Verification ของส่วนเหล่านั้นโดยเฉพาะ</p>`;
   host.append(block);
   const fields=$('v24-settings-fields');
   for(const [key,label,min,max] of items){
     const outer=document.createElement('label');outer.textContent=`${label} [${min}–${max}]`;
     const input=document.createElement('input');input.type='number';input.step='any';input.min=min;input.max=max;input.id='v24-setting-'+key;input.disabled=true;
     outer.append(input);fields.append(outer);
   }
   const deletion=document.createElement('details');deletion.id='sf-v24-delete-panel';deletion.className='rsm-panel';
   deletion.innerHTML=`<summary><strong>ลบ Site ที่ไม่ได้ใช้งาน — Preview → ยืนยัน → Trash</strong></summary>
   <p>ไม่อนุญาตให้ลบ Active Site; ระบบต้องยืนยันการไม่อ้างอิงจาก Runtime ก่อนทุกครั้ง</p>
   <div class="sf-simple-actions"><button type="button" id="v24-delete-refresh">โหลด Inactive Sites</button>
   <select id="v24-delete-site"><option value="">เลือก Site</option></select>
   <button type="button" id="v24-delete-preview">ตรวจความปลอดภัยก่อนลบ</button>
   <button type="button" id="v24-delete-confirm" disabled>ลบ Site ที่เลือก (เข้า Trash)</button></div>
   <pre id="v24-delete-result">ยังไม่ได้ตรวจ</pre>`;
   host.append(deletion);
   const safe=fn=>async()=>{try{await fn();}catch(e){stateMsg('ERROR: '+e.message);}};
   $('v24-settings-load').onclick=safe(loadSettings);
   $('v24-draft').onclick=safe(beginDraft);
   $('v24-save').onclick=safe(saveSettings);
   $('v24-delete-refresh').onclick=safe(loadInactive);
   $('v24-delete-preview').onclick=safe(previewDelete);
   $('v24-delete-confirm').onclick=safe(doDelete);
   $('v24-delete-site').onchange=()=>{deletePreview=null;$('v24-delete-confirm').disabled=true;};
   block.addEventListener('toggle',()=>{if(block.open&&!settings)safe(loadSettings)();});
   deletion.addEventListener('toggle',()=>{if(deletion.open)safe(loadInactive)();});
   return true;
 }
 let attempt=0;const timer=setInterval(()=>{if(boot()||++attempt>120)clearInterval(timer);},150);
})();
