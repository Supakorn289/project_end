# Contributing

## Development Setup

```bash
python3.12 -m venv venv
./venv/bin/python -m pip install -U pip
./venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 torchvision==0.26.0
./venv/bin/python -m pip install -r requirements-dev.txt
```

## Before a Pull Request

```bash
bash -n deploy/install-manager-stack.sh
python -m py_compile main.py config.py camera.py detection.py calibration.py geometry.py ptz.py
python -m compileall -q manager
python -m pytest
```

## Rules

- Never commit secrets or site-specific runtime state.
- Do not bypass Final Verification.
- Do not activate non-validated revisions.
- Preserve production model integrity checks.
- Do not add arbitrary shell execution to the privileged Manager Agent.
- Clearly mark tests that move the PTZ camera.
