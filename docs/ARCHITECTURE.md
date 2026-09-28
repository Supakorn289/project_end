# Architecture

## Runtime

`main.py` coordinates the production scan pipeline:

```text
PTZ move
→ synchronized/fresh frame
→ AI inference
→ temporal confirmation
→ calibrated geometry
→ distance / bearing
→ cross-preset fusion
→ pending alert finalization
→ notification
```

## Commissioning Manager

`manager/` provides the web commissioning workflow and protected APIs.

Major responsibilities:

- installation discovery
- LAB / PRODUCTION planning
- camera setup/test
- PTZ verification
- camera intrinsics
- distance calibration/verification
- cross-preset geometry
- True-North / location metadata
- Telegram setup/test
- final verification
- immutable revisions
- activation planning

## Privilege Separation

The web process should not execute arbitrary privileged commands.

Privileged actions are delegated to the narrowly scoped Manager Agent over a protected Unix socket.

## Calibration Worker

Hardware/calibration operations are isolated in a worker and coordinated with:

- hardware lock
- calibration lease
- watchdog recovery
- private candidate storage

## Revision Lifecycle

```text
EDITING
→ CANDIDATE
→ VALIDATED_CANDIDATE
→ immutable revision
→ ACTIVE
```

Calibration work must not overwrite the active runtime directly.

## Activation Transaction

```text
validate revision
→ acquire locks
→ backup runtime
→ stop detection
→ deploy immutable calibration
→ atomic active-pointer switch
→ write runtime environment
→ preflight
→ optional production sweep
→ start detection
→ stability check
→ enable service
→ ACTIVE
```

On failure, restore the previous environment, active files/pointers, running state, and boot-enabled state.
