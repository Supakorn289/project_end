# Troubleshooting

## Service Status

```bash
systemctl is-active \
  smart-fire-manager.service \
  smart-fire-manager-agent.service \
  smart-fire-detection.service \
  smart-fire-calibration-worker.service \
  smart-fire-calibration-watchdog.service
```

## Manager Log

```bash
sudo journalctl -u smart-fire-manager.service -n 100 --no-pager
```

## Detection Log

```bash
sudo journalctl -u smart-fire-detection.service -n 100 --no-pager
```

## Manager Agent Log

```bash
sudo journalctl -u smart-fire-manager-agent.service -n 100 --no-pager
```

## Worker Log

```bash
sudo journalctl -u smart-fire-calibration-worker.service -n 100 --no-pager
```

## Bootstrap Syntax Check

```bash
bash -n deploy/install-manager-stack.sh
```

## Model Integrity

Use the project model inspection/preflight tools. Do not replace the production model with an unverified checkpoint.

## Activation Failure

Do not manually overwrite active calibration immediately. Check the activation/rollback record first.
