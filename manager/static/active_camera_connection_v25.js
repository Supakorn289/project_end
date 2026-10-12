(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let current=null;
  const say=(message)=>{const el=$('v25-camera-message');if(el)el.textContent=String(message);};
  async function api(path,method='GET',data){
    const sr=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
    const session=await sr.json();
    if(!session.authenticated)throw Error('กรุณา Unlock Manager ก่อนใช้งาน');
    const res=await fetch(path,{method,credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':session.csrf})},
      body:data===undefined?undefined:JSON.stringify(data)});
    const obj=await res.json();
    if(!res.ok||obj.ok===false)throw Error(obj.error||`HTTP ${res.status}`);
    return obj;
  }
  const values=['camera_ip','camera_port','rtsp_port','rtsp_path'];
  function show(c){
    current=c;
    $('v25-camera-site').textContent=`${c.site_id} / ${c.revision_id} · ${c.source} · ${c.mode}`;
    $('v25-camera-active').textContent=JSON.stringify(c.active_camera,null,2);
    const cam=c.selected_camera;
    for(const key of values){$('v25-'+key).value=cam[key]??'';$('v25-'+key).disabled=!c.editable;}
    $('v25-camera-username').value='';$('v25-camera-password').value='';
    $('v25-camera-username').disabled=!c.editable;$('v25-camera-password').disabled=!c.editable;
    $('v25-camera-userhint').textContent=`Username เดิม: ${cam.camera_user_hint||'ไม่ระบุ'} · มีรหัสผ่าน: ${cam.password_configured?'ใช่':'ไม่'}. ช่อง Username/Password ว่าง = ใช้ค่าเดิม`;
    $('v25-camera-draft').disabled=c.editable || c.mode!=='LAB';
    $('v25-camera-save').disabled=!c.editable || c.mode!=='LAB';
    $('v25-camera-test').disabled=!c.editable || c.mode!=='LAB' || (!c.changed_from_active&&!c.camera_test_required);
    $('v25-camera-attest').disabled=!(c.editable&&c.mode==='LAB'&&c.changed_from_active&&c.camera_test_passed&&!c.camera_test_required);
    $('v25-camera-state').textContent=c.editable?
      `Working Copy: ${c.working_state} · Test ${c.camera_test_passed?'PASS':c.camera_test_required?'REQUIRED':'ยังไม่ผ่าน'} · เปลี่ยนจาก Active: ${c.changed_from_active?'ใช่':'ไม่'}`:
      'Read-only: สร้าง Working Copy ก่อนแก้ไข';
  }
  async function load(){say('กำลังโหลดค่ากล้องจาก Active Revision...');show(await api('/api/phase45/active/camera'));say('อ่านค่าเดิมสำเร็จ — ยังไม่ได้แก้ Runtime');}
  async function draft(){
    if(!current)throw Error('กดโหลดค่าเดิมก่อน');
    if(current.editable)return;
    const s=current;
    if(!confirm(`สร้าง Working Copy จาก Active Revision?\n${s.site_id}\n${s.revision_id}\nไม่แก้ Runtime`))return;
    const url=`/api/runtime-sites/${encodeURIComponent(s.site_id)}/revision/${encodeURIComponent(s.revision_id)}/working-copy`;
    try{await api(url,'POST',{overwrite:false});}
    catch(e){
      if(!String(e.message).includes('working_copy_exists'))throw e;
      if(!confirm('พบ Candidate เดิมอยู่แล้ว\nหากเริ่มใหม่ Candidate เดิมจะถูก Archive ไป Trash และอาจสูญเสียงานที่ยังไม่ได้ Publish\nยืนยันจริงหรือไม่?'))return;
      await api(url,'POST',{overwrite:true});
    }
    await load();
  }
  const ctx=()=>{if(!current?.editable)throw Error('ต้องสร้าง Working Copy ก่อน');return {
    site_id:current.site_id,revision_id:current.revision_id,expected_digest:current.camera_digest,
  };};
  async function save(){
    const body=ctx();
    const data={camera_ip:$('v25-camera_ip').value.trim(),camera_port:$('v25-camera_port').value.trim(),
      rtsp_port:$('v25-rtsp_port').value.trim(),rtsp_path:$('v25-rtsp_path').value.trim()};
    const u=$('v25-camera-username').value,p=$('v25-camera-password').value;
    if(u)data.camera_user=u;
    if(p)data.camera_password=p;
    const ip=/^(?:\d{1,3}\.){3}\d{1,3}$/;
    if(!ip.test(data.camera_ip))throw Error('ต้องกรอก Camera IPv4');
    if(!data.rtsp_path.startsWith('/'))throw Error('RTSP Path ต้องขึ้นต้นด้วย /');
    for(const k of ['camera_port','rtsp_port'])if(!/^\d+$/.test(data[k])||Number(data[k])<1||Number(data[k])>65535)throw Error('Port ไม่ถูกต้อง');
    if(!confirm(`บันทึกการเชื่อมต่อกล้องลง Working Copy เท่านั้น?\nIP: ${data.camera_ip}\nหลังบันทึกจะต้อง Test Camera ใหม่ แล้วรับรอง LAB Trial ก่อน Publish`))return;
    await api('/api/phase45/active/camera','PATCH',{...body,...data});
    await load();say('บันทึก Camera Draft สำเร็จ · Camera Test เดิมถูกยกเลิก · Runtime ยังไม่เปลี่ยน');
  }
  async function test(){
    const data=ctx();
    if(!current.changed_from_active)throw Error('ยังไม่มี Camera Connection ที่แก้ไข');
    if(!confirm('คำเตือน: Camera/RTSP Test จะ STOP Detection ชั่วคราว (สูงสุดประมาณ 60 วินาทีหรือมากกว่ารวมเวลาเริ่มบริการ) และพยายาม START กลับ\n\nทำเฉพาะช่วง LAB Maintenance มีผู้เฝ้าระวังสำรอง\nคุณยืนยันให้หยุด Detection ชั่วคราวเพื่อทดสอบหรือไม่?'))return;
    say('ทดสอบ Camera/RTSP อยู่ · Detection อาจหยุดชั่วคราว...');
    try{
      const r=await api('/api/phase45/active/camera/test','POST',{
        ...data,confirm_detection_interruption:true,
      });
      await load();
      say(`Camera Test PASS · Detection Restored=${r.detection_restored} · Runtime Revision เดิมไม่ได้ถูกสลับ`);
    }catch(e){
      await load().catch(()=>{});
      throw Error('Camera Test ไม่ผ่าน หรือยังยืนยันการคืน Detection ไม่ได้: '+e.message);
    }
  }
  async function attest(){
    const data=ctx();
    if(current.mode!=='LAB')throw Error('ข้อยกเว้นนี้ใช้เฉพาะ LAB');
    if(!current.camera_test_passed)throw Error('ต้องผ่าน Camera Test ก่อน');
    if(!$('v25-camera-same').checked||!$('v25-camera-mount').checked||!$('v25-camera-lab').checked)
      throw Error('ต้องยืนยันข้อกำหนด LAB ครบ 3 ข้อ');
    const typed=prompt('พิมพ์ Site ID เพื่อยืนยันว่ากล้องตัวเดิม เลนส์และตำแหน่งติดตั้งไม่เปลี่ยน\nนี่เป็นคำรับรองของผู้ปฏิบัติงาน ไม่ใช่ผลตรวจยืนยันอัตโนมัติ',current.site_id);
    if(typed!==current.site_id)throw Error('Site ID ไม่ตรง ยกเลิก');
    const r=await api('/api/phase45/active/camera/attest','POST',{
      ...data,confirm_site_id:typed,
      same_physical_camera_ack:true,installation_unchanged_ack:true,explicit_lab_only_ack:true,
    });
    await load();say('LAB Connection Maintenance รับรองแล้ว · ยังไม่ Publish / Activate · ต้อง Final Verification → Publish → ตรวจ Activation Plan');
  }
  function boot(){
    const host=$('sf-simple');if(!host||$('sf-v25-camera-panel'))return false;
    const panel=document.createElement('details');panel.id='sf-v25-camera-panel';panel.className='rsm-panel';
    panel.innerHTML=`<summary><strong>Camera Connection Editor — Active Site (v2.5a)</strong></summary>
    <p>ดูค่าเดิมจาก Active Revision · เปลี่ยน IP/Port/RTSP/บัญชีของกล้องตัวเดิมใน Working Copy · ตรวจ Camera Test และ LAB Legacy Dependency ก่อน Publish</p>
    <p id="v25-camera-site">ยังไม่ได้โหลด</p>
    <div class="sf-simple-actions"><button id="v25-camera-load" type="button">โหลดข้อมูลกล้องเดิม</button>
    <button id="v25-camera-draft" type="button" disabled>สร้าง Working Copy</button></div>
    <p id="v25-camera-state"></p>
    <details><summary>ดูการเชื่อมต่อใน Active Revision (ไม่แสดง Credentials)</summary>
      <pre id="v25-camera-active" style="overflow:auto;max-height:220px">-</pre></details>
    <div class="sf-simple-grid">
      <label>Camera IP (IPv4)<input id="v25-camera_ip" placeholder="192.168.0.100" disabled/></label>
      <label>HTTP Port<input id="v25-camera_port" type="number" min="1" max="65535" disabled/></label>
      <label>RTSP Port<input id="v25-rtsp_port" type="number" min="1" max="65535" disabled/></label>
      <label>RTSP Path<input id="v25-rtsp_path" placeholder="/tcp/av0_0" disabled/></label>
      <label>Username ใหม่ (เว้นว่างเพื่อคงค่าเดิม)<input id="v25-camera-username" autocomplete="off" disabled/></label>
      <label>Password ใหม่ (เว้นว่างเพื่อคงค่าเดิม)<input id="v25-camera-password" type="password" autocomplete="new-password" disabled/></label>
    </div>
    <p id="v25-camera-userhint">ยังไม่โหลด</p>
    <div class="sf-simple-actions"><button id="v25-camera-save" type="button" disabled>บันทึก Camera Draft</button>
      <button id="v25-camera-test" type="button" disabled>ทดสอบกล้อง / RTSP (Detection หยุดชั่วคราว)</button></div>
    <div style="border:1px solid var(--border,#7776);border-radius:10px;padding:12px;margin-top:12px">
      <strong>LAB Same-Camera Attestation — ก่อน Publish Legacy Trial</strong>
      <p>ใช้ได้เฉพาะการเปลี่ยนการเชื่อมต่อของกล้องตัวเดิม หากเปลี่ยนตัวกล้อง เลนส์ มุม/จุดติดตั้ง หรือ PTZ Calibration ต้องทำ Calibration/Geometry ใหม่ ห้ามใช้การรับรองนี้แทนการตรวจภาคสนาม</p>
      <label style="display:block"><input id="v25-camera-same" type="checkbox"/> ยืนยันว่าเป็นกล้อง PTZ ตัวเดิม ไม่เปลี่ยนตัวกล้องหรือเลนส์</label>
      <label style="display:block"><input id="v25-camera-mount" type="checkbox"/> ยืนยันว่าไม่เปลี่ยนตำแหน่ง มุมยึด/ทิศทาง และ Preset Mapping</label>
      <label style="display:block"><input id="v25-camera-lab" type="checkbox"/> ยอมรับว่าข้อมูล Geometry เดิมยังเป็น LAB และไม่ใช่ Production certification</label>
      <button id="v25-camera-attest" type="button" disabled>ยืนยัน Same-Camera LAB Maintenance</button>
    </div>
    <pre id="v25-camera-message" aria-live="polite">Unlock Manager แล้วกดโหลดข้อมูลกล้อง</pre>
    <p>หลังยืนยัน: ไปที่ Tests → Final Verification → Publish New Revision → ตรวจ Activation Plan (ห้าม Activate จนกว่าจะตรวจค่าครบ)</p>`;
    host.append(panel);
    const safe=fn=>async()=>{try{await fn();}catch(e){say('ERROR: '+e.message);}};
    $('v25-camera-load').onclick=safe(load);
    $('v25-camera-draft').onclick=safe(draft);
    $('v25-camera-save').onclick=safe(save);
    $('v25-camera-test').onclick=safe(test);
    $('v25-camera-attest').onclick=safe(attest);
    panel.addEventListener('toggle',()=>{if(panel.open&&!current)safe(load)();});
    return true;
  }
  let count=0;const timer=setInterval(()=>{if(boot()||++count>150)clearInterval(timer);},150);
})();
