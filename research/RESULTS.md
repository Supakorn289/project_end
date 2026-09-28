# Results

> This file distinguishes historical laboratory validation from production field acceptance.

## AI Model Contract

Reference release:

```text
Model release: R3-E6
Classes: {0: fire, 1: smoke}
Runtime: CPU PyTorch
```

The production code checks the expected model SHA-256 before loading.

## Historical Cross-Preset Geometry Validation

A historical lab validation run reported:

| Metric | Result |
|---|---:|
| Holdout targets | 353 |
| Median absolute azimuth error | 0.738° |
| Mean absolute azimuth error | 0.853° |
| P90 absolute azimuth error | 1.693° |
| Maximum absolute azimuth error | 4.523° |
| Median 3D angular error | 0.885° |
| P90 3D angular error | 1.856° |
| Pair checks passed | 9 / 9 |

These values are **historical lab results** and must not be presented as accuracy guarantees for a new installation.

## Historical Distance Calibration Example

One lab calibration used 5 points over approximately 2.11–5.17 m and reported pixel RMSE ≈ 3.68 px.

Distance performance is site/camera dependent and must be recalibrated and independently verified for each installation.

## Deployment/Manager Verification

The software project has passed local checks for:
- Manager routes
- Manager/Agent/Worker/Watchdog service startup
- DRAFT revision activation rejection
- self-contained revision snapshots
- bootstrap syntax/systemd validation

## Production Field Acceptance

Not a universal result.

Each deployment must record its own:
- camera/RTSP verification
- PTZ verification
- intrinsics
- distance validation
- geometry holdout
- True-North/GPS validation
- notification test
- activation/full sweep
- runtime soak
