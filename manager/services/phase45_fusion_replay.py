"""Dry-run CrossPresetObjectFusion on explicit user-supplied observations.
No camera/PTZ access, no alerts, no synthetic observations created server-side.
"""
from __future__ import annotations
import math
from types import SimpleNamespace


def finite_number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_{name}")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"invalid_{name}")
    return value


def validate_observations(payload):
    points = payload.get('observations') if isinstance(payload, dict) else None
    if not isinstance(points, list) or len(points) != 3:
        raise ValueError('exactly_3_preset_observations_required')
    result = []
    seen = set()
    for data in points:
        if not isinstance(data, dict):
            raise ValueError('invalid_observation')
        p = data.get('preset')
        if isinstance(p, bool) or not isinstance(p, int) or p not in range(1, 10) or p in seen:
            raise ValueError('invalid_or_duplicate_preset')
        seen.add(p)
        clazz = data.get('class')
        if clazz not in ('fire', 'smoke'):
            raise ValueError('class_must_be_fire_or_smoke')
        bbox = data.get('bbox')
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError('invalid_bbox')
        bbox = [finite_number(v, 'bbox', 0, 1280) for v in bbox]
        if not (bbox[0] < bbox[2] and bbox[1] < bbox[3] and bbox[2] <= 1280 and bbox[3] <= 720):
            raise ValueError('invalid_bbox_geometry')
        result.append({'preset':p,'class':clazz,'bbox':bbox,
                       'bearing_deg':finite_number(data.get('bearing_deg'), 'bearing', -360, 360),
                       'distance_m':finite_number(data.get('distance_m'), 'distance', 0.01, 200),
                       'confidence':finite_number(data.get('confidence',0.9),'confidence',0,1)})
    return result


def replay(payload):
    from cross_preset_fusion import CrossPresetObjectFusion
    obs = validate_observations(payload)
    fusion = CrossPresetObjectFusion()
    outcome = []
    for i, row in enumerate(obs):
        d = SimpleNamespace(
            canonical_class=row['class'], model_class=row['class'],
            bbox=tuple(row['bbox']), confidence=row['confidence'],
            bearing_deg=row['bearing_deg'], distance_m=row['distance_m'],
            distance_quality='unverified', gps=None,
        )
        fused = fusion.fuse_batch([d],row['preset'], float(i*2))
        result = fused[0]
        outcome.append({'preset':row['preset'], 'class':row['class'],
                        'object_id':result.object_id,
                        'raw_bearing_deg':result.raw_bearing_deg,
                        'output_bearing_deg':result.bearing_deg,
                        'fused_measurement':result.measurement_fused,
                        'source_preset':result.measurement_source_preset})
    unique = len({o['object_id'] for o in outcome})
    return {'ok':True, 'test_type':'REPLAY_ONLY_NOT_LIVE',
            'observations':outcome, 'unique_object_count':unique,
            'same_object':unique==1,
            'runtime_changed':False,
            'limitations':'Uses manually supplied observations with actual Fusion Engine. No new camera/AI detection, no Telegram and not field validation.'}
