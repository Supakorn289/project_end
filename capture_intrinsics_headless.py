from pathlib import Path
import time
import cv2

from camera import LatestFrameCamera
from calibrate_intrinsics import (
    find_corners,
    calculate_sharpness,
    calculate_board_coverage,
)

TARGET = 25

out = Path("calibration/intrinsics_v1/captures")
out.mkdir(parents=True, exist_ok=True)

print("Starting camera...")
cam = LatestFrameCamera().start()

deadline = time.monotonic() + 10.0

while cam.latest(copy=False) is None:
    if time.monotonic() >= deadline:
        cam.stop()
        raise SystemExit("❌ RTSP timeout")
    time.sleep(0.1)

print("✅ RTSP ready")
print("")
print("วิธีใช้:")
print("  จัด Checkerboard แล้วกด Enter = ถ่าย")
print("  เปลี่ยนตำแหน่ง/มุมทุกภาพ")
print("  q + Enter = จบก่อนครบ 25 ภาพ")

saved = 0

try:
    while saved < TARGET:
        cmd = input(
            f"\n[{saved}/{TARGET}] พร้อมแล้วกด Enter: "
        ).strip().lower()

        if cmd == "q":
            break

        packet = cam.latest(copy=True)

        if packet is None:
            print("❌ ไม่มี frame")
            continue

        frame = packet.frame

        if frame is None:
            print("❌ frame ว่าง")
            continue

        h, w = frame.shape[:2]

        corners = find_corners(frame)

        if corners is None:
            print("❌ REJECT: ไม่พบ Checkerboard")
            continue

        sharpness = calculate_sharpness(frame)

        coverage = calculate_board_coverage(
            corners,
            w,
            h,
        )

        if coverage < 0.02:
            print(
                "❌ REJECT: Checkerboard เล็กเกินไป "
                f"| coverage={coverage * 100:.1f}%"
            )
            continue

        saved += 1
        path = out / f"calib_{saved:03d}.jpg"

        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(
                f"บันทึกภาพไม่ได้: {path}"
            )

        print(
            f"✅ SAVED {path.name}"
            f" | shape={frame.shape}"
            f" | sharp={sharpness:.1f}"
            f" | coverage={coverage * 100:.1f}%"
        )

finally:
    cam.stop()

print("")
print("=" * 60)
print(f"✅ Captured total: {saved}")
print(f"Saved directory: {out.resolve()}")
print("=" * 60)
