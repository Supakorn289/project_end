#!/usr/bin/env python3

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


VALIDATION_DIR = Path(
    "/home/fire/current_negative_side_final_path.txt"
).read_text(
    encoding="utf-8"
).strip()

VALIDATION_DIR = Path(VALIDATION_DIR)

CAPTURE_DIR = VALIDATION_DIR / "captures"

MARK_FILE = (
    VALIDATION_DIR
    / "negative_side_marks.json"
)


# key, step A, preset A, step B, preset B
PAIRS = [
    ("1-6", 1, 1, 2, 6),
    ("6-7", 2, 6, 3, 7),
    ("7-8", 3, 7, 4, 8),
    ("8-9", 4, 8, 5, 9),
    ("5-9", 6, 5, 5, 9),
]


def empty_state():
    return {
        "format": (
            "smart-fire-negative-side-"
            "marks-v1"
        ),
        "validation_dir": str(
            VALIDATION_DIR
        ),
        "pairs": {
            key: []
            for key, *_ in PAIRS
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
    temp = MARK_FILE.with_suffix(
        ".tmp"
    )

    temp.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp.replace(
        MARK_FILE
    )


def filename(
    step,
    preset,
):
    return (
        f"step_{step:02d}_"
        f"p{preset}.jpg"
    )


HTML = r'''<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Negative-Side Bearing Validation</title>

<style>
* { box-sizing:border-box; }

body {
  margin:0;
  background:#111;
  color:#eee;
  font-family:sans-serif;
}

header {
  position:sticky;
  top:0;
  z-index:20;
  background:#1d1d1d;
  padding:12px 18px;
}

h2 {
  margin:0 0 6px;
}

.images {
  display:flex;
  gap:8px;
  padding:8px;
}

.panel {
  width:50%;
}

.panel h3 {
  text-align:center;
  margin:5px;
}

.wrap {
  position:relative;
}

.wrap img {
  width:100%;
  display:block;
  border:2px solid #444;
  cursor:crosshair;
}

.marker {
  position:absolute;
  width:18px;
  height:18px;
  border:3px solid #ff3b30;
  border-radius:50%;
  transform:translate(-50%,-50%);
  pointer-events:none;
}

.marker.pending {
  border-color:#00e5ff;
}

.marker span {
  position:absolute;
  left:12px;
  top:-13px;
  color:#ffe600;
  font-weight:bold;
  text-shadow:1px 1px 2px #000;
}

.controls {
  display:flex;
  justify-content:center;
  gap:8px;
  flex-wrap:wrap;
  padding:10px;
}

button {
  font-size:16px;
  padding:9px 15px;
  cursor:pointer;
}

.help {
  padding:10px 18px 22px;
  line-height:1.55;
  color:#ccc;
}

.good { color:#6cff6c; }
.warn { color:#ffd45e; }
</style>
</head>

<body>

<header>
  <h2>Negative-Side Same-target Validation</h2>
  <div id="status"></div>
</header>

<div class="images">

  <div class="panel">
    <h3 id="titleA"></h3>
    <div class="wrap" id="wrapA">
      <img id="imgA">
    </div>
  </div>

  <div class="panel">
    <h3 id="titleB"></h3>
    <div class="wrap" id="wrapB">
      <img id="imgB">
    </div>
  </div>

</div>

<div class="controls">

  <button onclick="previous()">
    ← คู่ก่อนหน้า
  </button>

  <button onclick="undo()">
    Undo
  </button>

  <button onclick="clearPair()">
    ล้างคู่นี้
  </button>

  <button onclick="save()">
    Save
  </button>

  <button onclick="next()">
    คู่ถัดไป →
  </button>

</div>

<div class="help">
<b>Negative-side final bearing validation</b><br><br>

เลือก target จริงจุดเดียวกันในภาพซ้ายและขวา
ใช้ 8–15 จุดคุณภาพดีต่อคู่ และหลีกเลี่ยงวัตถุใกล้กล้อง<br>

คลิกภาพซ้ายก่อน แล้วคลิกตำแหน่งเดียวกันในภาพขวา<br>

ใช้จุดที่แน่นอน เช่น มุมเสา มุมป้าย จุดตัดเส้น
หรือ calibration target ที่อยู่นิ่ง<br><br>

อย่าเลือกจุดเพื่อให้ค่าดูดี
และไม่ต้องสนใจว่าจุดนั้นอยู่ใกล้ center หรือ edge
เพราะระบบต้องพิสูจน์ distortion correction ด้วย
</div>

<script>

const pairs = [
  ["1-6", 1, 1, 2, 6],
  ["6-7", 2, 6, 3, 7],
  ["7-8", 3, 7, 4, 8],
  ["8-9", 4, 8, 5, 9],
  ["5-9", 6, 5, 5, 9],
];

let state = null;
let index = 0;
let pending = null;


function fileName(step,preset) {
  return (
    `step_${String(step).padStart(2,"0")}_` +
    `p${preset}.jpg`
  );
}


async function load() {

  const response = await fetch(
    "/api/state"
  );

  state = await response.json();

  render();
}


function pair() {
  return pairs[index];
}


function key() {
  return pair()[0];
}


function marks() {

  if (!state.pairs[key()]) {
    state.pairs[key()] = [];
  }

  return state.pairs[key()];
}


function imageURL(step,preset) {
  return (
    `/image/${step}/${preset}`
  );
}


function render() {

  const [
    pairKey,
    stepA,
    presetA,
    stepB,
    presetB
  ] = pair();

  document.getElementById(
    "titleA"
  ).textContent =
    `P${presetA} | Step ${stepA}`;

  document.getElementById(
    "titleB"
  ).textContent =
    `P${presetB} | Step ${stepB}`;

  document.getElementById(
    "imgA"
  ).src =
    imageURL(stepA,presetA);

  document.getElementById(
    "imgB"
  ).src =
    imageURL(stepB,presetB);

  setTimeout(
    draw,
    100
  );

  status();
}


function status() {

  const count = marks().length;

  const cls =
    count >= 3
      ? "good"
      : "warn";

  document.getElementById(
    "status"
  ).innerHTML =
    `คู่ ${index+1}/${pairs.length} | ` +
    `<b>${key()}</b> | ` +
    `<span class="${cls}">` +
    `${count} targets</span> | ` +
    (
      pending
      ? "คลิก target เดียวกันในภาพขวา"
      : "คลิก target ในภาพซ้าย"
    );
}


function clearMarkers(wrap) {

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
  isPending=false
) {

  const img = wrap.querySelector(
    "img"
  );

  if (
    !img.naturalWidth
    ||
    !img.naturalHeight
  ) {
    return;
  }

  const marker =
    document.createElement(
      "div"
    );

  marker.className =
    "marker" +
    (
      isPending
      ? " pending"
      : ""
    );

  marker.style.left =
    (
      point[0]
      / img.naturalWidth
      * 100
    ) + "%";

  marker.style.top =
    (
      point[1]
      / img.naturalHeight
      * 100
    ) + "%";

  const label =
    document.createElement(
      "span"
    );

  label.textContent =
    String(number);

  marker.appendChild(
    label
  );

  wrap.appendChild(
    marker
  );
}


function draw() {

  const wrapA =
    document.getElementById(
      "wrapA"
    );

  const wrapB =
    document.getElementById(
      "wrapB"
    );

  clearMarkers(
    wrapA
  );

  clearMarkers(
    wrapB
  );

  marks().forEach(
    (mark,i) => {

      addMarker(
        wrapA,
        mark.a,
        i+1
      );

      addMarker(
        wrapB,
        mark.b,
        i+1
      );
    }
  );

  if (pending) {

    addMarker(
      wrapA,
      pending,
      marks().length+1,
      true
    );
  }
}


function pointFromEvent(
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
    Number(x.toFixed(2)),
    Number(y.toFixed(2))
  ];
}


document.getElementById(
  "imgA"
).addEventListener(
  "click",
  event => {

    pending =
      pointFromEvent(
        event,
        event.target
      );

    draw();
    status();
  }
);


document.getElementById(
  "imgB"
).addEventListener(
  "click",
  event => {

    if (!pending) {

      alert(
        "คลิกภาพซ้ายก่อน"
      );

      return;
    }

    const right =
      pointFromEvent(
        event,
        event.target
      );

    marks().push(
      {
        a: pending,
        b: right
      }
    );

    pending = null;

    draw();
    status();
  }
);


function undo() {

  if (pending) {
    pending = null;
  } else {
    marks().pop();
  }

  draw();
  status();
}


function clearPair() {

  if (
    !confirm(
      "ล้าง targets ของคู่นี้?"
    )
  ) {
    return;
  }

  state.pairs[
    key()
  ] = [];

  pending = null;

  draw();
  status();
}


async function save() {

  const response = await fetch(
    "/api/state",
    {
      method:"POST",
      headers:{
        "Content-Type":
          "application/json"
      },
      body:JSON.stringify(
        state
      )
    }
  );

  if (!response.ok) {
    alert("Save failed");
  }

  status();
}


async function next() {

  await save();

  pending = null;

  if (
    index
    < pairs.length-1
  ) {
    index++;
  }

  render();
}


async function previous() {

  await save();

  pending = null;

  if (index > 0) {
    index--;
  }

  render();
}


window.onload = load;

</script>

</body>
</html>
'''


class Handler(
    BaseHTTPRequestHandler
):

    def send_data(
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
            str(len(data)),
        )

        self.end_headers()

        self.wfile.write(
            data
        )


    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path == "/":

            self.send_data(
                200,
                "text/html; charset=utf-8",
                HTML.encode(
                    "utf-8"
                ),
            )

            return


        if path == "/api/state":

            payload = json.dumps(
                load_state(),
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )

            self.send_data(
                200,
                "application/json",
                payload,
            )

            return


        if path.startswith(
            "/image/"
        ):

            parts = path.strip(
                "/"
            ).split(
                "/"
            )

            if len(parts) != 3:
                self.send_error(400)
                return

            try:
                step = int(
                    parts[1]
                )

                preset = int(
                    parts[2]
                )

            except ValueError:
                self.send_error(400)
                return

            image_path = (
                CAPTURE_DIR
                / filename(
                    step,
                    preset,
                )
            )

            if not image_path.exists():
                self.send_error(404)
                return

            self.send_data(
                200,
                "image/jpeg",
                image_path.read_bytes(),
            )

            return


        self.send_error(404)


    def do_POST(self):

        if self.path != "/api/state":
            self.send_error(404)
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

        self.send_data(
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

    for (
        key,
        step_a,
        preset_a,
        step_b,
        preset_b,
    ) in PAIRS:

        for step, preset in (
            (step_a,preset_a),
            (step_b,preset_b),
        ):

            path = (
                CAPTURE_DIR
                / filename(
                    step,
                    preset,
                )
            )

            if not path.exists():
                raise RuntimeError(
                    f"Missing {path}"
                )

    save_state(
        load_state()
    )

    print(
        "=" * 72
    )

    print(
        "SAME-TARGET CROSS-PRESET "
        "NEGATIVE-SIDE FINAL MARK TOOL"
    )

    print(
        "=" * 72
    )

    print(
        f"Validation : "
        f"{VALIDATION_DIR}"
    )

    print(
        f"Marks      : "
        f"{MARK_FILE}"
    )

    print(
        "URL        : "
        "http://0.0.0.0:8766"
    )

    print(
        "Mark 3-5 SAME physical "
        "targets per pair."
    )

    print(
        "=" * 72
    )

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            8766,
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
