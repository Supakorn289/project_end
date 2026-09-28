#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d .git ]]; then
    echo "Run from the repository root."
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree is not clean."
    echo "Commit/stash your work before running this script."
    exit 1
fi

stamp="$(date +%Y%m%d_%H%M%S)"
backup_branch="archive/pre-public-release-${stamp}"

git branch "$backup_branch"
echo "Backup branch: $backup_branch"

# Remove known accidental/obsolete files from the active branch.
git rm -f --ignore-unmatch -- 'udo mkdir -p \'
git rm -f --ignore-unmatch -- \
  test_dynamic_bearing_reference_v1.BROKEN_20260909_112524.py

# Keep site calibration locally but remove it from Git tracking.
if git ls-files calibration | grep -q .; then
    git rm -r --cached --ignore-unmatch calibration || true
fi
mkdir -p calibration
touch calibration/.gitkeep
git add calibration/.gitkeep

# Remove known duplicate model artifacts from the active branch.
git rm -f --ignore-unmatch \
  fire_smoke_r3_e6_final.pt \
  models/fire_smoke_r3_e6_final.pt

git rm -r -f --ignore-unmatch \
  models/fire_smoke_r3_e6_final

# Ensure Git LFS is configured for canonical weights.
if command -v git-lfs >/dev/null 2>&1; then
    git lfs install
    git lfs track models/fire.pt
    git lfs track models/final/fire_smoke_r3_e6_final.pt
else
    echo "WARNING: git-lfs not installed."
    echo "Install Git LFS before the public release."
fi

git add \
  .gitignore \
  .gitattributes \
  README.md \
  README_TH.md \
  SECURITY.md \
  CONTRIBUTING.md \
  CHANGELOG.md \
  CITATION.cff \
  LICENSE-DECISION.md \
  PUBLIC_RELEASE_CHECKLIST.md \
  docs \
  research \
  scripts \
  .github

echo
echo "Prepared staging changes."
echo "Review with:"
echo "  git status"
echo "  git diff --cached"
echo
echo "Then run:"
echo "  bash scripts/repository_audit.sh"
echo
echo "No commit or push was performed automatically."
