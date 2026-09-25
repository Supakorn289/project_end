#!/usr/bin/env python3

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


OLD_DIR = Path(
    "/home/fire/cross_preset_validation_20260913_185110"
)

NEW_DIR = Path(
    Path(
        "/home/fire/current_cross_validation_path.txt"
    ).read_text(
        encoding="utf-8"
    ).strip()
)

OUTPUT = (
    NEW_DIR
    / "cross_session_same_preset_marks.json"
)

PRESETS = [
    ("P1",  1,  1),
    ("P6",  6, 10),
    ("P7",  7, 11),
    ("P8",  8, 12),
    ("P9",  9, 13),
]


def filename(step, preset):
    return (
        f"step_{step:02d}_"
        f"p{preset}.jpg"
    )


def initial_state():
    return {
        "format":
            "smart-fire-cross-session-same-preset-marks-v1",

        "old_dir": str(OLD_DIR),
        "new_dir": str(NEW_DIR),

        "presets": {
            name: []
            for name, _, _
            in PRESETS
        },
    }


def load_state():

    if OUTPUT.exists():
        return json.loads(
            OUTPUT.read_text(
                encoding="utf-8"
            )
        )

    return initial_state()


def save_state(data):

    tmp = OUTPUT.with_suffix(
        ".tmp"
    )

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    tmp.replace(
        OUTPUT
    )


HTML = r'''<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Cross-session Same Preset</title>

<style>
*{box-sizing:border-box}

body{
 margin:0;
 background:#111;
 color:#eee;
 font-family:sans-serif
}

header{
 position:sticky;
 top:0;
 z-index:20;
 background:#1b1b1b;
 padding:12px 18px
}

h2{margin:0 0 5px}

.images{
 display:flex;
 gap:8px;
 padding:8px
}

.panel{width:50%}

.panel h3{
 text-align:center;
 margin:5px
}

.wrap{position:relative}

img{
 width:100%;
 display:block;
 border:2px solid #444;
 cursor:crosshair
}

.marker{
 position:absolute;
 width:18px;
 height:18px;
 border:3px solid #ff3b30;
 border-radius:50%;
 transform:translate(-50%,-50%);
 pointer-events:none
}

.marker.pending{
 border-color:#00e5ff
}

.marker span{
 position:absolute;
 left:12px;
 top:-13px;
 color:#ffe600;
 font-weight:bold;
 text-shadow:1px 1px 2px #000
}

.controls{
 display:flex;
 justify-content:center;
 gap:8px;
 flex-wrap:wrap;
 padding:10px
}

button{
 font-size:16px;
 padding:9px 15px
}

.help{
 padding:10px 18px 24px;
 color:#ccc;
 line-height:1.55
}
</style>
</head>

<body>

<header>
<h2>Cross-session Same-Preset Test</h2>
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

<button onclick="prevPreset()">
← ก่อนหน้า
</button>

<button onclick="undo()">
Undo
</button>

<button onclick="clearPreset()">
ล้าง P นี้
</button>

<button onclick="save()">
Save
</button>

<button onclick="nextPreset()">
ถัดไป →
</button>

</div>

<div class="help">

<b>OLD อยู่ซ้าย / NEW อยู่ขวา</b><br><br>

เลือก physical point เดียวกันจริง ๆ
ใน preset เดียวกันทั้งสอง session<br>

แนะนำอย่างน้อย 8–12 จุดต่อ preset ถ้าภาพเอื้อ<br><br>

เลือกจุดกระจายทั่วภาพ และถ้ามี ให้เลือกทั้งวัตถุใกล้และไกล
เพราะรอบนี้เราต้องการแยก
<b>rotation shift</b> ออกจาก <b>parallax</b><br><br>

อย่าพยายามคลิกให้ตำแหน่ง pixel เท่ากัน
คลิกตำแหน่งจริงของวัตถุนั้นเท่านั้น

</div>

<script>

const presets = [
 ["P1",1,1],
 ["P6",6,10],
 ["P7",7,11],
 ["P8",8,12],
 ["P9",9,13],
];

let state=null;
let idx=0;
let pending=null;


function current(){
 return presets[idx];
}


function name(){
 return current()[0];
}


function marks(){

 if(!state.presets[name()]){
   state.presets[name()] = [];
 }

 return state.presets[name()];
}


async function load(){

 state=
   await (
     await fetch("/api/state")
   ).json();

 render();
}


function render(){

 const [n,preset,step]=current();

 titleA.textContent =
   `OLD ${n} | Step ${step}`;

 titleB.textContent =
   `NEW ${n} | Step ${step}`;

 imgA.src =
   `/old/${step}/${preset}`;

 imgB.src =
   `/new/${step}/${preset}`;

 setTimeout(draw,100);

 status();
}


function status(){

 document.getElementById(
   "status"
 ).textContent =
   `${idx+1}/${presets.length} | `+
   `${name()} | `+
   `${marks().length} targets | `+
   (
     pending
     ? "คลิกจุดเดียวกันฝั่ง NEW"
     : "คลิกฝั่ง OLD"
   );
}


function clearMarkers(w){

 w.querySelectorAll(
   ".marker"
 ).forEach(
   e=>e.remove()
 );
}


function addMarker(
 w,
 point,
 number,
 isPending=false
){

 const img=w.querySelector("img");

 if(!img.naturalWidth)return;

 const marker=
   document.createElement("div");

 marker.className=
   "marker"+
   (isPending ? " pending" : "");

 marker.style.left=
   (
     point[0]
     /img.naturalWidth
     *100
   )+"%";

 marker.style.top=
   (
     point[1]
     /img.naturalHeight
     *100
   )+"%";

 const label=
   document.createElement("span");

 label.textContent=number;

 marker.appendChild(label);
 w.appendChild(marker);
}


function draw(){

 clearMarkers(wrapA);
 clearMarkers(wrapB);

 marks().forEach((m,i)=>{
   addMarker(wrapA,m.old,i+1);
   addMarker(wrapB,m.new,i+1);
 });

 if(pending){
   addMarker(
     wrapA,
     pending,
     marks().length+1,
     true
   );
 }
}


function point(e,img){

 const r=
   img.getBoundingClientRect();

 return [
   +(
     (e.clientX-r.left)
     *img.naturalWidth
     /r.width
   ).toFixed(2),

   +(
     (e.clientY-r.top)
     *img.naturalHeight
     /r.height
   ).toFixed(2)
 ];
}


imgA.onclick=e=>{

 pending=
   point(
     e,
     e.target
   );

 draw();
 status();
};


imgB.onclick=e=>{

 if(!pending){
   alert("คลิก OLD ก่อน");
   return;
 }

 marks().push({
   old:pending,
   new:point(
     e,
     e.target
   )
 });

 pending=null;

 draw();
 status();
};


function undo(){

 if(pending){
   pending=null;
 }else{
   marks().pop();
 }

 draw();
 status();
}


function clearPreset(){

 if(!confirm("ล้าง marks ของ preset นี้?")){
   return;
 }

 state.presets[name()]=[];
 pending=null;

 draw();
 status();
}


async function save(){

 await fetch(
   "/api/state",
   {
     method:"POST",
     headers:{
       "Content-Type":
         "application/json"
     },
     body:JSON.stringify(state)
   }
 );
}


async function nextPreset(){

 await save();

 pending=null;

 if(idx<presets.length-1){
   idx++;
 }

 render();
}


async function prevPreset(){

 await save();

 pending=null;

 if(idx>0){
   idx--;
 }

 render();
}


window.onload=load;

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

        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(len(data)),
        )

        self.end_headers()

        self.wfile.write(data)


    def do_GET(self):

        path=urlparse(
            self.path
        ).path

        if path=="/":

            self.send_data(
                200,
                "text/html; charset=utf-8",
                HTML.encode("utf-8"),
            )
            return


        if path=="/api/state":

            self.send_data(
                200,
                "application/json",
                json.dumps(
                    load_state(),
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            return


        parts=path.strip("/").split("/")

        if (
            len(parts)==3
            and
            parts[0] in ("old","new")
        ):

            side=parts[0]

            try:
                step=int(parts[1])
                preset=int(parts[2])
            except ValueError:
                self.send_error(400)
                return

            root=(
                OLD_DIR
                if side=="old"
                else NEW_DIR
            )

            file=(
                root
                /"captures"
                /filename(
                    step,
                    preset,
                )
            )

            if not file.exists():
                self.send_error(404)
                return

            self.send_data(
                200,
                "image/jpeg",
                file.read_bytes(),
            )
            return


        self.send_error(404)


    def do_POST(self):

        if self.path!="/api/state":
            self.send_error(404)
            return

        length=int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        try:

            data=json.loads(
                self.rfile.read(
                    length
                ).decode("utf-8")
            )

            save_state(data)

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
        *args,
    ):
        return


def main():

    for _,preset,step in PRESETS:

        for root in (
            OLD_DIR,
            NEW_DIR,
        ):

            path=(
                root
                /"captures"
                /filename(
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


    print("="*72)

    print(
        "CROSS-SESSION SAME-PRESET "
        "MARK TOOL v1"
    )

    print("="*72)

    print(
        f"OLD   : {OLD_DIR}"
    )

    print(
        f"NEW   : {NEW_DIR}"
    )

    print(
        f"Marks : {OUTPUT}"
    )

    print(
        "URL   : http://0.0.0.0:8768"
    )

    print("="*72)


    server=ThreadingHTTPServer(
        (
            "0.0.0.0",
            8768,
        ),
        Handler,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()


if __name__=="__main__":
    main()
