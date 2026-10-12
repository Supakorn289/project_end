(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const esc = encodeURIComponent;
  async function request(path, method='GET', payload) {
    const session = await fetch('/api/auth/session', {credentials:'same-origin', cache:'no-store'}).then(r => r.json());
    if (!session.authenticated || !session.csrf) throw Error('กรุณา Unlock Manager ก่อน');
    const response = await fetch(path, {
      method, credentials:'same-origin', cache:'no-store',
      headers: {'Content-Type':'application/json', ...(method!=='GET' ? {'X-CSRF-Token':session.csrf} : {})},
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    const obj = await response.json();
    if (!response.ok || obj.ok === false) throw Error(obj.error || `HTTP ${response.status}`);
    return obj;
  }
  const selected = () => ({site:byId('sf-simple-site')?.value || '', rev:byId('sf-simple-revision')?.value || ''});
  function report(msg) {
    const node=byId('sf-v22-result');
    if(node) node.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
  }
  function showReuse(result) {
    const node=byId('sf-v22-overlap');
    if (!node) return;
    const matches=result?.telegram_reuse?.matches || [];
    if (!matches.length) {
      node.textContent='ไม่พบ Telegram Bot หรือ Chat ID ที่ซ้ำกับ Site อื่นใน Revision ที่ตรวจ';
      return;
    }
    const description=matches.map(m => {
      const parts=(m.shared || []).map(x=>x==='bot'?'Bot':'Chat ID');
      return `${m.site_name || m.site_id} (${m.site_id}) — ${parts.join(' + ')}${m.active?' [กำลังใช้งาน]':''}`;
    });
    node.textContent=`พบการใช้ Telegram ซ้ำกับ Site:
${description.join('\n')}
อนุญาตให้ใช้ซ้ำได้ แต่การแจ้งเตือนของ Site เหล่านี้อาจเข้าปลายทางเดียวกัน`;
  }
  function clearReuse() {
    const node=byId('sf-v22-overlap'); if (node) node.textContent='';
  }
  async function checkReuse() {
    const {site,rev}=selected();
    if (!site || !rev) throw Error('เลือก Site และ Revision ก่อน');
    const token=byId('sf-v22-token').value.trim();
    const chat=byId('sf-v22-chat').value.trim();
    if (!token || !chat) throw Error('กรอก Bot Token และ Chat ID ก่อนตรวจการใช้ซ้ำ');
    const result=await request(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/notification-reuse-check`, 'POST', {
      telegram_token:token, telegram_chat_id:chat
    });
    if (selected().site!==site || selected().rev!==rev || result.site_id!==site || result.revision_id!==rev)
      throw Error('Site/Revision เปลี่ยนระหว่างตรวจ');
    showReuse(result);
    report({ok:true, duplicate_check_only:true, telegram_reuse:result.telegram_reuse,
            telegram_test_sent:false, runtime_changed:false});
    return result;
  }
  async function review() {
    const {site,rev}=selected();
    if (!site || !rev) throw Error('เลือก Site และ Revision ก่อน');
    const value=await request(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/notification-fork-preview`);
    if (selected().site!==site || selected().rev!==rev || value.site_id!==site || value.revision_id!==rev)
      throw Error('Site/Revision เปลี่ยนหรือผลลัพธ์ไม่ตรง โปรดตรวจใหม่');
    report(value);
    return value;
  }
  async function testAndPublish() {
    const v=await review();
    if (!v.eligible) throw Error('Revision นี้ยังไม่พร้อมสำหรับ Notification Fork');
    const {site,rev}=selected();
    const token=byId('sf-v22-token').value.trim();
    const chat=byId('sf-v22-chat').value.trim();
    if(!token || !chat) throw Error('กรอก Bot Token และ Chat ID ของ Site เป้าหมาย');
    if(!confirm(`ส่ง Telegram Test ไปยัง Chat ที่ระบุ แล้วสร้าง Revision ใหม่ให้ ${site} โดยไม่ Activate ใช่หรือไม่?`)) return;
    if(prompt(`พิมพ์ Site ID ยืนยัน:\n${site}`)!==site) {report('ยกเลิก: Site ID ไม่ตรง'); return;}
    if (selected().site!==site || selected().rev!==rev) throw Error('Site/Revision เปลี่ยนระหว่างยืนยัน');
    const publishButton=byId('sf-v22-publish');
    publishButton.disabled=true;
    report('กำลังทดสอบ Telegram และสร้าง Immutable Revision (หากส่งข้อความไม่สำเร็จ จะไม่สร้าง Revision)');
    try {
      const result=await request(`/api/runtime-sites/${esc(site)}/revision/${esc(rev)}/notification-fork`, 'POST', {
        confirm_site_id:site, confirm_revision_id:rev, telegram_token:token, telegram_chat_id:chat
      });
      byId('sf-v22-token').value='';
      byId('sf-v22-chat').value='';
      if (result.site_id!==site || result.parent_revision!==rev) throw Error('Revision identity mismatch');
      showReuse(result);
      report({...result, next:'กด รีเฟรชสถานะ เลือก Revision ใหม่ แล้วตรวจ Activation Plan; ยังไม่ Activate'});
    } finally {publishButton.disabled=false;}
  }
  function init() {
    const existing=byId('sf-simple');
    if(!existing || byId('sf-v22-panel')) return !!byId('sf-v22-panel');
    const details=document.createElement('details');
    details.id='sf-v22-panel';
    details.className='rsm-panel';
    details.innerHTML=`<summary>ตั้งค่า Telegram แยกตาม Site (v2.2)</summary>
      <p class="rsm-sub">ใช้ Site และ Revision ที่เลือกด้านบน · กรอก Bot/Chat สำหรับ Site ที่ยังไม่ Active (ซ้ำกับ Site อื่นได้และจะรายงานชื่อ Site ที่ซ้ำ) · ส่งข้อความทดสอบก่อน Publish · ไม่สลับ Runtime อัตโนมัติ</p>
      <div class="sf-simple-grid">
      <label>Bot Token ของ Site เป้าหมาย <input type="password" id="sf-v22-token" autocomplete="new-password" spellcheck="false" placeholder="Bot Token (ใช้ร่วมกับ Site อื่นได้)" /></label>
      <label>Chat ID ของ Site เป้าหมาย <input type="text" id="sf-v22-chat" autocomplete="off" spellcheck="false" placeholder="Chat ID (ใช้ร่วมกันได้)" /></label>
      </div>
      <div class="sf-simple-actions"><button type="button" id="sf-v22-preview">ตรวจ Revision ต้นทาง (ไม่ส่งข้อความ)</button>
      <button type="button" id="sf-v22-reuse-check">ตรวจ Bot/Chat ที่ใช้ซ้ำ (ไม่ส่งข้อความ)</button>
      <button type="button" id="sf-v22-publish">ทดสอบ Telegram + สร้าง Revision ใหม่</button></div>
      <p class="sf-simple-caution">LAB เท่านั้น · Bot/Chat ใช้ซ้ำข้าม Site ได้โดยแจ้งเตือน · ต้องใช้บัญชีที่ได้รับอนุญาต · ไม่คัดลอกรหัสจาก Active Site · Historical Geometry ไม่ผ่านการรับรอง Production</p>
      <p id="sf-v22-overlap" class="sf-simple-caution" role="status" aria-live="polite"></p>
      <pre id="sf-v22-result" aria-live="polite">ยังไม่ได้ตรวจสอบ</pre>`;
    existing.append(details);
    for (const [name,func] of [['sf-v22-preview',review],['sf-v22-reuse-check',checkReuse],['sf-v22-publish',testAndPublish]]) {
      byId(name).onclick=()=>func().catch(e=>report('ERROR: '+e.message));
    }
    for (const id of ['sf-v22-token','sf-v22-chat','sf-simple-site','sf-simple-revision']) {
      const node=byId(id); if (node) node.addEventListener('change',clearReuse);
    }
    for (const id of ['sf-v22-token','sf-v22-chat']) {
      const node=byId(id); if (node) node.addEventListener('input',clearReuse);
    }
    return true;
  }
  let remaining=0;
  const timer=setInterval(()=>{if(init() || ++remaining>80)clearInterval(timer);},150);
})();
