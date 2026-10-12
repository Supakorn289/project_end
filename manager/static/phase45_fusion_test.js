(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let counter=0;
  function boot(){
    const host=$('page-tests');if(!host||$('sf-p45-fusion'))return false;
    const panel=document.createElement('div');panel.id='sf-p45-fusion';panel.className='panel';
    panel.innerHTML=`<div class="panel-head"><div><h2>Fusion 3 Presets — Replay</h2>
      <p>ป้อน Observation จาก 3 Presets เพื่อเรียก CrossPresetObjectFusion จริงโดยไม่หมุนกล้อง ไม่ส่ง Telegram</p></div></div>
      <p>โหมดนี้เป็น REPLAY เท่านั้น ยังไม่ใช่ Live Camera Test</p>
      <textarea id="sf-p45-fusion-input" rows="11" style="width:100%;box-sizing:border-box;background:#09111f;color:#e6edf6;border:1px solid #59667b;padding:10px;font:12px monospace"></textarea>
      <button id="sf-p45-fusion-run" type="button" class="action-btn">รัน Replay 3 Presets (ไม่ใช้กล้อง)</button>
      <pre id="sf-p45-fusion-output" style="white-space:pre-wrap;max-height:360px;overflow:auto">ยังไม่ได้ทดสอบ</pre>`;
    host.append(panel);
    // Example input labelled and editable; NEVER represent as real detections.
    $('sf-p45-fusion-input').value=JSON.stringify({observations:[
      {preset:1,class:'fire',bbox:[580,300,670,390],bearing_deg:20.0,distance_m:4.5,confidence:0.92},
      {preset:2,class:'fire',bbox:[110,300,190,390],bearing_deg:20.5,distance_m:4.6,confidence:0.89},
      {preset:3,class:'fire',bbox:[110,300,190,390],bearing_deg:20.2,distance_m:4.4,confidence:0.91}
    ]},null,2);
    $('sf-p45-fusion-run').onclick=async()=>{
      const out=$('sf-p45-fusion-output');out.textContent='กำลังทดสอบ Replay...';
      try {
        const session=await fetch('/api/auth/session',{credentials:'same-origin'}).then(r=>r.json());
        if(!session.authenticated)throw Error('กรุณา Unlock Manager ก่อน');
        const observations=JSON.parse($('sf-p45-fusion-input').value);
        const r=await fetch('/api/phase45/fusion/replay-three',{method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify(observations)});
        const data=await r.json();out.textContent=JSON.stringify(data,null,2);
      }catch(e){out.textContent='ERROR: '+e.message;}
    };
    return true;
  }
  const timer=setInterval(()=>{if(boot()||++counter>100)clearInterval(timer);},150);
})();
