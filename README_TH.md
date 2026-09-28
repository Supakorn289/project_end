# Smart Fire Detection v2 — ภาษาไทย

ระบบตรวจจับไฟและควันด้วย AI สำหรับกล้อง PTZ IP Camera พร้อมระบบคาลิเบรตระยะทาง/ทิศทาง, Cross-Preset Geometry, Web Commissioning Manager, Revision, Atomic Activation และ Automatic Rollback

## สถานะ

- Software Commissioning Manager: พัฒนาเสร็จ
- Fresh Debian bootstrap: พัฒนาเสร็จ
- LAB workflow: พัฒนาเสร็จ
- Production field acceptance: ต้องทดสอบจริงแยกตามสถานที่ติดตั้ง
- เป็นระบบวิจัย/วิศวกรรม ไม่ใช่อุปกรณ์ Fire Alarm ที่ผ่านการรับรองมาตรฐาน

## ติดตั้งบนเครื่องใหม่

```bash
git clone <REPOSITORY_URL> ~/smart-fire-release
cd ~/smart-fire-release
sudo ./deploy/install-manager-stack.sh
```

จากนั้นเปิด:

```text
http://<SERVER-IP>:5050/
```

และทำตาม:

```text
New Installation
→ Camera
→ PTZ
→ Intrinsics
→ Distance
→ Geometry
→ True North / GPS (Production)
→ Telegram
→ Final Verification
→ Create Revision
→ Check Plan
→ Activate
```

รายละเอียด:
- `docs/INSTALLATION.md`
- `docs/COMMISSIONING.md`
- `docs/TROUBLESHOOTING.md`

## สิ่งที่ห้าม Commit

- รหัสกล้อง
- Telegram Token / Chat ID
- พิกัดสถานที่ติดตั้งจริง
- Manager Token
- `production.env`
- ภาพกล้องส่วนตัว
- calibration/site state ของหน้างาน
- revision/candidate/runtime state ใน `calibration/.manager/`

## สำหรับ Portfolio / งานวิจัย

- `docs/PORTFOLIO.md`
- `research/METHODOLOGY.md`
- `research/REPRODUCIBILITY.md`
- `research/RESULTS.md`
- `research/MODEL_CARD.md`
- `CITATION.cff`
