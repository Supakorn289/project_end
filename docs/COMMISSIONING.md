# Commissioning 0→100

Recommended sequence:

```text
Fresh Debian
→ Bootstrap
→ LAB Site
→ Camera / RTSP
→ PTZ Presets
→ Intrinsics
→ Distance
→ Distance Verification
→ Cross-Preset Geometry
→ Final Verification
→ Immutable Revision
→ LAB Activation
→ Runtime Soak
→ PRODUCTION Mode
→ True North / GPS
→ Telegram
→ Production Final Verification
→ Production Revision
→ Activate
→ Full Sweep
→ Runtime Acceptance
```

## PTZ Presets

Reference relative layout:

```text
P1    0°
P2  +45°
P3  +90°
P4 +135°
P5 +177.5°
P6  -45°
P7  -90°
P8 -135°
P9 -177.5°
```

Program camera presets using the camera/vendor utility and then verify them through Manager.

## Intrinsics

Capture checkerboard views across image position, distance and orientation. Avoid collecting only near-duplicate views.

## Distance

Use ground-contact points. Keep verification measurements separate from fitting measurements.

## Cross-Preset Geometry

Use stable landmarks that are visible in both presets. Keep holdout marks independent from fitting marks.

## Production

Do not bypass production field requirements. True-North/GPS and notification checks must reflect the actual installation site.

## Revision / Activation

Only a validated immutable revision should be activatable.

If activation fails, inspect the rollback state before retrying.
