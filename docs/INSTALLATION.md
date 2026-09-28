# Fresh Debian Installation

## Reference Target

- Debian 13
- x86_64
- Python 3.12
- systemd
- CPU inference reference runtime

## Install

Clone into a staging directory:

```bash
git clone <REPOSITORY_URL> ~/smart-fire-release
cd ~/smart-fire-release
```

If the repository uses Git LFS:

```bash
sudo apt-get install git-lfs
git lfs install
git lfs pull
```

Run:

```bash
sudo ./deploy/install-manager-stack.sh
```

## Expected State

After bootstrap and before commissioning:

```text
smart-fire-manager.service                 active
smart-fire-manager-agent.service           active
smart-fire-calibration-worker.service      active
smart-fire-calibration-watchdog.service    active
smart-fire-detection.service               inactive
smart-fire-detection.service               disabled
```

Open:

```text
http://<SERVER-IP>:5050/
```

## Important

Do not copy `calibration/` from an existing installation into a new site. Calibration is site/camera dependent.
