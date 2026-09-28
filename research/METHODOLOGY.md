# Methodology

## Objective

Evaluate whether a PTZ-based AI surveillance pipeline can detect fire/smoke while providing reproducible preset-to-preset bearing geometry and approximate distance estimation.

## System Components

Document each experiment with:

- Git commit/tag
- camera model
- camera resolution
- lens/zoom state
- server hardware
- OS/Python versions
- AI model SHA-256
- calibration revision
- site mode: LAB or PRODUCTION

## AI Detection

The production runtime uses a frozen fire/smoke model with a fixed class contract:

```text
0 = fire
1 = smoke
```

Candidate detections are not immediately treated as final alerts; the runtime applies temporal confirmation and additional alert logic.

## Camera Intrinsics

Estimate the camera matrix/distortion from checkerboard observations collected across varied positions/orientations.

## Distance

Fit the existing project distance engine from measured ground-contact observations. Verify using independent distances not used for fitting.

## Cross-Preset Geometry

Use manually selected same-landmark correspondences between configured overlapping PTZ presets.

Evaluation should separate:
- fit/train marks
- independent holdout marks

## Production Bearing

Relative preset geometry and absolute True North are distinct calibration problems. Absolute direction must be validated at the installation site.

## Reporting

Always report:
- sample counts
- train/holdout separation
- median
- mean where relevant
- P90
- maximum error
- limitations
