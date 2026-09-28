# Portfolio Presentation Guide

## One-line Project Description

> Smart Fire Detection v2 is an edge-AI PTZ surveillance system that detects fire/smoke and combines calibrated camera geometry, distance estimation, cross-preset fusion, and a web-based commissioning/deployment workflow.

## Strong Portfolio Sections

### Problem
Fixed-camera detection leaves blind spots and does not directly provide a calibrated direction/distance workflow.

### Engineering Solution
A PTZ camera scans nine presets, AI identifies fire/smoke candidates, and calibrated geometry converts image observations into site-relative bearing/distance estimates.

### Systems Engineering
The project includes a separate Commissioning Manager, immutable revisions, privilege separation, systemd deployment, activation health checks, and automatic rollback.

### Research / Validation
Present:
- calibration method
- independent holdout design
- model integrity contract
- geometry error metrics
- distance verification
- runtime stability testing
- limitations and future work

## Recommended Repository Media

Add only public/sanitized media:

```text
assets/
├── hero.png
├── manager-overview.png
├── commissioning-wizard.png
├── architecture.png
├── detection-demo.gif
└── hardware-setup.jpg
```

Blur/remove:
- private IP addresses
- usernames/passwords
- Telegram IDs
- private site coordinates
- faces/license plates if not needed

## Resume Bullet Example

> Developed an AI PTZ fire/smoke surveillance platform on Debian using Python, OpenCV, Ultralytics YOLO, calibrated camera geometry, web-based commissioning, systemd services, and transactional activation/rollback.
