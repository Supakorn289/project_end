(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const uri = encodeURIComponent;
  const keys = ['x_a_px', 'y_a_px', 'x_b_px', 'y_b_px'];
  const settingKeys = [
    ['ALERT_COOLDOWN_SEC', 'Alert cooldown', 0, 3600],
    ['ALERT_DEDUP_IOU_THRESHOLD', 'Alert dedup IoU', 0, 1],
    ['FUSION_ANCHOR_MAX_AGE_SEC', 'Fusion anchor max age', 1, 120],
    ['FUSION_PENDING_SAFETY_SEC', 'Fusion pending safety', 1, 600],
  ];
  let editor = null;
  let settings = null;
  let loadedIdentity = null;
  let chosen = null;
  let busy = false;
  let loading = false;
  let dirty = false;
  let draftStarted = false;
  const el = (name, content, className) => {
    const node = document.createElement(name);
    if (className) node.className = className;
    node.textContent = content == null ? '—' : String(content);
    return node;
  };
  const txt = (id, value) => { const node = $(id); if (node) node.textContent = String(value ?? '—'); };
  const status = (value, kind = 'info') => {
    txt('sf27-status', value);
    $('sf27-status').dataset.kind = kind;
  };
  const same = (a, b) => a && b && a.site_id === b.site_id && a.revision_id === b.revision_id;
  const currentPair = () => ({site_id: editor?.site_id, revision_id: editor?.revision_id});
  async function api(path, method = 'GET', payload) {
    const auth = await fetch('/api/auth/session', {credentials:'same-origin',cache:'no-store'});
    if (!auth.ok) throw new Error('Manager Session ไม่พร้อม');
    const session = await auth.json();
    if (!session.authenticated || !session.csrf) throw new Error('กรุณา Unlock Manager');
    const headers = {'Accept':'application/json'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = session.csrf;
    }
    const response = await fetch(path, {method, headers,credentials:'same-origin',cache:'no-store',
      body: payload === undefined ? undefined : JSON.stringify(payload)});
    let data;
    try { data = await response.json(); } catch { throw new Error(`HTTP ${response.status}: invalid JSON`); }
    if (!response.ok || data?.ok === false) throw new Error(String(data?.error || data?.reason || `HTTP ${response.status}`));
    return data;
  }
  function setActions() {
    const canEdit = Boolean(editor?.editable && settings?.editable && same(editor,settings) && !busy && !loading);
    $('sf27-draft').disabled = busy || loading || !editor || canEdit || editor?.editable || draftStarted;
    $('sf27-reload').disabled = busy || loading;
    $('sf27-add').disabled = !canEdit;
    $('sf27-update').disabled = !canEdit || !chosen;
    $('sf27-delete').disabled = !canEdit || !chosen;
    $('sf27-settings-save').disabled = !canEdit || !settingsChanged();
    $('sf27-wizard').disabled = !editor || busy || loading;
    $('sf27-diff').disabled = !editor || busy || loading;
  }
  function renderOverview() {
    if (!editor) return;
    txt('sf27-identity', `${editor.site_id} / ${editor.revision_id}`);
    txt('sf27-source', `Geometry: ${editor.source} · Settings: ${settings.source} · ${editor.editable && settings.editable ? 'EDITABLE DRAFT' : 'READ ONLY'}`);
    txt('sf27-dirty', editor.geometry_dirty
      ? 'GEOMETRY DIRTY — ต้อง Solve และทำ Independent Holdout / Final Verification ใหม่'
      : 'Geometry ยังไม่ได้ถูกแก้ผ่าน Editor รอบนี้ (ต้องตรวจ Verification Gate อีกครั้งก่อน Publish)');
    const o = editor.overview || {};
    const sections = [
      ['Camera', o.camera, ['ip','http_port','rtsp_port','rtsp_path','credentials_configured']],
      ['Intrinsics', o.intrinsics, ['status','frame_width','frame_height','fx_px','fy_px','cx_px','cy_px','valid_for_production']],
      ['Distance', o.distance, ['status','pixel_rmse','min_distance_m','max_distance_m','points']],
      ['Geometry', o.geometry, ['model','status','presets','holdout_passed']],
      ['True North / Site', o.site, ['north_offset_deg','measured_preset1_bearing_deg','hfov_deg','frame_width','frame_height']],
      ['Notifications', o.telegram, ['configured','chat_configured']],
    ];
    const cards = $('sf27-cards'); cards.replaceChildren();
    for (const [name, data, fields] of sections) {
      const card = el('section', '', 'sf27-card');
      card.append(el('h4',name));
      for (const field of fields) {
        const row = el('div','','sf27-data-row');
        row.append(el('span',field),el('strong', data?.[field] ?? '—'));
        card.append(row);
      }
      cards.append(card);
    }
    const legacy = o.legacy_geometry_input_values || {};
    const summary = Object.entries(legacy).map(([name, data]) => `${name}: ${Array.isArray(data) ? data.length : Object.keys(data || {}).length} entries`).join(' · ');
    txt('sf27-legacy-note', summary || 'ไม่พบ Legacy Geometry Input ใน Active Revision');
    // Historical input data may not have the same schema as editable Wizard marks.
    txt('sf27-legacy-json', JSON.stringify(legacy, null, 2));
  }
  function renderMarks() {
    const list = $('sf27-marks'); list.replaceChildren();
    const marks = editor?.marks || {};
    let count = 0;
    for (const phase of ['train','holdout']) {
      for (const [pair, arr] of Object.entries(marks[phase] || {}).sort((a,b)=>a[0].localeCompare(b[0]))) {
        if (!Array.isArray(arr)) continue;
        arr.forEach((mark, index) => {
          ++count;
          const row = el('div','','sf27-mark-row');
          const label = el('span',`${phase.toUpperCase()} · P${pair} · #${index + 1} — ${keys.map(k => `${k}=${mark[k] ?? '?'}`).join(' · ')}`);
          const action = el('button','เลือกแก้ไข');action.type='button';
          action.disabled = !editor.editable || !settings?.editable;
          action.onclick = () => {
            chosen = {phase,pair,index,original: {...mark}};
            $('sf27-phase').value = phase;
            $('sf27-pair').value = pair;
            keys.forEach(k => { $('sf27-'+k).value = mark[k]; });
            txt('sf27-selection', `เลือก ${phase} · ${pair} · Index ${index} (เริ่ม 0)`);
            previewDiff(); setActions();
          };
          row.append(label,action); list.append(row);
        });
      }
    }
    if (!count) list.append(el('p','ไม่พบ Wizard Marks — โปรดตรวจ Legacy Geometry Inputs (Read-only) ก่อน ไม่ควรนำ Coordinates คนละ schema มาใส่อัตโนมัติ'));
    txt('sf27-mark-count', `${count} Marks · ${editor?.source || 'UNKNOWN'}`);
  }
  function renderSettings() {
    const list = $('sf27-settings');list.replaceChildren();
    for (const [key,label,min,max] of settingKeys) {
      const field = el('label','','sf27-field');
      field.append(el('span',`${label} (${key})`));
      const input = document.createElement('input');
      input.id = `sf27-setting-${key}`;
      input.type = 'number'; input.step = 'any'; input.min = String(min);input.max = String(max);
      input.value = settings.values?.[key] ?? '';
      input.addEventListener('input',()=>{ previewDiff();setActions(); });
      field.append(input);
      list.append(field);
    }
    txt('sf27-setting-source', `Origin: ${settings.source} · ${settings.working_state || 'No Working Copy'} · locked: ${(settings.locked_keys || []).join(', ')}`);
  }
  function formMark() {
    const phase = $('sf27-phase').value;
    const pair = $('sf27-pair').value.trim();
    if (!['train','holdout'].includes(phase) || !/^[1-9]-[1-9]$/.test(pair) || pair[0] === pair[2])
      throw new Error('Phase หรือ Preset Pair ไม่ถูกต้อง (ตัวอย่าง 1-2)');
    const mark = {};
    for (const key of keys) {
      const input = $('sf27-' + key);
      const raw = input.value.trim();
      if (!raw || !input.checkValidity() || !Number.isFinite(Number(raw))) throw new Error('พิกัด ' + key + ' ไม่ถูกต้อง');
      mark[key] = Number(raw);
    }
    return {phase,pair,mark};
  }
  function inputSettings() {
    const vals = {};
    for (const [key,,min,max] of settingKeys) {
      const input = $('sf27-setting-'+key);
      if (!input) throw new Error('Settings ยังไม่โหลด');
      const raw = input.value.trim();
      const number = Number(raw);
      if (!raw || !Number.isFinite(number) || number < min || number > max || !input.checkValidity())
        throw new Error(`${key} ต้องอยู่ระหว่าง ${min} ถึง ${max}`);
      vals[key] = raw;
    }
    if (Number(vals.FUSION_PENDING_SAFETY_SEC) < Number(vals.FUSION_ANCHOR_MAX_AGE_SEC))
      throw new Error('Pending Safety ต้องไม่น้อยกว่า Anchor Max Age');
    return vals;
  }
  function settingsChanged() {
    try {const vals=inputSettings();return settingKeys.some(([k])=>Number(vals[k])!==Number(settings?.values?.[k]));}
    catch {return false;}
  }
  function previewDiff() {
    let mark = 'ยังไม่เลือก Mark';
    try {
      const next = formMark();
      mark = chosen
        ? `BEFORE ${JSON.stringify(chosen.original)}\nAFTER  ${JSON.stringify(next.mark)}\nPhase/Pair BEFORE ${chosen.phase}/${chosen.pair} AFTER ${next.phase}/${next.pair}`
        : `ADD PREVIEW ${next.phase}/${next.pair}: ${JSON.stringify(next.mark)}`;
    } catch (error) {mark = 'Mark: ' + error.message;}
    let diff = '';
    if (settings) {
      try {
        const vals = inputSettings();
        diff = settingKeys.filter(([k])=>Number(vals[k])!==Number(settings.values?.[k]))
          .map(([k])=>`${k}: ${settings.values?.[k] ?? '—'} → ${vals[k]}`).join('\n') || 'Settings: ไม่มีการเปลี่ยน';
      } catch (error) {diff = 'Settings: ' + error.message;}
    }
    txt('sf27-diff-preview', mark + '\n\n' + diff);
  }
  async function activeGuard() {
    const inventory = await api('/api/runtime-sites');
    if (!inventory || inventory.ok !== true) throw new Error('Runtime Inventory ไม่พร้อม');
    if (inventory.active_site !== editor?.site_id || inventory.active_revision !== editor?.revision_id)
      throw new Error('Active Site/Revision เปลี่ยนแล้ว — กรุณาโหลดค่าใหม่');
  }
  async function reload() {
    if (busy || loading) return;
    loading = true;setActions(); status('กำลังโหลด Active Revision และ Settings (Read-only)...');
    try {
      const [geom, tune, inventory] = await Promise.all([
        api('/api/phase45/active/editor'),api('/api/phase45/site-settings'),api('/api/runtime-sites')
      ]);
      if (!geom.ok || !tune.ok || !inventory.ok || !same(geom,tune) ||
          inventory.active_site !== geom.site_id || inventory.active_revision !== geom.revision_id)
        throw new Error('ACTIVE_IDENTITY_MISMATCH — ข้อมูลจาก APIs ไม่ตรงกัน');
      editor = geom;settings = tune;
      loadedIdentity = {site_id:geom.site_id,revision_id:geom.revision_id};
      chosen = null;dirty = false;draftStarted = false;
      txt('sf27-selection','ยังไม่ได้เลือก Mark');
      renderOverview();renderMarks();renderSettings();previewDiff();
      status('โหลดข้อมูลเดิมสำเร็จ — ยังไม่มีการแก้ไข Live Runtime','success');
    } catch (error) {
      editor = null; settings = null; loadedIdentity = null; chosen = null;
      $('sf27-marks').replaceChildren();$('sf27-settings').replaceChildren();
      status('ERROR: '+error.message,'error');
    } finally {loading = false;setActions();}
  }
  async function action(fn) {
    if (busy || loading) return;
    busy = true;setActions();
    try { await fn(); }
    catch (error) {status('ERROR: '+error.message,'error');}
    finally {busy = false;setActions();}
  }
  async function createDraft() {
    if (!editor || !settings) throw new Error('กด Load ก่อน');
    await activeGuard();
    if (editor.editable || settings.editable) throw new Error('Draft ที่แก้ไขได้มีอยู่แล้ว หรือ State ไม่ตรงกัน');
    if (!window.confirm(`สร้าง Working Copy ของ Active Revision?\n${editor.site_id} / ${editor.revision_id}\nค่า Runtime จริงยังไม่เปลี่ยน`)) return;
    draftStarted = true;setActions();
    try {
      await api(`/api/runtime-sites/${uri(editor.site_id)}/revision/${uri(editor.revision_id)}/working-copy`, 'POST', {overwrite:false});
      status('สร้าง Working Copy แล้ว กำลังโหลดใหม่...', 'success');
    } catch (error) {draftStarted = false; throw error;}
    // Defer refresh until after busy action is released.
    return true;
  }
  async function editMark(type) {
    if (!editor?.editable || !settings?.editable) throw new Error('Active Working Copy ยังไม่พร้อม');
    await activeGuard();
    const next = formMark();
    if (type !== 'add' && !chosen) throw new Error('เลือกรายการ Mark เดิมก่อน');
    if (type !== 'add' && (chosen.phase !== next.phase || chosen.pair !== next.pair))
      throw new Error('การแก้ไข Mark เดิมห้ามเปลี่ยน Phase/Pair; ให้ลบและเพิ่มใหม่');
    const payload = {site_id:editor.site_id,revision_id:editor.revision_id,
      expected_digest:editor.geometry_digest,action:type,phase:next.phase,pair:next.pair};
    if (type !== 'add') payload.index = chosen.index;
    if (type !== 'delete') payload.mark = next.mark;
    if (settingsChanged() && !window.confirm('มี Settings ที่แก้ในฟอร์มแต่ยังไม่ Save\nหลังบันทึก Mark จะโหลดค่าเดิมใหม่และทิ้งค่าในฟอร์ม ต้องการดำเนินการต่อหรือไม่?')) return false;
    if (!window.confirm(`${type.toUpperCase()} Landmark ของ Active Working Copy?\n${next.phase} / ${next.pair}\nต้อง Solve Geometry และ Verify ใหม่ก่อน Publish`)) return false;
    const response = await api('/api/phase45/active/marks','POST',payload);
    if (response.runtime_changed !== false || response.geometry_dirty !== true)
      throw new Error('Mutation response ไม่ยืนยันความปลอดภัย; ตรวจระบบก่อนดำเนินการต่อ');
    dirty = true;
    return true;
  }
  async function saveSettings() {
    if (!editor?.editable || !settings?.editable) throw new Error('Active Working Copy ยังไม่พร้อม');
    const values = inputSettings();
    if (!settingsChanged()) return false;
    await activeGuard();
    const changes = settingKeys.filter(([k])=>Number(values[k])!==Number(settings.values?.[k])).map(([k])=>k);
    if (!window.confirm(`แก้ Detection/Fusion Settings เฉพาะ Working Copy?\n${changes.join('\n')}\n\nต้อง Verify → Publish → Activate ก่อนมีผลจริง`)) return false;
    const response = await api('/api/phase45/site-settings','POST',{
      site_id:settings.site_id,revision_id:settings.revision_id,
      values,expected_digest:settings.expected_digest
    });
    if (response.runtime_changed !== false) throw new Error('Settings response ไม่ยืนยัน Runtime isolation');
    return true;
  }
  function linkWizard() {
    if (!editor || !loadedIdentity) return;
    window.location.assign(`/setup-wizard?mode=existing&site=${uri(editor.site_id)}`);
  }
  function tidyLegacy(host) {
    const advanced = document.createElement('details');advanced.id='sf27-advanced';
    advanced.append(el('summary','เครื่องมือเดิม / Advanced Site Manager (เปิดเมื่อต้องสร้าง Site หรือกู้คืนข้อมูล)'));
    const existing = [...host.children].filter(child => child.id !== 'sfw26' && child.id !== 'sf27-advanced');
    existing.forEach(child => advanced.append(child));
    const simple = $('sf-simple');
    if (simple) advanced.append(simple);
    host.append(advanced);
    // The v2.6 create button delegates to the legacy creation flow; reveal it first.
    $('sfw26-new')?.addEventListener('click',()=>{advanced.open=true;},true);
  }
  function mount() {
    const host = $('runtime-site-manager');const panel = $('sfw26');
    if (!host || !panel) return false;
    if ($('sf27')) return true;
    const div = document.createElement('section');div.id='sf27';
    div.innerHTML = `<header class="sf27-header"><div><h3>Active Site Calibration Editor <small>v2.7</small></h3>
      <p>ค่าเดิมจาก Revision · Working Copy · Correlation Marks · Fusion/Alert Settings</p></div>
      <button id="sf27-reload" type="button">โหลดค่าเดิม (Read-only)</button></header>
      <div class="sf27-id"><b id="sf27-identity">ยังไม่โหลด</b><span id="sf27-source">—</span><span id="sf27-dirty">—</span></div>
      <div id="sf27-cards" class="sf27-cards"></div>
      <details class="sf27-details"><summary>Legacy Geometry Inputs เดิม (Read-only / ห้าม Import อัตโนมัติ)</summary>
        <p id="sf27-legacy-note"></p><pre id="sf27-legacy-json">—</pre></details>
      <div class="sf27-toolbar"><button id="sf27-draft" type="button" disabled>สร้าง Active Working Copy</button>
        <button id="sf27-wizard" type="button" disabled>Setup Wizard: Camera / PTZ / Intrinsics / Distance / Verification</button>
        <button id="sf27-diff" type="button">ดู Before / After Diff</button></div>
      <div class="sf27-columns"><section class="sf27-box"><h4>Correlation / Geometry Marks</h4>
        <p id="sf27-mark-count">—</p><div id="sf27-marks" class="sf27-marks"></div>
        <p id="sf27-selection">ยังไม่ได้เลือก Mark</p>
        <div class="sf27-form"><label>Phase<select id="sf27-phase"><option value="train">Train</option><option value="holdout">Holdout</option></select></label>
        <label>Preset Pair<input id="sf27-pair" value="1-2" pattern="[1-9]-[1-9]" aria-label="Preset Pair เช่น 1-2"></label>
        <label>X A (px)<input id="sf27-x_a_px" type="number" min="0" step="any"></label>
        <label>Y A (px)<input id="sf27-y_a_px" type="number" min="0" step="any"></label>
        <label>X B (px)<input id="sf27-x_b_px" type="number" min="0" step="any"></label>
        <label>Y B (px)<input id="sf27-y_b_px" type="number" min="0" step="any"></label></div>
        <div class="sf27-buttons"><button id="sf27-add" type="button" disabled>เพิ่ม Mark</button>
          <button id="sf27-update" type="button" disabled>แก้ Mark</button>
          <button id="sf27-delete" class="sf27-danger" type="button" disabled>ลบ Mark</button></div>
        <p class="sf27-warning">ทุกครั้งที่แก้ Marks จะ invalidate Solver Result และบังคับ Verify ใหม่</p>
      </section><section class="sf27-box"><h4>Detection / Fusion Settings</h4>
        <p id="sf27-setting-source">—</p><div id="sf27-settings" class="sf27-form"></div>
        <button id="sf27-settings-save" type="button" disabled>บันทึก Settings ลง Working Copy</button>
        <p class="sf27-warning">ค่า Threshold ของโมเดลถูกล็อก — ไม่อนุญาตให้แก้จาก Editor นี้</p>
      </section></div>
      <details class="sf27-details" id="sf27-diff-details"><summary>Before / After Diff (Preview เท่านั้น)</summary><pre id="sf27-diff-preview">—</pre></details>
      <p id="sf27-status" class="sf27-status" role="status" aria-live="polite">กดโหลดค่าเดิมก่อนเริ่ม</p>
      <p class="sf27-footer">การบันทึก Draft ไม่เปลี่ยน Active Runtime: ต้อง Recompute → Verify → Publish Revision → Activation Plan → Activate</p>`;
    panel.insertBefore(div, $('sfw26-legacy'));
    tidyLegacy(host);
    $('sf27-reload').addEventListener('click',()=>reload());
    $('sf27-draft').addEventListener('click',()=>action(async()=>{
      const created = await createDraft();
      if (created) setTimeout(()=>reload(),0);
    }));
    for (const type of ['add','update','delete']) $('sf27-'+type).addEventListener('click',()=>action(async()=>{
      const result = await editMark(type);if(result) setTimeout(()=>reload(),0);
    }));
    $('sf27-settings-save').addEventListener('click',()=>action(async()=>{
      const result = await saveSettings();if(result) setTimeout(()=>reload(),0);
    }));
    $('sf27-wizard').onclick = linkWizard;
    $('sf27-diff').onclick = () => {previewDiff();$('sf27-diff-details').open=true;};
    ['sf27-phase','sf27-pair',...keys.map(k=>'sf27-'+k)].forEach(id=>{
      $(id).addEventListener('input',previewDiff);
    });
    setActions();
    reload();
    return true;
  }
  let attempts = 0;
  function boot() {
    const id=setInterval(()=>{if(mount() || ++attempts>150) clearInterval(id);},150);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
