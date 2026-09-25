#!/usr/bin/env python3

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PAIRS = [
    [1, 2],
    [2, 3],
    [3, 4],
    [4, 5],
    [1, 6],
    [6, 7],
    [7, 8],
    [8, 9],
    [5, 9],
]


def get_site_dir():
    value = os.environ.get(
        "MARK_SITE_DIR"
    )

    if value:
        return Path(value)

    pointer = Path(
        "/home/fire/current_site_setup_path.txt"
    )

    if not pointer.exists():
        raise RuntimeError(
            "MARK_SITE_DIR not set and "
            "site pointer not found"
        )

    return Path(
        pointer.read_text(
            encoding="utf-8"
        ).strip()
    )


SITE_DIR = get_site_dir()

CAPTURE_DIR = (
    SITE_DIR
    / "captures"
)

MARK_DIR = (
    SITE_DIR
    / "marks"
)

MARK_FILE = (
    MARK_DIR
    / "marks.json"
)

MARK_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def empty_state():
    return {
        "format": (
            "smart-fire-preset-marks-v1"
        ),
        "site_dir": str(
            SITE_DIR
        ),
        "pairs": {
            f"{a}-{b}": []
            for a, b in PAIRS
        },
    }


def load_state():
    if MARK_FILE.exists():
        return json.loads(
            MARK_FILE.read_text(
                encoding="utf-8"
            )
        )

    return empty_state()


def save_state(state):
    tmp = MARK_FILE.with_suffix(
        ".tmp"
    )

    tmp.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    tmp.replace(
        MARK_FILE
    )


HTML = r'''<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>Smart Fire - Preset Geometry MARK</title>

<style>
* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: sans-serif;
  background: #111;
  color: #eee;
}

header {
  padding: 12px 18px;
  background: #1d1d1d;
  position: sticky;
  top: 0;
  z-index: 10;
}

h2 {
  margin: 0 0 7px 0;
}

#status {
  font-size: 15px;
}

.images {
  display: flex;
  gap: 8px;
  padding: 8px;
}

.panel {
  width: 50%;
  position: relative;
}

.panel h3 {
  text-align: center;
  margin: 5px;
}

.imgwrap {
  position: relative;
  width: 100%;
}

.imgwrap img {
  width: 100%;
  display: block;
  border: 2px solid #444;
  cursor: crosshair;
}

.marker {
  position: absolute;
  width: 18px;
  height: 18px;
  border: 3px solid red;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
}

.marker span {
  position: absolute;
  left: 11px;
  top: -12px;
  font-weight: bold;
  color: yellow;
  text-shadow: 1px 1px 2px #000;
}

.pending {
  border-color: cyan;
}

.controls {
  padding: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

button {
  font-size: 16px;
  padding: 9px 16px;
  cursor: pointer;
}

.help {
  padding: 10px 18px 20px;
  color: #ccc;
  line-height: 1.55;
}

.good {
  color: #6cff6c;
}

.warn {
  color: #ffd45e;
}
</style>
</head>

<body>

<header>
  <h2>MARK-based Preset Geometry Calibration</h2>
  <div id="status"></div>
</header>

<div class="images">

  <div class="panel">
    <h3 id="titleA"></h3>

    <div class="imgwrap"
         id="wrapA">

      <img id="imgA">

    </div>
  </div>

  <div class="panel">
    <h3 id="titleB"></h3>

    <div class="imgwrap"
         id="wrapB">

      <img id="imgB">

    </div>
  </div>

</div>

<div class="controls">

  <button onclick="prevPair()">
    ← คู่ก่อนหน้า
  </button>

  <button onclick="undo()">
    Undo จุดล่าสุด
  </button>

  <button onclick="clearPair()">
    ล้างคู่นี้
  </button>

  <button onclick="saveState()">
    Save
  </button>

  <button onclick="nextPair()">
    คู่ถัดไป →
  </button>

</div>

<div class="help">
  <b>วิธี MARK:</b><br>
  1. เลือกจุดวัตถุจริงจุดเดียวกันในภาพซ้ายและขวา<br>
  2. คลิก <b>ภาพซ้ายก่อน</b> แล้วคลิกจุดเดียวกันใน <b>ภาพขวา</b><br>
  3. ทำประมาณ <b>5 จุดต่อคู่</b> โดยกระจายจุดในบริเวณ overlap<br>
  4. เลือกจุดจากโครงสร้างนิ่ง เช่น มุมผนัง เสา ขอบประตู ป้าย หรือวัตถุถาวร<br>
  5. หลีกเลี่ยงคน รถ เก้าอี้ หรือสิ่งที่เคลื่อนที่ได้<br><br>

  ภาพเหล่านี้ใช้เฉพาะ Setup ครั้งนี้เท่านั้น
  Runtime จริงจะไม่ใช้ image matching
</div>

<script>

const pairs = [
  [1,2],
  [2,3],
  [3,4],
  [4,5],
  [1,6],
  [6,7],
  [7,8],
  [8,9],
  [5,9],
];

let state = null;
let pairIndex = 0;
let pending = null;

async function loadState() {

  const response = await fetch(
    "/api/state"
  );

  state = await response.json();

  render();
}

function pairKey() {

  const p = pairs[pairIndex];

  return `${p[0]}-${p[1]}`;
}

function currentMarks() {

  const key = pairKey();

  if (!state.pairs[key]) {
    state.pairs[key] = [];
  }

  return state.pairs[key];
}

function render() {

  const [a,b] = pairs[pairIndex];

  document.getElementById(
    "titleA"
  ).textContent = `P${a}`;

  document.getElementById(
    "titleB"
  ).textContent = `P${b}`;

  document.getElementById(
    "imgA"
  ).src = `/image/${a}`;

  document.getElementById(
    "imgB"
  ).src = `/image/${b}`;

  drawMarkers();

  updateStatus();
}

function updateStatus() {

  const marks = currentMarks();

  let phase = pending
    ? "คลิกจุดเดียวกันในภาพขวา"
    : "คลิกจุดในภาพซ้าย";

  let cls = marks.length >= 5
    ? "good"
    : "warn";

  document.getElementById(
    "status"
  ).innerHTML =
    `คู่ ${pairIndex + 1}/${pairs.length} : ` +
    `<b>${pairKey()}</b> | ` +
    `<span class="${cls}">` +
    `${marks.length} จุด</span> | ${phase}`;
}

function removeMarkers(wrap) {

  wrap.querySelectorAll(
    ".marker"
  ).forEach(
    element => element.remove()
  );
}

function addMarker(
  wrap,
  point,
  number,
  pendingMarker=false
) {

  const img = wrap.querySelector(
    "img"
  );

  const marker = document.createElement(
    "div"
  );

  marker.className =
    "marker" +
    (
      pendingMarker
      ? " pending"
      : ""
    );

  marker.style.left =
    `${point[0] / img.naturalWidth * 100}%`;

  marker.style.top =
    `${point[1] / img.naturalHeight * 100}%`;

  const label = document.createElement(
    "span"
  );

  label.textContent = number;

  marker.appendChild(
    label
  );

  wrap.appendChild(
    marker
  );
}

function drawMarkers() {

  const wrapA = document.getElementById(
    "wrapA"
  );

  const wrapB = document.getElementById(
    "wrapB"
  );

  removeMarkers(
    wrapA
  );

  removeMarkers(
    wrapB
  );

  const marks = currentMarks();

  marks.forEach(
    (mark, index) => {

      addMarker(
        wrapA,
        mark.a,
        index + 1
      );

      addMarker(
        wrapB,
        mark.b,
        index + 1
      );
    }
  );

  if (pending) {

    addMarker(
      wrapA,
      pending,
      marks.length + 1,
      true
    );
  }
}

function imagePoint(
  event,
  img
) {

  const rect =
    img.getBoundingClientRect();

  const x =
    (
      event.clientX
      - rect.left
    )
    * img.naturalWidth
    / rect.width;

  const y =
    (
      event.clientY
      - rect.top
    )
    * img.naturalHeight
    / rect.height;

  return [
    Number(
      x.toFixed(2)
    ),
    Number(
      y.toFixed(2)
    ),
  ];
}

document.getElementById(
  "imgA"
).addEventListener(
  "click",
  event => {

    pending = imagePoint(
      event,
      event.target
    );

    drawMarkers();
    updateStatus();
  }
);

document.getElementById(
  "imgB"
).addEventListener(
  "click",
  event => {

    if (!pending) {

      alert(
        "กรุณาคลิกภาพซ้ายก่อน"
      );

      return;
    }

    const right = imagePoint(
      event,
      event.target
    );

    currentMarks().push(
      {
        a: pending,
        b: right,
      }
    );

    pending = null;

    drawMarkers();
    updateStatus();
  }
);

function undo() {

  if (pending) {
    pending = null;
  } else {
    currentMarks().pop();
  }

  drawMarkers();
  updateStatus();
}

function clearPair() {

  if (!confirm(
    "ล้าง MARK ของคู่นี้?"
  )) {
    return;
  }

  state.pairs[
    pairKey()
  ] = [];

  pending = null;

  drawMarkers();
  updateStatus();
}

async function saveState() {

  const response = await fetch(
    "/api/state",
    {
      method: "POST",
      headers: {
        "Content-Type":
          "application/json"
      },
      body: JSON.stringify(
        state
      ),
    }
  );

  if (!response.ok) {

    alert(
      "Save failed"
    );

    return;
  }

  updateStatus();
}

async function nextPair() {

  await saveState();

  pending = null;

  if (
    pairIndex
    < pairs.length - 1
  ) {
    pairIndex++;
  }

  render();
}

async function prevPair() {

  await saveState();

  pending = null;

  if (
    pairIndex > 0
  ) {
    pairIndex--;
  }

  render();
}

window.addEventListener(
  "beforeunload",
  () => {
    if (state) {
      navigator.sendBeacon(
        "/api/state",
        new Blob(
          [
            JSON.stringify(
              state
            )
          ],
          {
            type:
              "application/json"
          }
        )
      );
    }
  }
);

window.onload = loadState;

</script>
</body>
</html>
'''


class Handler(
    BaseHTTPRequestHandler
):

    def send_bytes(
        self,
        status,
        content_type,
        data,
    ):
        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(
                len(data)
            ),
        )

        self.end_headers()

        self.wfile.write(
            data
        )

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        if parsed.path == "/":

            self.send_bytes(
                200,
                "text/html; charset=utf-8",
                HTML.encode(
                    "utf-8"
                ),
            )

            return

        if parsed.path == "/api/state":

            payload = json.dumps(
                load_state(),
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )

            self.send_bytes(
                200,
                "application/json",
                payload,
            )

            return

        if parsed.path.startswith(
            "/image/"
        ):

            try:

                preset = int(
                    parsed.path.split(
                        "/"
                    )[-1]
                )

            except ValueError:

                self.send_error(
                    400
                )

                return

            image_path = (
                CAPTURE_DIR
                / f"preset_{preset}.jpg"
            )

            if not image_path.exists():

                self.send_error(
                    404
                )

                return

            self.send_bytes(
                200,
                "image/jpeg",
                image_path.read_bytes(),
            )

            return

        self.send_error(
            404
        )

    def do_POST(self):

        if self.path != "/api/state":

            self.send_error(
                404
            )

            return

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        raw = self.rfile.read(
            length
        )

        try:

            state = json.loads(
                raw.decode(
                    "utf-8"
                )
            )

            save_state(
                state
            )

        except Exception as exc:

            self.send_error(
                400,
                str(exc),
            )

            return

        self.send_bytes(
            200,
            "application/json",
            b'{"ok":true}',
        )

    def log_message(
        self,
        fmt,
        *args,
    ):
        return


def main():

    for preset in range(
        1,
        10,
    ):

        image = (
            CAPTURE_DIR
            / f"preset_{preset}.jpg"
        )

        if not image.exists():

            raise RuntimeError(
                f"Missing {image}"
            )

    save_state(
        load_state()
    )

    print(
        "=" * 72
    )

    print(
        "MARK-based Preset Geometry Tool"
    )

    print(
        "=" * 72
    )

    print(
        f"Site  : {SITE_DIR}"
    )

    print(
        f"Marks : {MARK_FILE}"
    )

    print(
        "URL   : http://0.0.0.0:8765"
    )

    print(
        "MARK 5 corresponding points "
        "for each pair."
    )

    print(
        "=" * 72
    )

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            8765,
        ),
        Handler,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()


if __name__ == "__main__":
    main()
