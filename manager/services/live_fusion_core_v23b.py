#!/usr/bin/env python3
"""Live PTZ/RTSP/AI/Fusion LAB diagnostic for Smart Fire v2.

Runs only with an explicit confirmation and in LAB; does not send Telegram,
modify calibration/revisions, or persist secrets. Requires root for reading
systemd runtime environment and pausing/restoring Detection.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/opt/smart-fire-detection-v2')
SERVICE = 'smart-fire-detection.service'
OUT_ROOT = ROOT / 'calibration/.manager/test-runs/live-fusion'


def run_cmd(*parts: str, timeout=40, check=True):
    return subprocess.run(parts, check=check, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def is_active():
    return run_cmd('systemctl','is-active','--quiet',SERVICE,check=False).returncode == 0


def live_env():
    result = run_cmd('systemctl','show',SERVICE,'-p','MainPID','--value', timeout=10)
    pid = int(result.stdout.strip() or '0')
    if pid < 2 or not is_active():
        raise RuntimeError('Detection must be running before LAB test')
    blob = Path(f'/proc/{pid}/environ').read_bytes()
    values = {}
    for item in blob.split(b'\x00'):
        if b'=' not in item: continue
        k,v = item.split(b'=',1)
        key = k.decode('utf-8','strict')
        if key and key.isidentifier():
            values[key] = v.decode('utf-8','surrogateescape')
    for key in ('CAMERA_IP','CAMERA_USER','CAMERA_PWD','RTSP_PORT'):
        if not values.get(key):
            raise RuntimeError('Required camera runtime configuration missing: '+key)
    # Do not inherit Telegram credentials into an isolated test process.
    values.pop('TELEGRAM_TOKEN',None)
    values.pop('TELEGRAM_CHAT_ID',None)
    return values


def site_identity():
    from manager.services.site_store import get_active_site
    item = get_active_site() or {}
    return item.get('site_id'), item.get('revision_id')


def lab_identity():
    from manager.services.site_registry import list_registered_sites
    site, rev = site_identity()
    if not site or not rev: raise RuntimeError('Invalid active Site/Revision identity')
    rec = (list_registered_sites().get('sites') or {}).get(site) or {}
    if str(rec.get('mode','')).upper() != 'LAB':
        raise RuntimeError('LAB_ONLY: Refusing live test outside registered LAB site')
    return site, rev


def angular_span(presets, bearings):
    angles = sorted(float(bearings[p]) % 360 for p in presets)
    gaps = [((angles[(i+1)%len(angles)] - angles[i]) % 360)
            for i in range(len(angles))]
    return 360 - max(gaps)


def preflight(presets):
    if os.geteuid() != 0:
        raise RuntimeError('Needs sudo/root for hardware test safety and environment access')
    sys.path.insert(0, str(ROOT))
    s,r = lab_identity()
    # Load effective environment from the CURRENT Detection process BEFORE
    # importing config.py (which caches settings at import time).
    env = live_env()
    os.environ.update(env)
    os.environ.pop("TELEGRAM_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    from config import HFOV_DEG, PRESET_BEARING_DEG
    from cross_preset_fusion import presets_can_overlap
    if len(presets) != 3 or len(set(presets)) != 3:
        raise RuntimeError('Choose exactly three distinct presets')
    if any(p not in PRESET_BEARING_DEG for p in presets):
        raise RuntimeError('Unsupported PTZ Preset')
    if not all(presets_can_overlap(a,b) for a,b in zip(presets,presets[1:])):
        raise RuntimeError('Route contains adjacent presets that Fusion Engine cannot associate')
    span = angular_span(presets, PRESET_BEARING_DEG)
    overlap = float(HFOV_DEG) - span
    # Pairwise fusion-route support is a safety-independent prerequisite.
    # A 3-way angular FOV estimate is advisory in LAB, not a camera observation.
    # The real images/AI results decide whether all presets saw the target.
    if not is_active(): raise RuntimeError('DETECTION_NOT_ACTIVE')
    print('PREFLIGHT=PASS', flush=True)
    print('ACTIVE_SITE=',s,'ACTIVE_REVISION=',r,flush=True)
    print('MODE=LAB')
    print('PRESETS=',','.join(map(str,presets)))
    print('HFOV_DEG=',round(float(HFOV_DEG),3))
    print('THEORETICAL_COMMON_FOV_DEG=',round(overlap,3))
    print('THEORETICAL_TRIPLE_OVERLAP=', 'LIKELY' if overlap >= 5 else 'NOT_PREDICTED')
    print('ACTUAL_TARGET_VISIBILITY=UNVERIFIED')
    print('STATIONARY_TARGET_REQUIRED=YES')
    print('TELEGRAM_IN_TEST=DISABLED')
    print('CAMERA_CONFIG_LOADED=YES (values hidden)')
    return (s,r),env


def arm_failsafe():
    name = 'sf-live-fusion-restore-'+str(os.getpid())
    # systemd transient timer runs even if this testing shell is terminated.
    run_cmd('systemd-run', '--quiet', '--unit='+name, '--on-active=8m',
            '/usr/bin/systemctl','start',SERVICE,timeout=20)
    print('FAILSAFE_TIMER=ARMED_8_MINUTES', flush=True)
    return name


def disarm_failsafe(name):
    if not name: return
    run_cmd('systemctl','stop',name+'.timer',timeout=15,check=False)
    print('FAILSAFE_TIMER=CANCELLED_AFTER_RESTORE',flush=True)


def ensure_stopped():
    run_cmd('systemctl','stop',SERVICE,timeout=60)
    for _ in range(20):
        if not is_active():
            print('DETECTION_PAUSED=YES',flush=True)
            return
        time.sleep(.5)
    raise RuntimeError('DETECTION_DID_NOT_STOP')


def restore_detection():
    try:
        run_cmd('systemctl','start',SERVICE,timeout=135)
        for _ in range(45):
            if is_active():
                print('DETECTION_RESTORED=YES',flush=True)
                return True
            time.sleep(1)
    except Exception as exc:
        print('RESTORE_ERROR_TYPE=',type(exc).__name__,flush=True)
    print('DETECTION_RESTORED=NO (failsafe timer remains armed)',flush=True)
    return False


def acquire_frame(camera,ptz,preset,first,config):
    from camera import wait_until_stable
    # Suppress PTZ library exception output: it may contain credentials in a URL.
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        ok,wait = ptz.goto_preset(preset)
    if not ok:
        raise RuntimeError('PTZ_MOVE_FAILED_PRESET_'+str(preset))
    time.sleep(min(45., max(float(wait), 15. if first else 2.5)))
    seq=camera.sequence
    packet=None
    for _ in range(int(config.POST_MOVE_FRESH_FRAMES)):
        packet=camera.wait_for_newer(seq,timeout=5)
        if packet is None: raise RuntimeError('CAMERA_FRAME_TIMEOUT_PRESET_'+str(preset))
        seq=packet.seq
    stable=wait_until_stable(camera,seq,config.STABLE_DIFF_THRESHOLD,
                             config.STABLE_REQUIRED_PAIRS,
                             max(8.,config.STABLE_TIMEOUT_SEC))
    if stable is None: raise RuntimeError('CAMERA_STABILITY_TIMEOUT_PRESET_'+str(preset))
    return stable


def redact_observation(d,preset):
    def safe_number(x,nd=3):
        if x is None:return None
        try:return round(float(x),nd)
        except (TypeError,ValueError):return None
    return {
        'preset':preset,'class':str(d.canonical_class),
        'object_id':getattr(d,'object_id',None),
        'confidence':safe_number(d.confidence),
        'raw_bearing_deg':safe_number(getattr(d,'raw_bearing_deg',d.bearing_deg)),
        'output_bearing_deg':safe_number(d.bearing_deg),
        'distance_m':safe_number(d.distance_m),
        'bbox':list(map(int,d.bbox)),
        'fused_measurement':bool(getattr(d,'measurement_fused',False)),
        'bearing_zone':getattr(d,'bearing_zone',None),
        'fusion_anchor_stale':bool(getattr(d,'fusion_anchor_stale',False)),
    }


def annotate(frame, detections, preset, cv2):
    result=frame.copy()
    cv2.putText(result, 'LIVE LAB TEST P'+str(preset), (20,37),
                cv2.FONT_HERSHEY_SIMPLEX,.8,(0,210,255),2)
    for d in detections:
        a,b,c,e = map(int,d.bbox)
        cv2.rectangle(result,(a,b),(c,e),(0,210,255),2)
        label=f'{d.canonical_class} {d.confidence:.2f} {getattr(d,"object_id","UNFUSED")}'
        cv2.putText(result,label,(max(3,a),max(20,b-6)),
                    cv2.FONT_HERSHEY_SIMPLEX,.55,(0,210,255),2)
    return result


def perform_test(presets,output,original):
    import cv2
    from camera import LatestFrameCamera
    import config
    from ptz import PTZController
    from detection import FireDetector, consensus
    from cross_preset_fusion import CrossPresetObjectFusion
    from preset_geometry import get_runtime_preset_rotation
    rotation = get_runtime_preset_rotation()
    rotation.reload_if_changed()
    detector=FireDetector()
    fusion=CrossPresetObjectFusion()
    ptz=PTZController()
    camera=LatestFrameCamera().start()
    try:
        start=time.monotonic()
        while camera.latest(copy=False) is None:
            if time.monotonic()-start > 15:
                raise RuntimeError('RTSP_CAMERA_STARTUP_TIMEOUT')
            time.sleep(.2)
        report={'test_type':'LIVE_REAL_RTSP_AI_FUSION_LAB','site_id':original[0],
                'revision_id':original[1],'route':presets,'no_telegram':True,
                'results':[],'same_object':False,'passed':False}
        for idx,preset in enumerate(presets):
            print('LIVE_PRESET_START=',preset,flush=True)
            packet=acquire_frame(camera,ptz,preset,idx==0,config)
            frames=[]
            for frame_idx in range(config.FRAMES_PER_SCAN):
                if frame_idx:
                    time.sleep(config.FRAME_SAMPLE_GAP_SEC)
                    next_packet=camera.wait_for_newer(packet.seq,timeout=4)
                    if next_packet is None:break
                    packet=next_packet
                result=detector.detect(packet.frame,preset,
                                       apply_north_offset=False,allow_gps=False)
                frames.append(result)
            confirmed=consensus(frames,config.MIN_CONFIRM_FRAMES) if len(frames)>=config.MIN_CONFIRM_FRAMES else []
            fused=fusion.fuse_batch(confirmed,preset,time.monotonic())
            image_path=output/f'preset_{preset}.jpg'
            if not cv2.imwrite(str(image_path),annotate(packet.frame,fused,preset,cv2)):
                raise RuntimeError('EVIDENCE_IMAGE_WRITE_FAILED')
            os.chmod(image_path,0o600)
            rows=[redact_observation(d,preset) for d in fused]
            report['results'].append({'preset':preset,'frames_inferred':len(frames),
                                      'raw_counts':[len(x) for x in frames],
                                      'confirmed_count':len(fused),
                                      'observations':rows,
                                      'image':image_path.name})
            print('P'+str(preset)+'_FRAMES=',len(frames),
                  'RAW_COUNTS=',[len(x) for x in frames],
                  'CONFIRMED=',len(fused),
                  'IDS=',[d['object_id'] for d in rows],flush=True)
            if site_identity()!=original:
                raise RuntimeError('ACTIVE_RUNTIME_CHANGED_DURING_TEST')
        rows=[r['observations'] for r in report['results']]
        if all(len(x)==1 for x in rows):
            ids={x[0]['object_id'] for x in rows}
            classes={x[0]['class'] for x in rows}
            same=(len(ids)==1 and None not in ids and len(classes)==1)
            report['same_object']=same
            report['passed']=same
            report['result']='PASS_SAME_OBJECT_3_PRESETS' if same else 'NOT_FUSED_SAME_OBJECT'
        elif any(len(x)>1 for x in rows):
            report['result']='AMBIGUOUS_MULTIPLE_OBJECTS'
        else:
            report['result']='NOT_CONFIRMED_IN_ALL_3_PRESETS'
        return report
    finally:
        camera.stop()


def main():
    parser=argparse.ArgumentParser(description='Real 3-preset camera/AI/fusion test, LAB only')
    parser.add_argument('--presets',default='4,5,9',help='ordered 3 physical presets (default 4,5,9)')
    parser.add_argument('--run',action='store_true',help='actually pause detection and move PTZ')
    parser.add_argument('--confirm',default='',help='must equal LAB_LIVE_TEST')
    args=parser.parse_args()
    try:
        presets=[int(p.strip()) for p in args.presets.split(',')]
    except ValueError:
        parser.error('Presets must be comma-separated integers')
    if len(presets)!=3 or len(set(presets))!=3:
        parser.error('Exactly three distinct presets required')
    try:
        original,env=preflight(presets)
        if not args.run:
            print('PREFLIGHT_ONLY=YES')
            print('NEXT=Place stationary target in common field of view; run with --run --confirm LAB_LIVE_TEST')
            return 0
        if args.confirm!='LAB_LIVE_TEST':
            raise RuntimeError('Explicit confirmation missing: --confirm LAB_LIVE_TEST')
        # Critical: do not inherit a notification-capable Telegram config into the test.
        os.environ.update(env)
        os.environ.pop('TELEGRAM_TOKEN',None)
        os.environ.pop('TELEGRAM_CHAT_ID',None)
        # Restore service even if the shell sends SIGTERM, or test exceeds 5m20s.
        def handle_interrupt(signum, frame):
            raise TimeoutError('Live test interrupted or timed out')
        signal.signal(signal.SIGTERM, handle_interrupt)
        signal.signal(signal.SIGALRM, handle_interrupt)
        from manager.services.hardware_lock import hardware_lock
        with hardware_lock('live-fusion-lab-3presets',timeout=2):
            if site_identity()!=original:
                raise RuntimeError('Active site changed after preflight')
            name=None
            restored=False
            output=None
            try:
                name=arm_failsafe()
                signal.alarm(320)
                ensure_stopped()
                stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                output=OUT_ROOT/(stamp+'-'+str(os.getpid()))
                output.mkdir(mode=0o700,parents=True,exist_ok=False)
                os.chmod(output,0o700)
                result=perform_test(presets,output,original)
                report_path=output/'result.json'
                report_path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                os.chmod(report_path,0o600)
                print('LIVE_FUSION_RESULT=',result['result'],flush=True)
                print('SAME_OBJECT=',result['same_object'],flush=True)
                print('EVIDENCE_DIRECTORY=',output,flush=True)
                print('EVIDENCE_IMAGES=',','.join(x['image'] for x in result['results']),flush=True)
            finally:
                signal.alarm(0)
                if name:
                    restored=restore_detection()
                    if restored: disarm_failsafe(name)
                print('ACTIVE_RUNTIME_UNCHANGED=',site_identity()==original,flush=True)
                print('DETECTION_SERVICE_ACTIVE=',is_active(),flush=True)
                if not restored: print('WARNING=Failsafe timer still armed',flush=True)
            if not restored:
                raise RuntimeError('DETECTION_RESTORE_NOT_CONFIRMED')
            print('LIVE_FUSION_TEST_COMPLETE',flush=True)
            return 0 if result['passed'] else 2
    except Exception as exc:
        # Errors from camera stack may include RTSP URL/credentials; print type only.
        print('TEST_ERROR_TYPE=',type(exc).__name__,flush=True)
        print('LIVE_FUSION_TEST_FAILED_OR_ABORTED',flush=True)
        return 1

if __name__=='__main__':
    sys.exit(main())
