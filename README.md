# Smart Fire Detection v2

AI-assisted fire and smoke surveillance for PTZ IP cameras, with reproducible calibration, commissioning, revision control, activation, and rollback on Debian Linux.

> **Status**
> - Software Commissioning Manager: implemented
> - Fresh Debian bootstrap path: implemented
> - LAB commissioning workflow: implemented
> - Production field acceptance: must be completed per installation site
> - Research/engineering prototype: **not a certified fire alarm system**

## Overview

Smart Fire Detection v2 combines:

- PTZ IP camera scanning
- Fire/smoke AI inference
- Camera intrinsics calibration
- Distance estimation
- Cross-preset geometric calibration
- Bearing / True-North support
- Optional GPS localization
- Cross-preset fusion
- Temporal confirmation
- Telegram notification
- Web-based Commissioning Manager
- Immutable revision lifecycle
- Atomic activation and automatic rollback
- systemd deployment on Debian

The commissioning lifecycle is intentionally separated from the active runtime:

```text
EDITING
  ↓
CANDIDATE
  ↓
VALIDATED
  ↓
IMMUTABLE REVISION
  ↓
ACTIVATE
  ↓
HEALTH CHECK
  ↓
ACTIVE
```

If activation fails, the previous runtime configuration and calibration state are restored.

## Architecture

```text
                         ┌──────────────────────────┐
                         │  Commissioning Manager   │
                         │     Flask / Waitress     │
                         └────────────┬─────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
 Calibration Worker          Manager Root Agent         Revision Engine
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      │
                                      ▼
                               Runtime activation
                                      │
                                      ▼
┌────────────┐    RTSP/PTZ    ┌─────────────────┐
│ PTZ Camera │◀──────────────▶│ Detection Runtime│
└────────────┘                │     main.py      │
                              └────────┬────────┘
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 ▼                     ▼                      ▼
              AI model          Geometry/Distance       Alert/Telegram
                                Bearing/GPS/Fusion
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Reference Platform

- Debian 13 x86_64
- Python 3.12
- CPU PyTorch runtime
- OpenCV
- Ultralytics
- Flask + Waitress
- systemd

Exact Python package versions are defined in `requirements.txt`.

## Quick Start — Fresh Debian

Clone into a staging directory:

```bash
git clone <REPOSITORY_URL> ~/smart-fire-release
cd ~/smart-fire-release
```

Run the bootstrap installer:

```bash
sudo ./deploy/install-manager-stack.sh
```

After installation, verify the commissioning services:

```bash
systemctl is-active smart-fire-manager.service
systemctl is-active smart-fire-manager-agent.service
systemctl is-active smart-fire-calibration-worker.service
systemctl is-active smart-fire-calibration-watchdog.service
```

Before site commissioning, the Detection service is expected to remain inactive/disabled.

Open:

```text
http://<SERVER-IP>:5050/
```

Then use the web workflow:

```text
New Installation
→ Camera / RTSP
→ PTZ Presets
→ Camera Intrinsics
→ Distance Calibration
→ Distance Verification
→ Cross-Preset Geometry
→ True North / GPS (Production)
→ Telegram
→ Final Verification
→ Create Revision
→ Check Activation Plan
→ Activate
```

Detailed instructions:

- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/COMMISSIONING.md`](docs/COMMISSIONING.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

## AI Model Contract

Runtime artifact:

```text
models/fire.pt
```

Master artifact:

```text
models/final/fire_smoke_r3_e6_final.pt
```

Expected classes:

```text
0 = fire
1 = smoke
```

The runtime validates the production model artifact by SHA-256 before use.

### Model Distribution

Use **Git LFS** for canonical `.pt` files, or publish model weights as versioned GitHub Release assets. Do not commit extracted PyTorch archive internals.

## Repository Layout

```text
.
├── README.md
├── README_TH.md
├── CITATION.cff
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── requirements.txt
├── requirements-dev.txt
├── main.py
├── config.py
├── camera.py
├── detection.py
├── calibration.py
├── geometry.py
├── ptz.py
├── manager/
├── deploy/
├── models/
│   ├── fire.pt
│   └── final/
│       └── fire_smoke_r3_e6_final.pt
├── calibration/
│   └── .gitkeep
├── tests/
├── docs/
├── research/
└── assets/
```

Some hardware/calibration CLI scripts remain at repository root for compatibility with the current Commissioning Manager tool registry.

## Testing

Basic repository checks:

```bash
bash -n deploy/install-manager-stack.sh
python -m compileall -q manager
python -m py_compile main.py config.py camera.py detection.py calibration.py geometry.py ptz.py
```

On an installed system:

```bash
PYTHONPATH="$PWD" ./venv/bin/python manager_final_selftest.py
```

Unit tests:

```bash
python -m pytest
```

Hardware-dependent tests can move the PTZ camera. Read [`TESTING.md`](TESTING.md) before running them.

## Research

Research-facing documentation is kept under [`research/`](research/):

- `METHODOLOGY.md`
- `REPRODUCIBILITY.md`
- `RESULTS.md`
- `MODEL_CARD.md`
- `DATA_AVAILABILITY.md`

Use [`CITATION.cff`](CITATION.cff) when citing the software.

## Portfolio

This repository demonstrates work in:

- computer vision / edge AI
- PTZ camera control and synchronization
- calibrated bearing and distance estimation
- geometric localization
- web-based commissioning tooling
- Linux/systemd deployment
- privilege separation
- transactional activation/rollback
- reproducible research engineering

See [`docs/PORTFOLIO.md`](docs/PORTFOLIO.md).

## Security / Privacy

Never commit:

- camera usernames/passwords
- Telegram tokens/chat IDs
- precise private installation coordinates
- manager tokens
- production environment files
- private camera captures
- site-specific calibration/runtime state

See [`SECURITY.md`](SECURITY.md).

## Safety

This project is a research/engineering detection system. It is not a replacement for certified fire detectors, fire alarms, suppression systems, emergency-response systems, or evacuation procedures.

## License

This repository uses Ultralytics components. Before publishing the final repository license, read [`LICENSE-DECISION.md`](LICENSE-DECISION.md). If the project is distributed under the open-source Ultralytics path, use an AGPL-3.0-compatible repository license unless another applicable Ultralytics license covers the project.

## Citation

See [`CITATION.cff`](CITATION.cff).
