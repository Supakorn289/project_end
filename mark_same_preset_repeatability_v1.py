#!/usr/bin/env python3

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(
    Path("/home/fire/current_cross_validation_path.txt")
    .read_text(encoding="utf-8")
    .strip()
)

CAPTURES = ROOT / "captures"
MARK_FILE = ROOT / "same_preset_repeatability_marks.json"

# key, stepA, preset, stepB
PAIRS = [
    ("P1_01-09", 1, 1, 9),
    ("P1_09-17", 9, 1, 17),
    ("P1_01-17", 1, 1, 17),

    ("P2_02-08", 2, 2, 8),
    ("P3_03-07", 3, 3, 7),
    ("P4_04-06", 4, 4, 6),

    ("P6_10-16", 10, 6, 16),
    ("P7_11-15", 11, 7, 15),
    ("P8_12-14", 12, 8, 14),
]


def fname(step, preset):
    return f"step_{step:02d}_p{preset}.jpg"


def empty():
    return {
        "format": "smart-fire-same-preset-repeatability-marks-v1",
        "root": str(ROOT),
        "pairs": {
            key: []
            for key, *_ in PAIRS
        },
    }


def load():
    if MARK_FILE.exists():
        return json.loads(
            MARK_FILE.read_text(encoding="utf-8")
        )
    return empty()


def save(data):
    tmp = MARK_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(MARK_FILE)


HTML = r'''<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Same Preset Repeatability</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#111;color:#eee;font-family:sans-serif}
header{position:sticky;top:0;background:#1b1b1b;padding:12px 18px;z-index:10}
h2{margin:0 0 5px}
.images{display:flex;gap:8px;padding:8px}
.panel{width:50%}
.panel h3{text-align:center;margin:5px}
.wrap{position:relative}
img{width:100%;display:block;border:2px solid #444;cursor:crosshair}
.marker{
 position:absolute;width:18px;height:18px;border:3px solid #ff3b30;
 border-radius:50%;transform:translate(-50%,-50%);pointer-events:none
}
.marker.pending{border-color:#00e5ff}
.marker span{
 position:absolute;left:12px;top:-13px;color:#ffe600;
 font-weight:bold;text-shadow:1px 1px 2px #000
}
.controls{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;padding:10px}
button{font-size:16px;padding:9px 15px}
.help{padding:10px 18px 24px;color:#ccc;line-height:1.55}
</style>
</head>
<body>

<header>
<h2>Same-Preset PTZ Repeatability Test</h2>
<div id="status"></div>
</header>

<div class="images">
 <div class="panel">
   <h3 id="titleA"></h3>
   <div class="wrap" id="wrapA"><img id="imgA"></div>
 </div>
 <div class="panel">
   <h3 id="titleB"></h3>
   <div class="wrap" id="wrapB"><img id="imgB"></div>
 </div>
</div>

<div class="controls">
<button onclick="prev()">← ก่อนหน้า</button>
<button onclick="undo()">Undo</button>
<button onclick="clearPair()">ล้างคู่นี้</button>
<button onclick="saveState()">Save</button>
<button onclick="next()">ถัดไป →</button>
</div>

<div class="help">
เลือก <b>จุดจริงเดียวกัน</b> ในภาพ preset เดียวกันทั้งสอง arrival
ประมาณ 3–5 จุดต่อคู่<br>
คลิกซ้ายก่อน แล้วคลิกจุดเดียวกันในภาพขวา<br>
ไม่ต้องพยายามทำให้ตำแหน่งใกล้กัน ระบบกำลังวัดว่ากล้องกลับมามุมเดิมจริงหรือไม่
</div>

<script>
const pairs = [
 ["P1_01-09",1,1,9],
 ["P1_09-17",9,1,17],
 ["P1_01-17",1,1,17],
 ["P2_02-08",2,2,8],
 ["P3_03-07",3,3,7],
 ["P4_04-06",4,4,6],
 ["P6_10-16",10,6,16],
 ["P7_11-15",11,7,15],
 ["P8_12-14",12,8,14],
];

let state=null;
let idx=0;
let pending=null;

function cur(){return pairs[idx]}
function key(){return cur()[0]}
function marks(){
 if(!state.pairs[key()]) state.pairs[key()]=[];
 return state.pairs[key()];
}
function url(step,preset){return `/image/${step}/${preset}`}

async function loadState(){
 state=await (await fetch("/api/state")).json();
 render();
}

function render(){
 const [k,a,p,b]=cur();
 titleA.textContent=`P${p} | Step ${a}`;
 titleB.textContent=`P${p} | Step ${b}`;
 imgA.src=url(a,p);
 imgB.src=url(b,p);
 setTimeout(draw,100);
 status();
}

function status(){
 document.getElementById("status").textContent =
  `${idx+1}/${pairs.length} | ${key()} | ${marks().length} targets | `+
  (pending ? "คลิกจุดเดียวกันทางขวา" : "คลิกภาพซ้าย");
}

function clearMarkers(w){
 w.querySelectorAll(".marker").forEach(e=>e.remove());
}

function addMarker(w,pt,n,p=false){
 const img=w.querySelector("img");
 if(!img.naturalWidth)return;
 const m=document.createElement("div");
 m.className="marker"+(p?" pending":"");
 m.style.left=(pt[0]/img.naturalWidth*100)+"%";
 m.style.top=(pt[1]/img.naturalHeight*100)+"%";
 const s=document.createElement("span");
 s.textContent=n;
 m.appendChild(s);
 w.appendChild(m);
}

function draw(){
 clearMarkers(wrapA); clearMarkers(wrapB);
 marks().forEach((m,i)=>{
   addMarker(wrapA,m.a,i+1);
   addMarker(wrapB,m.b,i+1);
 });
 if(pending)addMarker(wrapA,pending,marks().length+1,true);
}

function point(e,img){
 const r=img.getBoundingClientRect();
 return [
  +( (e.clientX-r.left)*img.naturalWidth/r.width ).toFixed(2),
  +( (e.clientY-r.top)*img.naturalHeight/r.height ).toFixed(2)
 ];
}

imgA.onclick=e=>{
 pending=point(e,e.target); draw(); status();
};

imgB.onclick=e=>{
 if(!pending){alert("คลิกภาพซ้ายก่อน");return;}
 marks().push({a:pending,b:point(e,e.target)});
 pending=null; draw(); status();
};

function undo(){
 if(pending)pending=null;
 else marks().pop();
 draw();status();
}

function clearPair(){
 if(!confirm("ล้างคู่นี้?"))return;
 state.pairs[key()]=[];
 pending=null;draw();status();
}

async function saveState(){
 await fetch("/api/state",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify(state)
 });
}

async function next(){
 await saveState();
 pending=null;
 if(idx<pairs.length-1)idx++;
 render();
}

async function prev(){
 await saveState();
 pending=null;
 if(idx>0)idx--;
 render();
}

window.onload=loadState;
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):

    def reply(self, status, content_type, data):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path=urlparse(self.path).path

        if path=="/":
            self.reply(
                200,
                "text/html; charset=utf-8",
                HTML.encode("utf-8"),
            )
            return

        if path=="/api/state":
            self.reply(
                200,
                "application/json",
                json.dumps(load(),ensure_ascii=False).encode("utf-8"),
            )
            return

        if path.startswith("/image/"):
            parts=path.strip("/").split("/")
            if len(parts)!=3:
                self.send_error(400); return
            try:
                step=int(parts[1])
                preset=int(parts[2])
            except ValueError:
                self.send_error(400); return

            f=CAPTURES/fname(step,preset)
            if not f.exists():
                self.send_error(404); return

            self.reply(200,"image/jpeg",f.read_bytes())
            return

        self.send_error(404)

    def do_POST(self):
        if self.path!="/api/state":
            self.send_error(404); return

        n=int(self.headers.get("Content-Length","0"))
        try:
            data=json.loads(self.rfile.read(n).decode("utf-8"))
            save(data)
        except Exception as exc:
            self.send_error(400,str(exc)); return

        self.reply(200,"application/json",b'{"ok":true}')

    def log_message(self,*args):
        return


def main():

    for key,a,p,b in PAIRS:
        for step in (a,b):
            f=CAPTURES/fname(step,p)
            if not f.exists():
                raise RuntimeError(f"Missing {f}")

    save(load())

    print("="*72)
    print("SAME-PRESET PTZ REPEATABILITY MARK TOOL")
    print("="*72)
    print(f"Root  : {ROOT}")
    print(f"Marks : {MARK_FILE}")
    print("URL   : http://0.0.0.0:8767")
    print("Mark 3-5 identical targets per pair.")
    print("="*72)

    server=ThreadingHTTPServer(("0.0.0.0",8767),Handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=="__main__":
    main()
