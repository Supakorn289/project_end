"""Read-only web view of root-managed live fusion LAB runs.

The fire-owned Manager may read summaries and annotated captures; only the
privileged Agent can launch camera/Detection control commands.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path

ROOT = Path('/opt/smart-fire-detection-v2')
JOBS = ROOT / 'calibration/.manager/live-fusion-web'
JOB_RE = re.compile(r'^lf-[0-9a-f]{24}$')
IMAGE_RE = re.compile(r'^preset_([1-9])\.jpg$')


def safe_dir(job_id):
    if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
        raise ValueError('invalid_test_id')
    return JOBS / job_id


def _read_json(p, max_bytes=262144):
    try:
        if not p.is_file() or p.is_symlink() or p.stat().st_size > max_bytes:
            return None
        with p.open('rb') as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def get_status(job_id):
    base = safe_dir(job_id)
    meta = _read_json(base / 'meta.json')
    if not isinstance(meta, dict) or meta.get('job_id') != job_id:
        raise FileNotFoundError('test_not_found')
    finish = _read_json(base / 'finish.json')
    if finish is None:
        pid = meta.get('pid',0)
        if isinstance(pid,int) and pid > 1:
            try:
                os.kill(pid,0)
                stat=Path(f'/proc/{pid}/stat').read_text()
                if stat.rsplit(')',1)[-1].strip().startswith('Z'):
                    raise ProcessLookupError('zombie_worker')
            except ProcessLookupError:
                finish = {'exit_code':None, 'detection_restored':None,
                          'runtime_changed':None, 'error':'worker_exited_without_report'}
            except PermissionError:
                pass
    stage = []
    log = base / 'run.log'
    # Read no more than 64KiB of stdout. Extract controlled numeric/status
    # event lines only; never return arbitrary library logs or credentials.
    if log.is_file() and not log.is_symlink():
        try:
            with log.open('rb') as f:
                f.seek(max(0, log.stat().st_size - 65536))
                content = f.read(65536).decode('utf-8','replace')
        except OSError:
            content = ''
        for line in content.splitlines():
            if re.fullmatch(r'LIVE_PRESET_START=\s*[1-9]',line):
                stage.append(line)
            elif line in ('DETECTION_PAUSED=YES','DETECTION_RESTORED=YES',
                          'FAILSAFE_TIMER=ARMED_8_MINUTES',
                          'LIVE_FUSION_TEST_COMPLETE'):
                stage.append(line)
            elif re.fullmatch(r'LIVE_FUSION_RESULT=\s*[A-Z0-9_]+',line):
                stage.append(line)
    stage = stage[-20:]
    result = None
    images = []
    for child in base.iterdir():
        if child.is_dir() and not child.is_symlink():
            possible = _read_json(child / 'result.json')
            if isinstance(possible, dict) and possible.get('site_id') == meta.get('site_id') and possible.get('revision_id') == meta.get('revision_id'):
                result = possible
                for p in meta['presets']:
                    if (child / f'preset_{p}.jpg').is_file():
                        images.append(p)
                break
    return {
        'ok': True,'job_id':job_id,'site_id':meta['site_id'],
        'revision_id':meta['revision_id'],'presets':meta['presets'],
        'started_at':meta['started_at'],'running':finish is None,
        'finished': finish is not None,
        'exit_code':finish.get('exit_code') if finish else None,
        'detection_restored':finish.get('detection_restored') if finish else None,
        'result':result,'image_presets':images,'stages':stage,
        'runtime_changed':None if finish is None else finish.get('runtime_changed'),
        'warning':'LAB ONLY, image-of-flame is not an operational fire-safety validation',
    }


def get_image(job_id, preset):
    base = safe_dir(job_id)
    meta = _read_json(base/'meta.json')
    if not isinstance(meta,dict) or meta.get('job_id') != job_id:
        raise FileNotFoundError('test_not_found')
    if type(preset) is not int or preset not in meta['presets']:
        raise ValueError('invalid_preset')
    name = f'preset_{preset}.jpg'
    if not IMAGE_RE.fullmatch(name):
        raise ValueError('invalid_image')
    for child in base.iterdir():
        if child.is_dir() and not child.is_symlink():
            p = child/name
            if p.is_file() and not p.is_symlink():
                return p
    raise FileNotFoundError('image_not_ready')
