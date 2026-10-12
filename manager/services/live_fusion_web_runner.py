#!/usr/bin/env python3
"""Privileged isolated worker started ONLY by Manager Agent with fixed argv."""
from __future__ import annotations
import argparse
import grp
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/opt/smart-fire-detection-v2')
BASE = ROOT / 'calibration/.manager/live-fusion-web'
RE = re.compile(r'^lf-[0-9a-f]{24}$')

def atomic_status(path, data):
    tmp = path.with_suffix('.new')
    tmp.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
    os.chmod(tmp,0o640)
    os.chown(tmp,0,grp.getgrnam('fire').gr_gid)
    os.replace(tmp,path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job-id',required=True)
    parser.add_argument('--presets',required=True)
    parser.add_argument('--site-id',required=True)
    parser.add_argument('--revision-id',required=True)
    args=parser.parse_args()
    if not RE.fullmatch(args.job_id):
        raise SystemExit('Invalid job id')
    directory=BASE/args.job_id
    meta=json.loads((directory/'meta.json').read_text())
    if meta.get('site_id')!=args.site_id or meta.get('revision_id')!=args.revision_id or ','.join(map(str,meta.get('presets',[])))!=args.presets:
        raise SystemExit('Job preflight mismatch')
    sys.path.insert(0,str(ROOT))
    from manager.services import live_fusion_core_v23b as core
    from manager.services.site_store import get_active_site
    core.OUT_ROOT = directory
    before=get_active_site() or {}
    rc=1
    try:
        if (before.get('site_id'), before.get('revision_id')) != (args.site_id,args.revision_id):
            print('TEST_ERROR_TYPE=ACTIVE_SITE_CHANGED_BEFORE_START',flush=True)
            return 1
        sys.argv=['live_fusion_core_v23b.py','--presets',args.presets,'--run','--confirm','LAB_LIVE_TEST']
        try:
            rc=core.main()
        except BaseException as ex:
            print('TEST_ERROR_TYPE='+type(ex).__name__,flush=True)
            rc=1
        return int(rc)
    finally:
        # Restrict access to the authenticated Manager group for image/result viewing.
        group=grp.getgrnam('fire').gr_gid
        for child in directory.iterdir():
            if child.is_dir() and not child.is_symlink():
                os.chown(child,0,group); os.chmod(child,0o750)
                for art in child.iterdir():
                    if art.is_file() and not art.is_symlink():
                        os.chown(art,0,group); os.chmod(art,0o640)
        after=get_active_site() or {}
        healthy=subprocess.run(['systemctl','is-active','--quiet','smart-fire-detection.service'],check=False).returncode==0
        atomic_status(directory/'finish.json',{
            'finished_at':datetime.now(timezone.utc).isoformat(),
            'exit_code':rc,
            'detection_restored':healthy,
            'runtime_changed':(before.get('site_id'),before.get('revision_id'))!=(after.get('site_id'),after.get('revision_id')),
        })

if __name__=='__main__':
    sys.exit(main())
