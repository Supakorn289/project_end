# Model Card — Fire/Smoke Model R3-E6

## Intended Use

Research/engineering detection of visible fire and smoke in camera frames as part of the Smart Fire Detection v2 pipeline.

## Class Contract

```text
0 = fire
1 = smoke
```

## Runtime Contract

The project uses an Ultralytics YOLO inference runtime with a frozen model artifact and validates file integrity before use.

## Limitations

Possible failure modes include:

- glare / overexposure
- fog, steam, dust, clouds
- small/distant fire
- night/low-light scenes
- occlusion
- domain shift
- camera compression
- motion blur during PTZ movement

The system must not be treated as a certified life-safety fire alarm.

## Site Validation

Model behavior should be evaluated with representative imagery from the intended installation environment.
