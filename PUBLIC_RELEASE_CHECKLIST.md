# Public Release Checklist

## Repository Hygiene

- [ ] Rename repository from a generic name such as `project_end` to `smart-fire-detection-v2`
- [ ] Replace README with the public README
- [ ] Add README_TH.md
- [ ] Add `.gitignore`
- [ ] Add `.gitattributes`
- [ ] Use Git LFS for canonical `.pt` model files
- [ ] Remove site-specific `calibration/` files from Git tracking
- [ ] Remove `calibration/.manager/` from Git tracking
- [ ] Remove broken/accidental files
- [ ] Remove duplicate model copies and extracted archives
- [ ] Confirm no credentials/private coordinates in current tree
- [ ] Scan Git history for previously committed secrets
- [ ] Rotate any credential that was ever committed

## Documentation

- [ ] INSTALLATION
- [ ] COMMISSIONING
- [ ] ARCHITECTURE
- [ ] TROUBLESHOOTING
- [ ] PORTFOLIO
- [ ] RESEARCH package
- [ ] CITATION.cff
- [ ] SECURITY.md
- [ ] CONTRIBUTING.md
- [ ] CHANGELOG.md

## Validation

- [ ] `bash -n deploy/install-manager-stack.sh`
- [ ] CI passes
- [ ] Clean Debian install tested
- [ ] LAB commissioning 0→100 tested
- [ ] Production field acceptance separately documented

## Release

- [ ] Decide/finalize LICENSE
- [ ] Create Git tag `v1.0.0`
- [ ] Create GitHub Release
- [ ] Attach release notes / checksums if model is distributed as release asset
- [ ] Add repository description and topics
- [ ] Add sanitized screenshots/demo
