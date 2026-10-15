"""Phase 4A: active-only historical editor (never mutates live revision).

All mutation requires an existing editable working copy.  No raw environment
or credential JSON is returned to browser.  Geometry edits revoke old solve.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

PAIR = re.compile(r"^[1-9]-[1-9]$")
PHASES = frozenset({"train", "holdout"})
FIELDS = ("x_a_px", "y_a_px", "x_b_px", "y_b_px")


def geometry_digest(geometry):
    obj = {p: geometry.get(p, {}) for p in PHASES}
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def clean_mark(value, width, height):
    if not isinstance(value, dict):
        raise ValueError("mark_must_be_object")
    output = {}
    for key, maximum in (("x_a_px", width), ("y_a_px", height),
                         ("x_b_px", width), ("y_b_px", height)):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("invalid_mark_coordinate:" + key)
        number = float(item)
        if not math.isfinite(number) or number < 0 or number >= maximum:
            raise ValueError("mark_outside_frame:" + key)
        output[key] = number
    return output


def mutate_marks(state, payload, *, width, height):
    """Pure mutation helper; returns changed state. No false solver PASS."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    phase, pair, action = payload.get("phase"), payload.get("pair"), payload.get("action")
    if phase not in PHASES or not isinstance(pair, str) or not PAIR.fullmatch(pair):
        raise ValueError("invalid_phase_or_pair")
    a, b = map(int, pair.split("-"))
    if a == b:
        raise ValueError("pair_must_use_distinct_presets")
    if action not in {"add", "update", "delete"}:
        raise ValueError("unsupported_action")
    result = copy.deepcopy(state)
    geom = result.setdefault("geometry", {})
    phase_data = geom.setdefault(phase, {})
    marks = phase_data.setdefault(pair, [])
    if not isinstance(marks, list):
        raise ValueError("corrupt_mark_list")
    if action == "add":
        if len(marks) >= 30:
            raise ValueError("mark_limit_exceeded")
        marks.append(clean_mark(payload.get("mark"), width, height))
    else:
        index = payload.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(marks):
            raise ValueError("mark_index_out_of_range")
        if action == "update":
            marks[index] = {**marks[index], **clean_mark(payload.get("mark"), width, height)}
        else:
            marks.pop(index)
    # Any historical solver/evidence computed from earlier marks is invalid.
    geom.pop("solver_result", None)
    geom.pop("candidate", None)
    result["phase45_geometry_dirty"] = True
    result["phase45_edit_note"] = "Landmark changed: new geometry solve/validation required"
    return result


def _safe_read(path):
    try:
        if path.is_symlink():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _sanitized_overview(revision_dir):
    artifacts = revision_dir / "artifacts"
    camera = _safe_read(artifacts / "camera_connection.json")
    camera_env = camera.get("runtime_env") or {}
    intrinsics = _safe_read(artifacts / "camera_intrinsics.json")
    distance = _safe_read(artifacts / "distance_global.json")
    geometry = _safe_read(artifacts / "preset_rotation.json")
    site_file = _safe_read(artifacts / "site.json")
    telegram = _safe_read(artifacts / "telegram.json")
    tenv = telegram.get("runtime_env") or telegram
    legacy_inputs = {}
    for label in ("positive_train", "negative_train", "positive_holdout", "negative_holdout"):
        path = artifacts / "geometry_inputs" / (label + ".json")
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 150000:
            legacy_inputs[label] = _safe_read(path)
    return {
        "legacy_geometry_input_values": legacy_inputs,
        "camera": {
            "ip": camera_env.get("CAMERA_IP"),
            "http_port": camera_env.get("CAMERA_PORT"),
            "rtsp_port": camera_env.get("RTSP_PORT"),
            "rtsp_path": camera_env.get("RTSP_PATH"),
            "credentials_configured": bool(camera_env.get("CAMERA_PWD")),
        },
        "intrinsics": {k: intrinsics.get(k) for k in (
            "status", "frame_width", "frame_height", "fx_px", "fy_px", "cx_px", "cy_px", "valid_for_production")},
        "distance": {k: distance.get(k) for k in (
            "H", "K", "pixel_rmse", "min_distance_m", "max_distance_m", "points", "status", "preset")},
        "geometry": {
            "model": geometry.get("model"), "status": geometry.get("status"),
            "presets": len(geometry.get("presets") or {}),
            "holdout_passed": (geometry.get("independent_holdout_gate") or {}).get("passed"),
        },
        "site": {k: site_file.get(k) for k in (
            "north_offset_deg", "measured_preset1_bearing_deg", "hfov_deg", "frame_width", "frame_height")},
        "telegram": {"configured": bool(tenv.get("TELEGRAM_TOKEN") or tenv.get("telegram_token") or tenv.get("token")),
                     "chat_configured": bool(tenv.get("TELEGRAM_CHAT_ID") or tenv.get("telegram_chat_id") or tenv.get("chat_id"))},
    }


def snapshot():
    from manager.services.site_store import get_active_site
    from manager.services.site_registry import list_registered_sites
    from manager.services.revision_engine import REVISION_ROOT
    from manager.services.wizard_store import STATE_DIR
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity

    active = get_active_site() or {}
    site, rev = active.get("site_id"), active.get("revision_id")
    if not site or not rev:
        raise RuntimeError("no_active_runtime")
    if check_revision_source_integrity(site, rev).get("ok") is not True:
        raise RuntimeError("active_revision_integrity_failed")
    base = REVISION_ROOT / site / rev
    if base.is_symlink():
        raise RuntimeError("unsafe_revision_directory")
    record = (list_registered_sites().get("sites") or {}).get(site) or {}
    working = record.get("working_copy") or {}
    editable = (working.get("state") in {"EDITING", "CAMERA_CHANGED", "READY_FOR_VERIFICATION", "CAMERA_TEST_FAILED"}
                and working.get("parent_revision") == rev and not working.get("recovery"))
    if editable:
        state = _safe_read(STATE_DIR / (site + ".json"))
        source = "WORKING_COPY"
    else:
        state = _safe_read(base / "wizard_state.json")
        source = "ACTIVE_REVISION"
    geom = state.get("geometry") or {}
    marks = {p: geom.get(p) or {} for p in ("train", "holdout")}
    sanitized = {p: {k: v for k, v in source_marks.items() if PAIR.fullmatch(k) and isinstance(v, list)}
                 for p, source_marks in marks.items()}
    return {
        "ok": True, "site_id": site, "revision_id": rev,
        "editable": editable, "source": source,
        "working_state": working.get("state"),
        "geometry_dirty": bool(state.get("phase45_geometry_dirty")),
        "geometry_digest": geometry_digest(geom),
        "marks": sanitized,
        "overview": _sanitized_overview(base),
        "runtime_changed": False,
    }


def edit_marks(payload):
    from manager.services.runtime_site_crud import _require_editable_working_copy, _audit
    from manager.services.wizard_store import CANDIDATE_DIR, load_state, STATE_DIR, save_state
    from manager.services.hardware_lock import hardware_lock
    active = get_active_site() or {}
    site = active.get("site_id")
    if not site or payload.get("site_id") != site or payload.get("revision_id") != active.get("revision_id"):
        raise PermissionError("ACTIVE_RUNTIME_IDENTITY_MISMATCH")
    with hardware_lock("phase45:geometry-mark-edit", timeout=3.0):
        # Protect against activation during edit and against inactive-site mutation.
        now = get_active_site() or {}
        if (now.get("site_id"), now.get("revision_id")) != (site, active.get("revision_id")):
            raise PermissionError("ACTIVE_RUNTIME_CHANGED")
        working = _require_editable_working_copy(site)
        if working.get("parent_revision") != active.get("revision_id") or working.get("recovery"):
            raise PermissionError("draft_parent_must_match_active_revision")
        candidate = CANDIDATE_DIR / site
        intrinsics = _safe_read(candidate / "camera_intrinsics.json")
        width, height = intrinsics.get("frame_width"), intrinsics.get("frame_height")
        if not (isinstance(width, int) and isinstance(height, int) and 100 <= width <= 10000 and 100 <= height <= 10000):
            raise RuntimeError("missing_camera_intrinsics_dimensions")
        state = load_state(site)
        digest = geometry_digest(state.get("geometry") or {})
        if payload.get("expected_digest") != digest:
            raise RuntimeError("DRAFT_CHANGED_REFRESH_REQUIRED")
        changed = mutate_marks(state, payload, width=width, height=height)
        save_state(site, changed)
        _audit("phase45_geometry_mark_edit", site_id=site, action_type=payload.get("action"),
               phase=payload.get("phase"), pair=payload.get("pair"), index=payload.get("index"))
        return {"ok": True, "new_digest": geometry_digest(changed.get("geometry") or {}),
                "geometry_dirty": True, "runtime_changed": False,
                "warning": "Geometry must be freshly solved and validated before publishing"}

def invalidate_geometry_state(state):
    """Revoke old derived geometry, including changes through legacy Wizard UI."""
    geom = state.setdefault('geometry', {})
    geom.pop('solver_result', None)
    geom.pop('candidate', None)
    state['phase45_geometry_dirty'] = True
    state['phase45_edit_note'] = 'Landmark changed: new geometry solve/validation required'
    return state


# Stage 2E: Source-session image evidence (strict read-only).
# The historical data has 618 pair correspondences but none of the 18 source
# image pairs is pixel-identical to the current Wizard captures. Never overlay
# legacy marks on current images, infer registration, import, or mutate them.
# The manager runs with ProtectHome=true, so it CANNOT read /home/fire.
# A root-verified, immutable-evidence snapshot is staged outside /home.
# Historical marks and frames remain source-session-only; never import to active.
_LEGACY_ORIGINAL_HOME = Path('/home/fire')
_LEGACY_HOME = Path('/opt/smart-fire-detection-v2/calibration/.manager/legacy-evidence-ro')

def _legacy_mapped_original(value, home):
    raw=Path(str(value))
    # Do not resolve the original /home path: ProtectHome makes it unavailable.
    if not raw.is_absolute() or '..' in raw.parts:
        raise ValueError('LEGACY_ORIGINAL_PATH_INVALID')
    try:
        rel=raw.relative_to(_LEGACY_ORIGINAL_HOME)
    except ValueError as exc:
        raise ValueError('LEGACY_ORIGINAL_PATH_OUT_OF_SCOPE') from exc
    mapped=home.joinpath(*rel.parts)
    _legacy_safe(mapped,home,limit=25_000_000) if mapped.is_file() else None
    if not mapped.resolve(strict=True).is_relative_to(home.resolve(strict=True)):
        raise ValueError('LEGACY_STAGED_PATH_ESCAPE')
    return mapped.resolve(strict=True)

_LEGACY_ROOT = Path('/opt/smart-fire-detection-v2')
_LEGACY_SITE = 'current-site-20260921'
_LEGACY_REV = 'rev-20261009T065702Z-6090a06a5d93'
_LEGACY_GROUPS = {
    'train': {
        'positive': ('final_session_A_path.txt','cross_preset_marks_FINAL_A.json',
                     '89a2cb0124f0757bb5d0b7ac92c1e3d095318ba5a811c350735d949bf1006427'),
        'negative': ('final_negative_A2_path.txt','negative_side_marks_FINAL_A2.json',
                     '69a66af2def8d8052356bcbf3db0f539ed09c8515ecc458e4d866408597edb98'),
    },
    'holdout': {
        'positive': ('final_session_B_path.txt','cross_preset_marks_FINAL_B.json',
                     'f6b6769a56b17d4e3fd1eecd2073e94b38ef006b7089c89331186e94f07a79bc'),
        'negative': ('final_negative_B2_path.txt','negative_side_marks_FINAL_B2.json',
                     'f932fd2e1dddb6cdc434c4a2fab4ac3d4a729792cb45754d5008156096a33979'),
    }
}
_LEGACY_MIXED = {
    'train': ('final_mixed_train_marks_v3.json',
              'ed65c6533c4638059337774c2e55e45ef4708deb6772ab7380517da72cade682'),
    'holdout': ('final_mixed_holdout_marks_v3.json',
                '94d01892ae18ce8cafcfe52434c37218c901a4403aa036835b87cf2068536d27')
}
# (session-step-A, preset-A, session-step-B, preset-B, branch)
_LEGACY_PAIRS = {
    '1-2': (1,1,2,2,'positive'),
    '2-3': (2,2,3,3,'positive'),
    '3-4': (3,3,4,4,'positive'),
    '4-5': (4,4,5,5,'positive'),
    '1-6': (1,1,2,6,'negative'),
    '6-7': (2,6,3,7,'negative'),
    '7-8': (3,7,4,8,'negative'),
    '8-9': (4,8,5,9,'negative'),
    '5-9': (6,5,5,9,'negative'),
}


def _legacy_safe(path, parent, *, limit=25_000_000):
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('LEGACY_UNSAFE_FILE')
        if not path.resolve(strict=True).is_relative_to(parent.resolve(strict=True)):
            raise ValueError('LEGACY_PATH_ESCAPE')
        if path.stat().st_size > limit or path.stat().st_size == 0:
            raise ValueError('LEGACY_SIZE_INVALID')
    except OSError as exc:
        raise ValueError('LEGACY_FILE_UNAVAILABLE') from exc
    return path


def _legacy_sha(path):
    sha=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            sha.update(chunk)
    return sha.hexdigest()


def _legacy_json(path, home, expected):
    _legacy_safe(path,home,limit=5_000_000)
    if _legacy_sha(path)!=expected:
        raise ValueError('LEGACY_SOURCE_SHA_MISMATCH')
    result=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result,dict) or not isinstance(result.get('pairs'),dict):
        raise ValueError('LEGACY_INVALID_MARK_FORMAT')
    return result


def _legacy_json_manifest(path,home):
    _legacy_safe(path,home,limit=200_000)
    obj=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj,dict) or obj.get('format')!='smartfire-legacy-ro-stage2e-v1' or not isinstance(obj.get('files'),dict):
        raise ValueError('LEGACY_STAGED_MANIFEST_INVALID')
    return obj


def _legacy_jpeg_size(path):
    # Standard-library SOF reader; fail closed on malformed/truncated JPEG.
    with path.open('rb') as f:
        if f.read(2)!=b'\xff\xd8':raise ValueError('LEGACY_NOT_JPEG')
        while f.tell()<min(path.stat().st_size,4_000_000):
            b=f.read(1)
            if not b:break
            if b!=b'\xff':continue
            marker=f.read(1)
            while marker==b'\xff':marker=f.read(1)
            if not marker:break
            m=marker[0]
            if m in (0xD8,0xD9,0x01,*range(0xD0,0xD8)):
                if m==0xD9:break
                continue
            length=f.read(2)
            if len(length)!=2:break
            n=int.from_bytes(length,'big')
            if n<2:break
            if m in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
                meta=f.read(5)
                if len(meta)!=5:break
                h=int.from_bytes(meta[1:3],'big')
                w=int.from_bytes(meta[3:5],'big')
                return w,h
            f.seek(n-2,1)
    raise ValueError('LEGACY_INVALID_JPEG_HEADER')


def _legacy_active_gate():
    from manager.services.site_store import get_active_site
    from manager.services.site_lifecycle_v2 import check_revision_source_integrity
    current=get_active_site() or {}
    if (current.get('site_id'),current.get('revision_id'))!=(_LEGACY_SITE,_LEGACY_REV):
        raise PermissionError('LEGACY_REVIEW_REQUIRES_AUDITED_ACTIVE_IDENTITY')
    if check_revision_source_integrity(_LEGACY_SITE,_LEGACY_REV).get('ok') is not True:
        raise PermissionError('LEGACY_ACTIVE_REVISION_INTEGRITY_FAILED')


def legacy_pair_evidence(phase, pair, *, home=None, root=None, enforce_active=True):
    """Strict pinned source/view-only pair; no historical data is ever written."""
    if phase not in _LEGACY_GROUPS or pair not in _LEGACY_PAIRS:
        raise ValueError('LEGACY_PHASE_PAIR_NOT_ALLOWED')
    if enforce_active:_legacy_active_gate()
    home=home or _LEGACY_HOME
    root=root or _LEGACY_ROOT
    step_a,pre_a,step_b,pre_b,branch=_LEGACY_PAIRS[pair]
    pointer,mark_name,mark_sha=_LEGACY_GROUPS[phase][branch]
    ptr=_legacy_safe(home/pointer,home,limit=2048)
    raw=ptr.read_text(encoding='utf-8').strip()
    # Pointers retain the ORIGINAL provenance path, never rewrite original JSON.
    session=_legacy_mapped_original(raw,home)
    if not session.is_dir():
        raise ValueError('LEGACY_SESSION_PATH_UNSAFE')
    source_file=session/mark_name
    source=_legacy_json(source_file,home,mark_sha)
    mixed_name,mixed_sha=_LEGACY_MIXED[phase]
    mixed_file=home/mixed_name
    mixed=_legacy_json(mixed_file,home,mixed_sha)
    key=branch+'_source'
    if (mixed.get('format')!='smart-fire-final-mixed-marks-v3' or
        _legacy_mapped_original(mixed.get(key,''),home)!=source_file.resolve()):
        raise ValueError('LEGACY_MIXED_LINEAGE_FAILED')
    if source.get('validation_dir') and _legacy_mapped_original(source['validation_dir'],home)!=session.resolve():
        raise ValueError('LEGACY_SESSION_METADATA_MISMATCH')
    marks=source['pairs'].get(pair)
    if (not isinstance(marks,list) or len(marks)<1 or len(marks)>100 or
        marks != mixed['pairs'].get(pair)):
        raise ValueError('LEGACY_PAIR_LINEAGE_MISMATCH')
    files={
        'a':_legacy_safe(session/'captures'/f'step_{step_a:02d}_p{pre_a}.jpg',home),
        'b':_legacy_safe(session/'captures'/f'step_{step_b:02d}_p{pre_b}.jpg',home),
    }
    size={side:_legacy_jpeg_size(path) for side,path in files.items()}
    manifest=_legacy_json_manifest(home/'source_manifest.json',home)
    for path in (ptr,*files.values(),source_file,mixed_file):
        rel=path.resolve(strict=True).relative_to(home.resolve(strict=True)).as_posix()
        if manifest['files'].get(rel)!=_legacy_sha(path):
            raise ValueError('LEGACY_STAGED_EVIDENCE_SHA_MISMATCH')
    import math
    sanitized=[]
    for item in marks:
        if not isinstance(item,dict):raise ValueError('LEGACY_BAD_MARK_OBJECT')
        converted={}
        for side in ('a','b'):
            pt=item.get(side)
            if not isinstance(pt,(list,tuple)) or len(pt)!=2:
                raise ValueError('LEGACY_BAD_MARK_POINT')
            w,h=size[side]
            if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in pt):
                raise ValueError('LEGACY_BAD_MARK_COORDINATE')
            if not (0 <= pt[0] < w and 0 <= pt[1] < h):
                raise ValueError('LEGACY_POINT_OUTSIDE_SOURCE_IMAGE')
            converted['x_'+side+'_px']=float(pt[0])
            converted['y_'+side+'_px']=float(pt[1])
        sanitized.append(converted)
    # Evidence is tied to source JPEGs; current captures cannot be overlaid.
    manager=root/'calibration/.manager'
    active_frames=manager/'revisions'/_LEGACY_SITE/_LEGACY_REV/'artifacts/ptz_captures/main'
    current_equal=True
    for side,preset in (('a',pre_a),('b',pre_b)):
        current=active_frames/f'preset_{preset}.jpg'
        if not current.is_file() or current.is_symlink():
            current_equal=False
        elif _legacy_sha(files[side]) != _legacy_sha(_legacy_safe(current,manager)):
            current_equal=False
    return {
        'ok':True,'read_only':True,'import_allowed':False,
        'site_id':_LEGACY_SITE,'revision_id':_LEGACY_REV,
        'phase':phase,'pair':pair,'branch':branch,'source_session':session.name,
        'marks':sanitized,'count':len(sanitized),
        'source_marks_sha256':mark_sha,'mixed_sha256':mixed_sha,
        'source_dimensions':size,'source_equals_active_images':current_equal,
        'frame_urls':{side:f'/api/phase45/active/legacy-frame/{phase}/{pair}/{side}' for side in files},
        'runtime_changed':False,
        'notice':'Historical source images only. Not current Wizard captures. No import, solve, publish, or edits.'
    }, files


def legacy_pair_preview(phase,pair):
    return legacy_pair_evidence(phase,pair)[0]


def legacy_source_frame(phase,pair,side):
    if side not in ('a','b'):
        raise ValueError('LEGACY_INVALID_FRAME_SIDE')
    _,paths=legacy_pair_evidence(phase,pair)
    return paths[side]


# Stage 3D.1: a separate edit-draft for ORIGINAL historical session images.
# It is intentionally NOT an activation candidate, geometry solve input, or
# permission to overlay on current preset captures. The source 618 marks stay
# byte-for-byte unchanged. Stable legacy indices support reversible deletion.
_LEGACY_DRAFT_FORMAT='smartfire-legacy-mark-draft-v1'
_LEGACY_DRAFT_ROOT=_LEGACY_ROOT/'calibration/.manager/legacy-mark-drafts'


def _historical_draft_path(phase, pair, *, root=None):
    if phase not in _LEGACY_GROUPS or pair not in _LEGACY_PAIRS:
        raise ValueError('INVALID_HISTORICAL_PHASE_PAIR')
    directory=(root or _LEGACY_DRAFT_ROOT)/_LEGACY_SITE/_LEGACY_REV/phase
    return directory/(pair+'.json')


def _historical_template(evidence, frame_shas):
    return {
        'format':_LEGACY_DRAFT_FORMAT,
        'site_id':_LEGACY_SITE,'revision_id':_LEGACY_REV,
        'phase':evidence['phase'],'pair':evidence['pair'],
        'source_marks_sha256':evidence['source_marks_sha256'],
        'source_frame_sha256':frame_shas,
        'removed':[], 'updated':{}, 'added':[],
    }


def _historical_draft_hash(draft):
    data=json.dumps(draft,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    return hashlib.sha256(data).hexdigest()


def _historical_validate_folder(path, *, create=False):
    # Do not resolve symlinked directories, including an attacker-controlled
    # intermediate directory. The Manager must be able to write the root.
    for parent in (path.parent, *list(path.parent.parents)[:5]):
        if parent.is_symlink(): raise ValueError('LEGACY_DRAFT_UNSAFE_DIRECTORY')
    if create:
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        for parent in (path.parent, *list(path.parent.parents)[:5]):
            if parent.is_symlink(): raise ValueError('LEGACY_DRAFT_UNSAFE_DIRECTORY')
    if path.is_symlink():raise ValueError('LEGACY_DRAFT_SYMLINK')


def _historical_load_draft(evidence, frame_shas, *, root=None):
    path=_historical_draft_path(evidence['phase'],evidence['pair'],root=root)
    _historical_validate_folder(path)
    template=_historical_template(evidence,frame_shas)
    if not path.exists():return template
    if not path.is_file() or path.stat().st_size>500_000:
        raise ValueError('LEGACY_DRAFT_BAD_FILE')
    obj=json.loads(path.read_text(encoding='utf8'))
    if not isinstance(obj,dict) or set(obj)!=set(template) or any(obj.get(k)!=v for k,v in template.items() if k not in ('removed','updated','added')):
        raise ValueError('LEGACY_DRAFT_LINEAGE_MISMATCH')
    total=len(evidence['marks'])
    removed=obj['removed'];updated=obj['updated'];added=obj['added']
    if not isinstance(removed,list) or any(type(i) is not int or not 0<=i<total for i in removed) or len(set(removed))!=len(removed):
        raise ValueError('LEGACY_DRAFT_BAD_REMOVED')
    if not isinstance(updated,dict) or any(not k.isdecimal() or int(k)>=total or int(k) in removed for k in updated):
        raise ValueError('LEGACY_DRAFT_BAD_UPDATED')
    if not isinstance(added,list) or len(added)>300:
        raise ValueError('LEGACY_DRAFT_BAD_ADDED')
    import re
    ids=set()
    for row in added:
        if not isinstance(row,dict) or set(row)!={'id','mark'} or not isinstance(row['id'],str) or not re.fullmatch(r'[0-9a-f]{32}',row['id']) or row['id'] in ids:
            raise ValueError('LEGACY_DRAFT_BAD_ADDED_ID')
        ids.add(row['id'])
    dimensions=evidence['source_dimensions']
    def check_mark(mark):
        if not isinstance(mark,dict) or set(mark)!=set(FIELDS): raise ValueError('LEGACY_DRAFT_BAD_MARK')
        # Per-side limits must be checked separately even for mixed dimensions.
        if not 0<=mark['x_a_px']<dimensions['a'][0] or not 0<=mark['y_a_px']<dimensions['a'][1] or not 0<=mark['x_b_px']<dimensions['b'][0] or not 0<=mark['y_b_px']<dimensions['b'][1]:
            raise ValueError('LEGACY_DRAFT_OUTSIDE_FRAME')
        return mark
    for mark in updated.values():check_mark(mark)
    for row in added:check_mark(row['mark'])
    return obj


def _historical_effective(evidence, draft):
    removed=set(draft['removed']);updated=draft['updated']
    active=[{'key':f'src:{i}', 'origin':'source','source_index':i,
             **(updated.get(str(i)) or m)} for i,m in enumerate(evidence['marks']) if i not in removed]
    active.extend({'key':'new:'+row['id'],'origin':'added','source_index':None,**row['mark']} for row in draft['added'])
    deleted=[{'key':f'src:{i}','source_index':i,**evidence['marks'][i]} for i in sorted(removed)]
    return active,deleted


def legacy_draft_preview(phase,pair,*,home=None,root=None,draft_root=None,enforce_active=True):
    # Rechecks pinned source SHA, JPEG SHA, and active revision every request.
    evidence,frames=legacy_pair_evidence(phase,pair,home=home,root=root,enforce_active=enforce_active)
    frames_sha={k:_legacy_sha(v) for k,v in frames.items()}
    draft=_historical_load_draft(evidence,frames_sha,root=draft_root)
    effective,deleted=_historical_effective(evidence,draft)
    # UI affordance only; POST enforces the same guard under hardware_lock.
    try:
        from manager.services.runtime_site_crud import _require_editable_working_copy
        working=_require_editable_working_copy(_LEGACY_SITE)
        editable=working.get('parent_revision')==_LEGACY_REV and not working.get('recovery')
    except (KeyError,RuntimeError,PermissionError,ValueError,ImportError):
        editable=False
    result={**evidence,
       'draft':{'digest':_historical_draft_hash(draft),'editable':editable,
                'effective_marks':effective,'deleted_marks':deleted,
                'source_count':len(evidence['marks']),
                'kept_source_count':len(evidence['marks'])-len(draft['removed']),
                'added_count':len(draft['added']),
                'removed_count':len(draft['removed']),
                'updated_count':len(draft['updated']),
                'not_solver_input':True,'not_current_capture':True}}
    return result


def _historical_pure_edit(evidence,frame_shas,draft,payload):
    import uuid
    if not isinstance(payload,dict):raise ValueError('INVALID_HISTORICAL_PAYLOAD')
    updated=copy.deepcopy(draft)
    action=payload.get('action')
    key=payload.get('key')
    total=len(evidence['marks'])
    if action in ('delete','restore','update'):
        if not isinstance(key,str) or not (key.startswith('src:') or key.startswith('new:')):
            raise ValueError('LEGACY_INVALID_MARK_KEY')
        if key.startswith('src:'):
            number=key[4:]
            if not number.isdecimal() or int(number)>=total:raise ValueError('LEGACY_BAD_SOURCE_INDEX')
            index=int(number)
            if action=='restore':
                if index not in updated['removed']:raise ValueError('LEGACY_MARK_NOT_DELETED')
                updated['removed'].remove(index)
            elif action=='delete':
                if index in updated['removed']:raise ValueError('LEGACY_MARK_ALREADY_REMOVED')
                updated['removed'].append(index)
                updated['removed'].sort()
                updated['updated'].pop(str(index),None)
            else:
                if index in updated['removed']:raise ValueError('LEGACY_MARK_REMOVED')
                updated['updated'][str(index)]=_historical_new_mark(evidence,payload.get('mark'))
        else:
            mark_id=key[4:]
            row=next((r for r in updated['added'] if r['id']==mark_id),None)
            if row is None or action=='restore':raise ValueError('LEGACY_NEW_MARK_NOT_FOUND')
            if action=='delete':updated['added'].remove(row)
            else:row['mark']=_historical_new_mark(evidence,payload.get('mark'))
    elif action=='add':
        if len(updated['added'])>=300:raise ValueError('LEGACY_ADDED_LIMIT')
        updated['added'].append({'id':uuid.uuid4().hex,'mark':_historical_new_mark(evidence,payload.get('mark'))})
    elif action=='clear':
        if payload.get('confirm')!='CLEAR '+evidence['phase'].upper()+' '+evidence['pair']:
            raise ValueError('LEGACY_CLEAR_EXPLICIT_CONFIRM_REQUIRED')
        updated['removed']=list(range(total));updated['updated']={};updated['added']=[]
    elif action=='reset':
        if payload.get('confirm')!='RESTORE '+evidence['phase'].upper()+' '+evidence['pair']:
            raise ValueError('LEGACY_RESET_EXPLICIT_CONFIRM_REQUIRED')
        updated['removed']=[];updated['updated']={};updated['added']=[]
    else:raise ValueError('LEGACY_UNSUPPORTED_ACTION')
    return updated


def _historical_new_mark(evidence,mark):
    if not isinstance(mark,dict) or set(mark)!=set(FIELDS):raise ValueError('LEGACY_MARK_SCHEMA_INVALID')
    bounds=evidence['source_dimensions']
    # clean_mark() assumes common width/height, but a/b can differ.
    for key,maximum in [('x_a_px',bounds['a'][0]),('y_a_px',bounds['a'][1]),('x_b_px',bounds['b'][0]),('y_b_px',bounds['b'][1])]:
        n=mark[key]
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<maximum:
            raise ValueError('LEGACY_MARK_OUTSIDE_SOURCE_FRAME:'+key)
    return {k:float(mark[k]) for k in FIELDS}


def legacy_draft_edit(phase,pair,payload):
    import os,tempfile
    from manager.services.runtime_site_crud import _require_editable_working_copy, _audit
    from manager.services.hardware_lock import hardware_lock
    if not isinstance(payload,dict) or payload.get('site_id')!=_LEGACY_SITE or payload.get('revision_id')!=_LEGACY_REV:
        raise PermissionError('LEGACY_DRAFT_SITE_REVISION_MISMATCH')
    with hardware_lock('legacy-evidence-draft-edit',timeout=3):
        _legacy_active_gate()
        working=_require_editable_working_copy(_LEGACY_SITE)
        if working.get('parent_revision')!=_LEGACY_REV or working.get('recovery'):
            raise PermissionError('LEGACY_DRAFT_WORKING_PARENT_MISMATCH')
        evidence,frames=legacy_pair_evidence(phase,pair)
        frame_shas={k:_legacy_sha(v) for k,v in frames.items()}
        draft=_historical_load_draft(evidence,frame_shas)
        if not isinstance(payload.get('expected_digest'),str) or payload['expected_digest']!=_historical_draft_hash(draft):
            raise RuntimeError('LEGACY_DRAFT_STALE_REFRESH_REQUIRED')
        after=_historical_pure_edit(evidence,frame_shas,draft,payload)
        path=_historical_draft_path(phase,pair)
        _historical_validate_folder(path,create=True)
        raw=json.dumps(after,ensure_ascii=False,sort_keys=True,indent=2).encode('utf8')
        fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.legacy-draft-')
        try:
            with os.fdopen(fd,'wb') as f:
                os.fchmod(f.fileno(),0o600)
                f.write(raw);f.flush();os.fsync(f.fileno())
            if path.is_symlink():raise ValueError('LEGACY_DRAFT_SYMLINK')
            os.replace(tmp,path)
            dirfd=os.open(str(path.parent),os.O_DIRECTORY)
            try:os.fsync(dirfd)
            finally:os.close(dirfd)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        # If a historical dataset was prepared/solved earlier, any subsequent
        # mark edit revokes that solver evidence. Source/revisions stay immutable.
        from manager.services.wizard_store import load_state,save_state
        state=load_state(_LEGACY_SITE)
        geom=state.get('geometry') or {}
        if geom.get('historical_draft_solver_source'):
            state['phase45_geometry_dirty']=True
            geom.pop('solver_result',None)
            geom.pop('solver_inputs',None)
            save_state(_LEGACY_SITE,state)
        _audit('historical_session_draft_edit',site_id=_LEGACY_SITE,
               phase=phase,pair=pair,action_type=payload.get('action'))
        # Never writes Candidate, Wizard State, Revision, Active, or original RO evidence.
        return {'ok':True,'draft_digest':_historical_draft_hash(after),
                'runtime_changed':False,'candidate_changed':False,
                'requires_explicit_solver_integration':True,
                'notice':'Saved isolated historical Session draft. Not a runtime/solver dataset.'}
