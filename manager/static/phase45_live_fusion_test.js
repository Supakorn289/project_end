(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const presets = Array.from({length:9},(_,i)=>i+1);
  let planned = null, current = null, timer = null;
  function selected(){return [1,2,3].map(i => Number($('sf-live-p'+i).value));}
  function clearPlan(){planned=null;$('sf-live-start').disabled=true;$('sf-live-ack').checked=false;}
  function show(text){$('sf-live-output').textContent=typeof text==='string'?text:JSON.stringify(text,null,2);}
  async function auth(){
    const r=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
    const j=await r.json();if(!j.authenticated||!j.csrf)throw Error('กรุณา Unlock Manager ก่อน');return j.csrf;
  }
  async function post(path,body){
    const csrf=await auth();
    const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
    const j=await r.json();if(!r.ok||j.ok===false)throw Error([j.error,j.reason].filter(Boolean).join(' — ')||'request_failed');return j;
  }
  function matchedPairs(result) {
    // Count genuine Fusion engine output; never generate a synthetic object ID.
    const rows=Array.isArray(result?.results)?result.results:[];
    const byId=new Map();
    for(const row of rows){
      for(const obs of (row.observations||[])){
        if(!obs?.object_id || !['fire','smoke'].includes(obs.class))continue;
        const id=obs.object_id, key=obs.class+'|'+id;
        if(!byId.has(key))byId.set(key,new Map());
        const slots=byId.get(key), preset=Number(row.preset);
        const prev=slots.get(preset)||false;
        slots.set(preset,prev||obs.fused_measurement===true);
      }
    }
    const pairs=[];
    for(const [key,slots] of byId.entries()){
      if(slots.size<2 || ![...slots.values()].some(Boolean))continue;
      const [type,id]=key.split('|');
      pairs.push({class:type,object_id:id,presets:[...slots.keys()].sort((a,b)=>a-b)});
    }
    return pairs;
  }
  function renderResult(status){
    const twoPresetMatches=matchedPairs(status.result);
    show({status:status.finished?'FINISHED':'RUNNING',site_id:status.site_id,revision_id:status.revision_id,
          two_preset_fusion_confirmed:twoPresetMatches.length>0,two_preset_matches:twoPresetMatches,
          presets:status.presets,stages:status.stages,exit_code:status.exit_code,
          detection_restored:status.detection_restored, result:status.result});
    const summary=$('sf-live-summary');
    summary.textContent=status.finished
      ? ('ผลรวม 3P: '+(status.result?.result||'FAILED_OR_INTERRUPTED')+' | Fusion 2P: '+(twoPresetMatches.length ? twoPresetMatches.map(x=>x.object_id+' '+x.presets.map(p=>'P'+p).join('↔')).join('; ') : 'NOT_CONFIRMED')+' | Detection restored: '+status.detection_restored)
      : ('กำลังทดสอบกล้องจริง — '+(status.stages||[]).slice(-1).join(''));
    if(status.finished){
      clearInterval(timer);timer=null;
      $('sf-live-start').disabled=true;
      const root=$('sf-live-images');root.replaceChildren();
      for(const preset of status.image_presets||[]){
        const cell=document.createElement('div');cell.style.cssText='width:290px;max-width:100%;';
        const label=document.createElement('div');label.textContent='ภาพจริง Preset '+preset;
        const img=document.createElement('img');img.alt='ภาพทดสอบ PTZ Preset '+preset;
        img.src=`/api/phase45/fusion/live/jobs/${encodeURIComponent(current)}/images/${preset}`;
        img.style.cssText='width:100%;height:auto;max-height:220px;object-fit:contain;';
        cell.append(label,img);root.append(cell);
      }
      current=null;planned=null;
      $('sf-live-preview').disabled=false;
      $('sf-live-preview-result').textContent='ทดสอบเสร็จแล้ว เลือก P และตรวจ Preflight เพื่อทดสอบรอบใหม่';
    }
  }
  async function poll(){
    if(!current)return;
    try{
      const r=await fetch('/api/phase45/fusion/live/jobs/'+encodeURIComponent(current),{credentials:'same-origin',cache:'no-store'});
      const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'status_failed');renderResult(j);
    }catch(e){$('sf-live-summary').textContent='ไม่สามารถอ่านผลได้: '+e.message;}
  }
  function boot(){
    const host=$('page-tests');if(!host||$('sf-live-panel'))return false;
    const panel=document.createElement('div');panel.id='sf-live-panel';panel.className='panel';
    panel.innerHTML=`<div class="panel-head"><div><h2>Live Fusion Test — เลือก 3 PTZ Presets</h2>
      <p>กล้อง RTSP จริง + AI Fire/Smoke + Consensus + Cross-Preset Fusion, ไม่ส่ง Telegram · เกณฑ์ Fusion อย่างน้อย 2 Presets</p></div></div>
      <p style="color:#f1be63">ทดสอบ LAB เท่านั้น · ต้องมีภาพไฟ/ควันจำลองที่อยู่นิ่ง · การทดสอบจะหยุด Detection ชั่วคราว</p>
      <div style="display:flex;flex-wrap:wrap;gap:12px;margin:12px 0">
        <label>P แรก <select id="sf-live-p1"></select></label>
        <label>P ที่สอง <select id="sf-live-p2"></select></label>
        <label>P ที่สาม <select id="sf-live-p3"></select></label>
      </div>
      <button id="sf-live-preview" class="action-btn" type="button">ตรวจพื้นที่ทับซ้อน / Preflight (ไม่หมุนกล้อง)</button>
      <pre id="sf-live-preview-result" style="max-height:230px;overflow:auto;white-space:pre-wrap">ยังไม่ได้ตรวจ</pre>
      <label style="display:block;margin:12px 0"><input type="checkbox" id="sf-live-ack"/> ยืนยันว่าทดสอบใน LAB มีการเฝ้าระวังสำรอง ยอมให้ PTZ หมุนและ Detection หยุดชั่วคราว</label>
      <button id="sf-live-start" class="action-btn" type="button" disabled>เริ่มทดสอบกล้องจริง</button>
      <p id="sf-live-summary" aria-live="polite">ยังไม่เริ่ม</p>
      <pre id="sf-live-output" style="max-height:350px;overflow:auto;white-space:pre-wrap">ยังไม่มีผลทดสอบ</pre>
      <div id="sf-live-images" style="display:flex;gap:10px;flex-wrap:wrap"></div>`;
    host.append(panel);
    [1,2,3].forEach((n)=>{
      const sel=$('sf-live-p'+n);
      presets.forEach(p=>{const el=document.createElement('option');el.value=String(p);el.textContent='P'+p;sel.append(el);});
      sel.value=String([4,5,9][n-1]);sel.onchange=()=>{
        clearPlan();$('sf-live-preview-result').textContent='เปลี่ยน Preset แล้ว กรุณาตรวจ Preflight ใหม่';
      };
    });
    $('sf-live-ack').onchange=()=>{$('sf-live-start').disabled=!(planned&&$('sf-live-ack').checked&&!current);};
    $('sf-live-preview').onclick=async()=>{
      clearPlan();const values=selected();const out=$('sf-live-preview-result');out.textContent='กำลังตรวจ...';
      try{const data=await post('/api/phase45/fusion/live/preview',{presets:values});
          if(values.join(',')!==selected().join(','))throw Error('Preset changed during preflight');
          planned=data;out.textContent=JSON.stringify(data,null,2);
      }catch(e){out.textContent='ไม่ผ่าน Preflight: '+e.message;}
    };
    $('sf-live-start').onclick=async()=>{
      if(!planned||!$('sf-live-ack').checked||current)return;
      $('sf-live-start').disabled=true;
      $('sf-live-summary').textContent='กำลังขอสิทธิ์เริ่ม Live Test...';
      try{
        const data=await post('/api/phase45/fusion/live/start',{
          presets:selected(),site_id:planned.site_id,revision_id:planned.revision_id,
          confirmation:'LAB_LIVE_TEST',maintenance_ack:true});
        current=data.job_id;$('sf-live-preview').disabled=true;
        $('sf-live-summary').textContent='เริ่มทดสอบแล้ว';
        await poll();if(current)timer=setInterval(poll,3500);
      }catch(e){$('sf-live-summary').textContent='ไม่สามารถเริ่มได้: '+e.message;current=null;}
    };
    return true;
  }
  let tries=0;const t=setInterval(()=>{if(boot()||++tries>100)clearInterval(t);},150);
})();
