#!/usr/bin/env bash

set -euo pipefail


PROJECT_ROOT="/opt/smart-fire-detection-v2"

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"

SOURCE_ROOT="$(
    cd -- "${SCRIPT_DIR}/.." && pwd
)"


if [ "${EUID}" -ne 0 ]; then
    echo "Run with sudo/root"
    exit 1
fi


echo "=========================================="
echo " Smart Fire Detection v2 Bootstrap"
echo "=========================================="


# ------------------------------------------------------------
# User / group
# ------------------------------------------------------------

if ! getent group fire >/dev/null; then
    groupadd --system fire
fi


if ! id fire >/dev/null 2>&1; then

    useradd \
        --create-home \
        --home-dir /home/fire \
        --shell /bin/bash \
        --gid fire \
        fire
fi


# ------------------------------------------------------------
# OS dependencies
# ------------------------------------------------------------

apt-get update

DEBIAN_FRONTEND=noninteractive \
apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    git \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncurses-dev \
    libgdbm-dev \
    uuid-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    llvm \
    make \
    pkg-config \
    rsync \
    tk-dev \
    wget \
    xz-utils \
    zlib1g-dev


# ------------------------------------------------------------
# Python 3.12
# ------------------------------------------------------------

PYTHON_BIN=""


for candidate in \
    /usr/local/bin/python3.12 \
    /usr/bin/python3.12
do

    if [ -x "$candidate" ]; then

        PYTHON_BIN="$candidate"
        break
    fi

done


if [ -z "$PYTHON_BIN" ]; then

    echo
    echo "Python 3.12 not found."
    echo "Building Python 3.12.10..."

    cd /usr/src

    if [ ! -f Python-3.12.10.tgz ]; then

        wget \
        https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tgz
    fi


    rm -rf \
    Python-3.12.10

    tar xf \
    Python-3.12.10.tgz

    cd \
    Python-3.12.10


    ./configure \
        --prefix=/usr/local \
        --with-ensurepip=install


    make \
        -j"$(
            nproc
        )"


    make \
        altinstall


    PYTHON_BIN="/usr/local/bin/python3.12"
fi


VERSION="$(
    "$PYTHON_BIN" \
    -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"


if [ "$VERSION" != "3.12" ]; then

    echo "Python version must be 3.12"
    exit 1
fi


# ------------------------------------------------------------
# Project install
# ------------------------------------------------------------

if [ "$SOURCE_ROOT" != "$PROJECT_ROOT" ]; then

    mkdir -p \
    "$PROJECT_ROOT"


    rsync \
        -a \
        --delete \
        --exclude 'venv/' \
        --exclude '__pycache__/' \
        --exclude 'calibration/' \
        --exclude 'static/status.json' \
        --exclude 'static/events/' \
        "$SOURCE_ROOT/" \
        "$PROJECT_ROOT/"
fi


cd \
"$PROJECT_ROOT"


chown -R \
fire:fire \
"$PROJECT_ROOT"


# ------------------------------------------------------------
# Venv
# ------------------------------------------------------------

if [ ! -x venv/bin/python ]; then

    runuser -u fire -- \
    "$PYTHON_BIN" \
    -m venv \
    venv
fi


runuser -u fire -- \
venv/bin/python \
-m pip install \
--upgrade \
pip


echo
echo "Installing approved CPU PyTorch runtime..."


runuser -u fire -- \
venv/bin/python \
-m pip install \
--index-url https://download.pytorch.org/whl/cpu \
torch==2.11.0 \
torchvision==0.26.0


runuser -u fire -- \
venv/bin/python \
-m pip install \
-r requirements.txt


# ------------------------------------------------------------
# Persistent config
# ------------------------------------------------------------

install -d \
    -o root \
    -g fire \
    -m 0750 \
    /etc/smart-fire-detection


if [ ! -f /etc/smart-fire-detection/production.env ]; then

    if [ -f deploy/production.env.example ]; then

        install \
            -o root \
            -g fire \
            -m 0600 \
            deploy/production.env.example \
            /etc/smart-fire-detection/production.env

    else

        cat > \
        /etc/smart-fire-detection/production.env <<'EOF'
ENABLE_TRUE_NORTH=0
ENABLE_GPS=0
EOF

        chown \
            root:fire \
            /etc/smart-fire-detection/production.env

        chmod 0600 \
            /etc/smart-fire-detection/production.env
    fi

fi


# ------------------------------------------------------------
# Manager token
# ------------------------------------------------------------

if [ ! -s /etc/smart-fire-detection/manager.token ]; then

    TOKEN="$(
        "$PYTHON_BIN" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
    )"


    printf '%s\n' \
    "$TOKEN" \
    > \
    /etc/smart-fire-detection/manager.token


    chown \
        root:fire \
        /etc/smart-fire-detection/manager.token


    chmod 0640 \
        /etc/smart-fire-detection/manager.token


    TOKEN_CREATED=1

else

    TOKEN_CREATED=0
    TOKEN=""
fi


# ------------------------------------------------------------
# Manager persistent workspace
# ------------------------------------------------------------

install -d \
    -o fire \
    -g fire \
    -m 0750 \
    "$PROJECT_ROOT/calibration/.manager"

install -d \
    -o fire \
    -g fire \
    -m 0750 \
    "$PROJECT_ROOT/calibration/.manager/candidates"

install -d \
    -o fire \
    -g fire \
    -m 0750 \
    "$PROJECT_ROOT/calibration/.manager/revisions"

install -d \
    -o fire \
    -g fire \
    -m 0750 \
    "$PROJECT_ROOT/calibration/.manager/activations"


# ------------------------------------------------------------
# Root Agent
# ------------------------------------------------------------

install -d \
    -o root \
    -g root \
    -m 0755 \
    /usr/local/libexec


install \
    -o root \
    -g root \
    -m 0755 \
    deploy/libexec/smart-fire-manager-agent \
    /usr/local/libexec/smart-fire-manager-agent


# ------------------------------------------------------------
# systemd
# ------------------------------------------------------------

for unit in \
    smart-fire-manager.service \
    smart-fire-manager-agent.service \
    smart-fire-calibration-worker.service \
    smart-fire-calibration-watchdog.service
do

    install \
        -o root \
        -g root \
        -m 0644 \
        "deploy/systemd/$unit" \
        "/etc/systemd/system/$unit"

done


for dropin_dir in \
    deploy/systemd/*.service.d
do

    if [ ! -d "$dropin_dir" ]; then
        continue
    fi


    target="/etc/systemd/system/$(
        basename "$dropin_dir"
    )"


    install -d \
        -o root \
        -g root \
        -m 0755 \
        "$target"


    cp -a \
        "$dropin_dir/." \
        "$target/"


    chown -R \
        root:root \
        "$target"

done


# Existing detection/dashboard units.
if [ -f deploy/smart-fire-detection.service ]; then

    install \
        -o root \
        -g root \
        -m 0644 \
        deploy/smart-fire-detection.service \
        /etc/systemd/system/smart-fire-detection.service
fi


if [ -f deploy/smart-fire-dashboard.service ]; then

    install \
        -o root \
        -g root \
        -m 0644 \
        deploy/smart-fire-dashboard.service \
        /etc/systemd/system/smart-fire-dashboard.service
fi


systemctl daemon-reload


# ------------------------------------------------------------
# Compile smoke
# ------------------------------------------------------------

runuser -u fire -- \
env \
PYTHONPATH="$PROJECT_ROOT" \
"$PROJECT_ROOT/venv/bin/python" \
-m py_compile \
"$PROJECT_ROOT/main.py" \
"$PROJECT_ROOT/manager/app.py" \
"$PROJECT_ROOT/manager/calibration_worker.py" \
"$PROJECT_ROOT/manager/calibration_watchdog.py"


/usr/bin/python3 \
-m py_compile \
/usr/local/libexec/smart-fire-manager-agent


# ------------------------------------------------------------
# Start commissioning infrastructure
# Detection remains inactive until setup/activation.
# ------------------------------------------------------------

systemctl enable \
    smart-fire-manager-agent.service \
    smart-fire-calibration-worker.service \
    smart-fire-calibration-watchdog.service \
    smart-fire-manager.service


systemctl restart \
    smart-fire-manager-agent.service \
    smart-fire-calibration-worker.service \
    smart-fire-calibration-watchdog.service \
    smart-fire-manager.service


# Detection remains disabled until a validated Revision
# completes Atomic Activation successfully.
systemctl stop \
    smart-fire-detection.service \
    2>/dev/null || true

systemctl disable \
    smart-fire-detection.service \
    2>/dev/null || true


sleep 3


echo
echo "=========================================="
echo " Installation complete"
echo "=========================================="

echo
echo "Manager:"
echo "  http://<SERVER-IP>:5050/"

echo
echo "Services:"

for service in \
    smart-fire-manager-agent.service \
    smart-fire-calibration-worker.service \
    smart-fire-calibration-watchdog.service \
    smart-fire-manager.service
do

    printf '  %-44s %s\n' \
        "$service" \
        "$(
            systemctl is-active \
            "$service" \
            2>/dev/null \
            || true
        )"

done


if [ "$TOKEN_CREATED" = "1" ]; then

    echo
    echo "FIRST LOGIN MANAGER TOKEN:"
    echo
    echo "$TOKEN"
    echo
    echo "Store this token securely."
fi


echo
echo "Next:"
echo "  Open Manager → New Installation"
echo "  Complete Wizard → Final Verification"
echo "  Create Revision → Activate"
echo
