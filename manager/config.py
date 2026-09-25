from pathlib import Path

PROJECT_ROOT = Path("/opt/smart-fire-detection-v2")

CALIBRATION_ROOT = PROJECT_ROOT / "calibration"
SITES_ROOT = CALIBRATION_ROOT / "sites"

ACTIVE_ROTATION = CALIBRATION_ROOT / "preset_rotation_ACTIVE.json"
ACTIVE_DISTANCE = CALIBRATION_ROOT / "distance_global.json"
SITE_FILE = CALIBRATION_ROOT / "site.json"

DETECTION_SERVICE = "smart-fire-detection.service"
DASHBOARD_SERVICE = "smart-fire-dashboard.service"

MANAGER_HOST = "0.0.0.0"
MANAGER_PORT = 5050

# Phase 1:
# Manager อ่านสถานะอย่างเดียว
# ยังไม่อนุญาตให้แก้ calibration หรือ control service
READ_ONLY = True
