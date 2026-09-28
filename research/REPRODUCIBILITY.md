# Reproducibility

## Software

Record:

```bash
git rev-parse HEAD
python --version
pip freeze
```

Record model integrity:

```bash
sha256sum models/fire.pt
sha256sum models/final/fire_smoke_r3_e6_final.pt
```

## Installation

Use the repository bootstrap installer on fresh Debian:

```bash
sudo ./deploy/install-manager-stack.sh
```

## Calibration

Do not reuse another installation site's generated `calibration/` state.

Commission the site through Manager and create a validated immutable revision.

## Experimental Artifacts

For publication, export only sanitized artifacts needed to reproduce reported metrics. Do not publish credentials, private coordinates, or private camera images.

## Versioning

A research result should reference:
- Git tag
- Git commit
- model SHA-256
- calibration revision ID
- hardware configuration
