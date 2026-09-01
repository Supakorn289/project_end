#!/usr/bin/env bash
# Smart Fire Detection v2 - Development & Testing Runner
# Automatically injects production environment variables and uses project venv

set -e
PROJECT_DIR="/opt/smart-fire-detection-v2"
ENV_FILE="/etc/smart-fire-detection/production.env"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"

if [ -f "${ENV_FILE}" ]; then
    set -a
    source "${ENV_FILE}"
    set +a
fi

cd "${PROJECT_DIR}"
exec "${VENV_PYTHON}" "$@"
