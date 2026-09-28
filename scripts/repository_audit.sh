#!/usr/bin/env bash
set -euo pipefail

fail=0

bad() {
    echo "FAIL: $*"
    fail=1
}

good() {
    echo "PASS: $*"
}

# Required public-repository files.
for f in \
    README.md \
    README_TH.md \
    .gitignore \
    .gitattributes \
    CITATION.cff \
    SECURITY.md \
    CONTRIBUTING.md \
    CHANGELOG.md \
    docs/INSTALLATION.md \
    docs/COMMISSIONING.md \
    docs/ARCHITECTURE.md \
    research/METHODOLOGY.md \
    research/REPRODUCIBILITY.md \
    research/RESULTS.md
do
    if [[ -f "$f" ]]; then
        good "$f"
    else
        bad "missing $f"
    fi
done

# Known accidental/obsolete files.
[[ ! -e 'udo mkdir -p \' ]] || bad "accidental file exists: udo mkdir -p \\"
[[ ! -e test_dynamic_bearing_reference_v1.BROKEN_20260909_112524.py ]] || \
    bad "BROKEN diagnostic file is still in active tree"

# Private runtime state must not be tracked.
if git ls-files 'calibration/.manager/**' | grep -q .; then
    bad "calibration/.manager is tracked"
else
    good "manager runtime state is not tracked"
fi

tracked_calibration="$(
    git ls-files 'calibration/**' \
      | grep -v '^calibration/.gitkeep$' \
      || true
)"
if [[ -n "$tracked_calibration" ]]; then
    echo "$tracked_calibration"
    bad "site/generated calibration files are tracked"
else
    good "only calibration/.gitkeep is tracked"
fi

# Canonical model paths.
model_files="$(
    git ls-files '*.pt' || true
)"
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    case "$f" in
      models/fire.pt|models/final/fire_smoke_r3_e6_final.pt) ;;
      *) bad "non-canonical model weight is tracked: $f" ;;
    esac
done <<< "$model_files"

# A basic secret-pattern scan of tracked text.
if git grep -nE \
  '(TELEGRAM_TOKEN|CAMERA_PWD|CAMERA_PASSWORD|PASSWORD|API_KEY|SECRET_KEY)=[^[:space:]]+' \
  -- ':!*.example' ':!*.md' 2>/dev/null \
  | grep -vE '=(["'\'']?["'\'']?)$' \
  | grep -q .; then
    bad "possible populated secret assignment found in tracked files"
else
    good "no obvious populated secret assignment found"
fi

if [[ "$fail" -ne 0 ]]; then
    echo
    echo "PUBLIC_REPOSITORY_AUDIT=FAIL"
    exit 1
fi

echo
echo "PUBLIC_REPOSITORY_AUDIT=PASS"
