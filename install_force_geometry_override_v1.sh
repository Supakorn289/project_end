#!/usr/bin/env bash
set -euo pipefail

ROOT="${SMART_FIRE_ROOT:-/opt/smart-fire-detection-v2}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$ROOT/calibration/.manager/patch-backups/force-geometry-$STAMP"

FILES=(
  "solve_final_mixed_rotation_AB_v3.py"
  "manager/services/geometry_solver_runner.py"
  "manager/geometry_adapter_api.py"
  "preset_geometry.py"
  "manager/services/final_verification.py"
  "manager/templates/wizard.html"
  "activate_preset_rotation.py"
)

cd "$ROOT"

mkdir -p "$BACKUP_DIR"

for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $ROOT/$f" >&2
    exit 1
  fi
  mkdir -p "$BACKUP_DIR/$(dirname "$f")"
  cp -a "$f" "$BACKUP_DIR/$f"
done

export SMART_FIRE_ROOT="$ROOT"

"$ROOT/venv/bin/python" - <<'PY'
from pathlib import Path
import os
import re

def patch_force_geometry(root: Path):
    changed=[]
    root=Path(root)

    def read(rel): return (root/rel).read_text(encoding='utf-8')
    def write(rel,txt):
        (root/rel).write_text(txt,encoding='utf-8')
        changed.append(rel)
    def replace_once(text, old, new, label):
        if old not in text:
            raise RuntimeError(f"{label}: anchor not found")
        return text.replace(old,new,1)

    # 1 solver
    rel='solve_final_mixed_rotation_AB_v3.py'
    t=read(rel)
    if 'SMART_FIRE_MIXED_FAILED_CANDIDATE' not in t:
        anchor='''\n\nPOSITIVE_PAIRS = [\n'''
        insert='''

FAILED_HOLDOUT_CANDIDATE = Path(
    os.getenv(
        "SMART_FIRE_MIXED_FAILED_CANDIDATE",
        str(
            FINAL_CANDIDATE.with_name(
                "preset_rotation_failed_"
                "holdout_MIXED_AB_v3.json"
            )
        ),
    )
)
'''
        t=replace_once(t,anchor,insert+anchor,'solver failed candidate path')

    if '"HOLDOUT_FAILED_CANDIDATE_NOT_INSTALLED"' not in t:
        start_anchor='''    if not passed:

        print()
        print(
            "FINAL_MIXED_RESULT="
            "HOLDOUT_FAILED"
        )

        print(
            "Runtime geometry remains unchanged."
        )

        return
'''
        new='''    if not passed:

        # Keep a TRAIN-only candidate for an explicit
        # operator override. This artifact is NOT active and
        # is never treated as a PASS candidate.
        failed_payload = {
            "format":
                "smart-fire-preset-rotation-MIXED-AB-v3",

            "status":
                "HOLDOUT_FAILED_CANDIDATE_NOT_INSTALLED",

            "model":
                "calibrated-global-raw-ray-rotation",

            "reference_preset":
                1,

            "runtime_image_matching":
                False,

            "near_field_negative_marks_used":
                False,

            "physical_lens_offsets_m": {
                "horizontal_from_pan_axis":
                    0.033,

                "vertical_from_axis":
                    0.057,

                "used_in_solver":
                    False,
            },

            # IMPORTANT:
            # Use TRAIN-only Q here. Do not refit with failed
            # holdout data because that would destroy the
            # meaning of independent validation.
            "presets":
                bundle.serialize_Q(
                    Q_train
                ),

            "independent_holdout_gate": {
                "passed":
                    False,

                "pairs":
                    pair_checks,
            },

            "train_evaluation":
                train_eval,

            "holdout_evaluation":
                holdout_eval,

            "pair_transfer":
                pair_transfer,

            "optimizer":
                payload.get(
                    "optimizer",
                    {},
                ),

            "note":
                (
                    "TRAIN-only geometry retained after "
                    "independent holdout failure. "
                    "Not activatable unless an operator "
                    "explicitly creates a FORCED candidate."
                ),
        }


        FAILED_HOLDOUT_CANDIDATE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )


        FAILED_HOLDOUT_CANDIDATE.write_text(
            json.dumps(
                failed_payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


        print()
        print(
            "FINAL_MIXED_RESULT="
            "HOLDOUT_FAILED"
        )

        print(
            f"FAILED_CANDIDATE="
            f"{FAILED_HOLDOUT_CANDIDATE}"
        )

        print(
            "Runtime geometry remains unchanged."
        )

        return
'''
        t=replace_once(t,start_anchor,new,'solver holdout failure block')
    write(rel,t)

    # 2 runner
    rel='manager/services/geometry_solver_runner.py'
    t=read(rel)
    if 'from datetime import (' not in t and 'from datetime import datetime' not in t:
        anchor='''import subprocess

from pathlib import Path
'''
        repl='''import subprocess

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path
'''
        t=replace_once(t,anchor,repl,'runner datetime import')

    if 'FAILED_CANDIDATE_NAME' not in t:
        anchor='''def _sha256_file(
    path,
):
'''
        insert='''FAILED_CANDIDATE_NAME = (
    "preset_rotation_failed_"
    "holdout_MIXED_AB_v3.json"
)


def _failed_geometry_candidate_path(
    site_id,
):

    return candidate_path(
        site_id,
        "geometry_solver_workspace/"
        + FAILED_CANDIDATE_NAME,
    )


'''
        t=replace_once(t,anchor,insert+anchor,'runner failed name')

    # _summary fallback
    old='''    holdout = (
        candidate
        .get(
            "post_refit_holdout",
            {}
        )
        .get(
            "global_metrics",
            {}
        )
    )
'''
    if old in t:
        new='''    holdout_evaluation = (
        candidate.get(
            "post_refit_holdout"
        )
        or
        candidate.get(
            "holdout_evaluation"
        )
        or
        {}
    )


    holdout = (
        holdout_evaluation
        .get(
            "global_metrics",
            {}
        )
    )
'''
        t=t.replace(old,new,1)

    if 'def failed_geometry_force_status(' not in t:
        marker='''def run_existing_geometry_solver(
    site_id,
):
'''
        helpers=r'''def failed_geometry_force_status(
    site_id,
):

    state = load_state(
        site_id
    )


    mode = str(
        state.get(
            "mode",
            "LAB",
        )
        or "LAB"
    ).upper()


    failed_file = (
        _failed_geometry_candidate_path(
            site_id
        )
    )


    manifest_file = (
        candidate_path(
            site_id,
            "geometry_inputs/"
            "manifest.json",
        )
    )


    exists = (
        failed_file.exists()
    )


    stale = False


    if exists:

        if not manifest_file.exists():

            stale = True

        else:

            try:

                stale = (
                    failed_file.stat().st_mtime_ns
                    <
                    manifest_file.stat().st_mtime_ns
                )

            except OSError:

                stale = True


    candidate = None


    if (
        exists
        and
        not stale
    ):

        try:

            candidate = (
                _read_json(
                    failed_file
                )
            )

        except Exception:

            candidate = None


    gate = (
        (
            candidate
            or {}
        )
        .get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    presets = (
        (
            candidate
            or {}
        )
        .get(
            "presets"
        )
    )


    structurally_valid = bool(
        isinstance(
            candidate,
            dict,
        )

        and

        candidate.get(
            "status"
        )
        ==
        "HOLDOUT_FAILED_CANDIDATE_NOT_INSTALLED"

        and

        candidate.get(
            "model"
        )
        ==
        "calibrated-global-raw-ray-rotation"

        and

        gate.get(
            "passed"
        )
        is False

        and

        isinstance(
            presets,
            dict,
        )

        and

        all(
            str(preset)
            in presets

            for preset
            in range(
                1,
                10,
            )
        )
    )


    available = bool(
        exists
        and
        not stale
        and
        structurally_valid
    )


    pair_checks = (
        gate.get(
            "pairs",
            {},
        )
        or {}
    )


    failed_pairs = [
        pair
        for pair, passed
        in pair_checks.items()
        if passed is not True
    ]


    holdout_metrics = (
        (
            candidate
            or {}
        )
        .get(
            "holdout_evaluation",
            {},
        )
        .get(
            "global_metrics",
            {},
        )
        or {}
    )


    return {
        "ok":
            True,

        "site_id":
            site_id,

        "mode":
            mode,

        "available":
            available,

        # Force override is intentionally LAB-only.
        "allowed":
            bool(
                available
                and
                mode
                ==
                "LAB"
            ),

        "stale":
            bool(
                stale
            ),

        "failed_pairs":
            failed_pairs,

        "global_metrics":
            holdout_metrics,

        "reason":
            (
                None
                if (
                    available
                    and
                    mode
                    ==
                    "LAB"
                )
                else
                (
                    "force_override_lab_only"
                    if (
                        available
                        and
                        mode
                        !=
                        "LAB"
                    )
                    else
                    (
                        "failed_candidate_stale"
                        if stale
                        else
                        "no_current_failed_candidate"
                    )
                )
            ),

        "runtime_changed":
            False,
    }


def force_failed_geometry_candidate(
    site_id,
    *,
    confirmation,
    reason=None,
):

    status = (
        failed_geometry_force_status(
            site_id
        )
    )


    if (
        str(
            confirmation
            or ""
        )
        .strip()
        .upper()
        !=
        "FORCE"
    ):

        raise ValueError(
            "confirmation must be FORCE"
        )


    if not status.get(
        "allowed"
    ):

        raise RuntimeError(
            status.get(
                "reason"
            )
            or
            "force_override_not_allowed"
        )


    failed_file = (
        _failed_geometry_candidate_path(
            site_id
        )
    )


    candidate = (
        _read_json(
            failed_file
        )
    )


    gate = (
        candidate.get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    if (
        gate.get(
            "passed"
        )
        is not False
    ):

        raise RuntimeError(
            "failed candidate does not "
            "contain a failed holdout gate"
        )


    forced_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


    reason_text = str(
        reason
        or
        "manual_operator_override"
    ).strip()


    if not reason_text:

        reason_text = (
            "manual_operator_override"
        )


    reason_text = (
        reason_text[
            :300
        ]
    )


    forced = dict(
        candidate
    )


    forced[
        "status"
    ] = (
        "FORCED_CANDIDATE_NOT_INSTALLED"
    )


    forced[
        "operator_override"
    ] = {
        "enabled":
            True,

        "acknowledged_holdout_failure":
            True,

        "scope":
            "LAB",

        "forced_at_utc":
            forced_at,

        "reason":
            reason_text,

        "source_status":
            candidate.get(
                "status"
            ),

        "source_failed_candidate":
            str(
                failed_file
            ),
    }


    manager_candidate = (
        save_candidate(
            site_id,
            "preset_rotation.json",
            forced,
        )
    )


    intrinsics_file = (
        candidate_path(
            site_id,
            "camera_intrinsics.json",
        )
    )


    intrinsics_sha256 = (
        _sha256_file(
            intrinsics_file
        )
        if intrinsics_file.exists()
        else None
    )


    state = load_state(
        site_id
    )


    geometry = (
        state.setdefault(
            "geometry",
            {},
        )
    )


    geometry[
        "candidate"
    ] = forced


    geometry[
        "solver_result"
    ] = {
        "engine":
            "solve_final_mixed_"
            "rotation_AB_v3.py",

        "candidate_file":
            str(
                manager_candidate
            ),

        "workspace":
            str(
                failed_file.parent
            ),

        "passed":
            False,

        "forced_override":
            True,

        "holdout_passed":
            False,

        "source_failed_candidate":
            str(
                failed_file
            ),

        "intrinsics_file":
            str(
                intrinsics_file
            ),

        "intrinsics_sha256":
            intrinsics_sha256,
    }


    geometry[
        "override"
    ] = {
        "enabled":
            True,

        "forced_at_utc":
            forced_at,

        "reason":
            reason_text,

        "failed_pairs":
            status.get(
                "failed_pairs",
                [],
            ),

        "global_metrics":
            status.get(
                "global_metrics",
                {},
            ),
    }


    state[
        "step"
    ] = "TRUE_NORTH"


    save_state(
        site_id,
        state,
    )


    return {
        "ok":
            True,

        "site_id":
            site_id,

        "status":
            forced[
                "status"
            ],

        "forced_override":
            True,

        "holdout_passed":
            False,

        "failed_pairs":
            status.get(
                "failed_pairs",
                [],
            ),

        "global_metrics":
            status.get(
                "global_metrics",
                {},
            ),

        "candidate_file":
            str(
                manager_candidate
            ),

        "warning":
            (
                "Geometry นี้ไม่ผ่าน Independent "
                "Holdout และถูกเปิดใช้ด้วย "
                "LAB operator override"
            ),

        "runtime_changed":
            False,
    }


'''
        t=replace_once(t,marker,helpers+marker,'runner force helpers')

    # local failed file
    if 'failed_candidate_file = (' not in t:
        anchor='''    stdout_file = (
        workspace
        / "solver.stdout.txt"
    )
'''
        insert='''    failed_candidate_file = (
        workspace
        / FAILED_CANDIDATE_NAME
    )


'''
        # put before stdout file
        t=replace_once(t,anchor,insert+anchor,'runner failed candidate local path')

    # stale delete tuple add
    stale_anchor='''        result_file,
        candidate_file,
    ):
'''
    if stale_anchor in t and 'failed_candidate_file,' not in t[t.find('# Never accept a stale candidate.'):t.find('env = os.environ.copy()', t.find('# Never accept a stale candidate.'))]:
        t=t.replace(stale_anchor,'''        result_file,
        candidate_file,
        failed_candidate_file,
    ):
''',1)

    if '"SMART_FIRE_MIXED_FAILED_CANDIDATE"' not in t:
        anchor='''    env[
        "SMART_FIRE_MIXED_FINAL_CANDIDATE"
    ] = str(
        candidate_file
    )
'''
        repl=anchor+'''

    env[
        "SMART_FIRE_MIXED_FAILED_CANDIDATE"
    ] = str(
        failed_candidate_file
    )
'''
        t=replace_once(t,anchor,repl,'runner failed candidate env')
    write(rel,t)

    # 3 API
    rel='manager/geometry_adapter_api.py'
    t=read(rel)
    # add request import
    if re.search(r'from flask import \(\s*Blueprint,\s*jsonify,\s*\)',t,re.S):
        t=re.sub(r'from flask import \(\s*Blueprint,\s*jsonify,\s*\)',
                 'from flask import (\n    Blueprint,\n    jsonify,\n    request,\n)',t,count=1)
    elif '    request,' not in t.split('from manager.security')[0]:
        raise RuntimeError('geometry api flask import unexpected')

    if '/force-status' not in t:
        append=r'''

@geometry_adapter_bp.get(
    "/api/geometry-adapter/"
    "<site_id>/force-status"
)
@require_manager_session
def geometry_adapter_force_status(
    site_id,
):

    from manager.services.geometry_solver_runner import (
        failed_geometry_force_status,
    )


    try:

        return jsonify(
            failed_geometry_force_status(
                site_id
            )
        )


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

            "runtime_changed":
                False,
        }), 400


@geometry_adapter_bp.post(
    "/api/geometry-adapter/"
    "<site_id>/force"
)
@require_manager_session
def geometry_adapter_force(
    site_id,
):

    from manager.services.geometry_solver_runner import (
        force_failed_geometry_candidate,
    )


    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        result = (
            force_failed_geometry_candidate(
                site_id,

                confirmation=
                    data.get(
                        "confirmation"
                    ),

                reason=
                    data.get(
                        "reason"
                    ),
            )
        )


        return jsonify(
            result
        )


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

            "runtime_changed":
                False,
        }), 400
'''
        t=t.rstrip()+append+'\n'
    write(rel,t)

    # 4 runtime validator
    rel='preset_geometry.py'
    t=read(rel)
    if 'FORCED_CANDIDATE_NOT_INSTALLED' not in t:
        old='''        if not status.startswith(
            "PASS_"
        ):
            raise RuntimeError(
                "Preset rotation is not "
                f"a PASS artifact: {status}"
            )

        gate = payload.get(
            "independent_holdout_gate",
            {},
        )

        if (
            not isinstance(gate, dict)
            or
            gate.get("passed")
            is not True
        ):
            raise RuntimeError(
                "Independent holdout gate "
                "is not PASS"
            )
'''
        new='''        gate = payload.get(
            "independent_holdout_gate",
            {},
        )


        override = (
            payload.get(
                "operator_override",
                {},
            )
            or {}
        )


        pass_artifact = bool(
            status.startswith(
                "PASS_"
            )

            and

            isinstance(
                gate,
                dict,
            )

            and

            gate.get(
                "passed"
            )
            is True
        )


        forced_artifact = bool(
            status
            ==
            "FORCED_CANDIDATE_NOT_INSTALLED"

            and

            isinstance(
                gate,
                dict,
            )

            and

            gate.get(
                "passed"
            )
            is False

            and

            override.get(
                "enabled"
            )
            is True

            and

            override.get(
                "acknowledged_holdout_failure"
            )
            is True
        )


        if not (
            pass_artifact
            or
            forced_artifact
        ):

            raise RuntimeError(
                "Preset rotation is neither "
                "a validated PASS artifact nor "
                "an explicit FORCED override: "
                f"{status}"
            )
'''
        t=replace_once(t,old,new,'runtime forced validator')
    write(rel,t)

    # 5 final verification geometry block
    rel='manager/services/final_verification.py'
    t=read(rel)
    if 'forced_geometry = bool(' not in t:
        start=t.index('    geometry_source = None\n    geometry_data = None\n', t.index('# Cross-preset Geometry'))
        end=t.index('    # Geometry/Intrinsics dependency integrity.', start)
        new=r'''    geometry_source = None
    geometry_data = None


    override_meta = (
        (
            geometry_candidate
            or {}
        )
        .get(
            "operator_override",
            {},
        )
        or {}
    )


    geometry_gate = (
        (
            geometry_candidate
            or {}
        )
        .get(
            "independent_holdout_gate",
            {},
        )
        or {}
    )


    forced_geometry = bool(
        (
            geometry_candidate
            or {}
        ).get(
            "status"
        )
        ==
        "FORCED_CANDIDATE_NOT_INSTALLED"

        and

        override_meta.get(
            "enabled"
        )
        is True

        and

        override_meta.get(
            "acknowledged_holdout_failure"
        )
        is True

        and

        geometry_gate.get(
            "passed"
        )
        is False

        and

        solver_result.get(
            "forced_override"
        )
        is True
    )


    solver_geometry_accepted = bool(
        solver_result.get(
            "passed"
        )
        is True

        or

        forced_geometry
    )


    if (
        _valid_geometry(
            geometry_candidate
        )
        and
        solver_geometry_accepted
    ):

        geometry_source = (
            "candidate"
        )

        geometry_data = (
            geometry_candidate
        )


    elif (
        existing_active
        and
        _valid_geometry(
            _read_json(
                ACTIVE_GEOMETRY
            )
        )
    ):

        geometry_source = (
            "active-runtime"
        )

        geometry_data = (
            _read_json(
                ACTIVE_GEOMETRY
            )
        )


    geometry_is_forced = bool(
        geometry_source
        ==
        "candidate"
        and
        forced_geometry
    )


    add(
        "geometry",
        "Cross-Preset Geometry",

        required=True,

        ok=bool(
            geometry_data
        ),

        status=(
            "WARN"
            if geometry_is_forced
            else None
        ),

        detail=(
            (
                "Geometry พร้อมแบบ FORCED LAB OVERRIDE | "
                "Independent Holdout = FAILED"
            )
            if geometry_is_forced
            else
            (
                (
                    "Geometry พร้อม | "
                    f"{geometry_source}"
                )
                if geometry_data
                else
                "ยังไม่มี Geometry ที่ผ่าน Solver"
            )
        ),

        source=
            geometry_source,
    )


'''
        t=t[:start]+new+t[end:]
    write(rel,t)

    # 6 direct activation meta
    rel='activate_preset_rotation.py'
    t=read(rel)
    if '"forced_override":' not in t:
        anchor='''        "holdout_passed": (
            metadata.get(
                "independent_holdout_gate",
                {},
            ).get("passed")
            is True
        ),
'''
        repl=anchor+'''        "forced_override": (
            metadata.get(
                "operator_override",
                {},
            ).get(
                "enabled"
            )
            is True
        ),
'''
        t=replace_once(t,anchor,repl,'activate meta forced')
    write(rel,t)

    # 7 Wizard UI
    rel='manager/templates/wizard.html'
    t=read(rel)

    if 'id="btnForceGeometry"' not in t:
        anchor='''        <button
            id="btnSolveGeometry"
            class="green"
        >
            คำนวณ Geometry ด้วย Solver เดิม
        </button>
'''
        repl=anchor+'''
        <button
            id="btnForceGeometry"
            class="red hidden"
        >
            ⚠ ใช้ Geometry นี้แบบ Override (LAB)
        </button>
'''
        t=replace_once(t,anchor,repl,'wizard force button')

    if 'id="geometryForceStatus"' not in t:
        anchor='''    </div>
</section>


<section
    id="finalPanel"
'''
        repl='''    </div>

    <div
        id="geometryForceStatus"
        class="status warn hidden"
    >
        —
    </div>
</section>


<section
    id="finalPanel"
'''
        # only replace first occurrence after geometry panel
        pos=t.index('id="geometryPanel"')
        idx=t.find(anchor,pos)
        if idx<0: raise RuntimeError('wizard force status anchor not found')
        t=t[:idx]+repl+t[idx+len(anchor):]

    # api error payload
    api_start=t.index('async function api(')
    api_end=t.index('async function authState()',api_start)
    seg=t[api_start:api_end]
    if 'err.payload = data;' not in seg:
        # diagnostic patched variant or baseline
        pat=re.compile(r'''        throw new Error\(\s*(?:data\.user_message\s*\|\|\s*)?data\.error\s*\|\|\s*JSON\.stringify\(data\)\s*\);''',re.S)
        m=pat.search(seg)
        if not m:
            raise RuntimeError('wizard api throw pattern not found')
        repl='''        const err =
            new Error(
                data.user_message
                || data.error
                || JSON.stringify(data)
            );

        err.payload = data;

        throw err;'''
        seg=seg[:m.start()]+repl+seg[m.end():]
        t=t[:api_start]+seg+t[api_end:]

    # hide force after successful prepare
    if 'hideGeometryForceOverride();' not in t[t.index('"btnPrepareGeometry"'):t.index('"btnSolveGeometry"', t.index('"btnPrepareGeometry"'))]:
        anchor='''            "Runtime changed: false";


    }catch(error){
'''
        # within prepare block, first occurrence after btnPrepare
        pstart=t.index('"btnPrepareGeometry"')
        idx=t.find(anchor,pstart)
        if idx<0: raise RuntimeError('wizard prepare success anchor')
        repl='''            "Runtime changed: false";

        hideGeometryForceOverride();


    }catch(error){
'''
        t=t[:idx]+repl+t[idx+len(anchor):]

    if 'async function refreshGeometryForceStatus()' not in t:
        marker='''document
    .getElementById(
        "btnSolveGeometry"
    )
'''
        helper=r'''function hideGeometryForceOverride(){

    const button =
        document.getElementById(
            "btnForceGeometry"
        );

    const status =
        document.getElementById(
            "geometryForceStatus"
        );


    if(button){
        button.classList.add(
            "hidden"
        );
    }


    if(status){
        status.classList.add(
            "hidden"
        );
    }
}


async function refreshGeometryForceStatus(){

    if(!siteId){
        hideGeometryForceOverride();
        return null;
    }


    const button =
        document.getElementById(
            "btnForceGeometry"
        );

    const statusBox =
        document.getElementById(
            "geometryForceStatus"
        );


    try{

        const data =
            await api(
                `/api/geometry-adapter/${siteId}/force-status`
            );


        if(
            data.available
            &&
            data.allowed
        ){

            button
                .classList
                .remove(
                    "hidden"
                );


            statusBox
                .classList
                .remove(
                    "hidden"
                );


            const pairs =
                (
                    data.failed_pairs
                    || []
                )
                .join(", ");


            const g =
                data.global_metrics
                || {};


            statusBox.textContent =
                "⚠ FORCED OVERRIDE AVAILABLE\n"
                +
                "Independent Holdout = FAILED\n"
                +
                `Failed pairs: ${pairs || "unknown"}\n`
                +
                (
                    g.median_abs_azimuth_error_deg
                    != null
                    ?
                    `Global median: ${
                        Number(
                            g.median_abs_azimuth_error_deg
                        ).toFixed(3)
                    }°\n`
                    :
                    ""
                )
                +
                (
                    g.p90_abs_azimuth_error_deg
                    != null
                    ?
                    `Global P90: ${
                        Number(
                            g.p90_abs_azimuth_error_deg
                        ).toFixed(3)
                    }°\n`
                    :
                    ""
                )
                +
                "\nLAB เท่านั้น · Runtime ยังไม่ถูกเปลี่ยน";


            return data;
        }


        hideGeometryForceOverride();

        return data;


    }catch(error){

        hideGeometryForceOverride();

        return null;
    }
}


document
    .getElementById(
        "btnForceGeometry"
    )
    .onclick =
async()=>{

    if(!siteId){
        return;
    }


    const confirmation =
        prompt(
            "Geometry นี้ไม่ผ่าน Independent Holdout\n\n"
            +
            "การ Override อาจทำให้ Bearing/พิกัดคลาดเคลื่อน\n"
            +
            "โหมดนี้อนุญาตเฉพาะ LAB\n\n"
            +
            "พิมพ์ FORCE เพื่อยืนยัน"
        );


    if(
        String(
            confirmation
            || ""
        )
        .trim()
        .toUpperCase()
        !==
        "FORCE"
    ){
        return;
    }


    const reason =
        prompt(
            "เหตุผลในการ Override (ไม่บังคับ)",
            "temporary_lab_override"
        );


    const box =
        document.getElementById(
            "geometryStatus"
        );


    box.textContent =
        "กำลังสร้าง FORCED Geometry Candidate...";


    try{

        const data =
            await api(
                `/api/geometry-adapter/${siteId}/force`,
                {
                    method:"POST",

                    body:
                        JSON.stringify({
                            confirmation:
                                "FORCE",

                            reason:
                                (
                                    reason
                                    ||
                                    "temporary_lab_override"
                                )
                        }),
                }
            );


        box.textContent =
            "⚠ FORCED GEOMETRY CANDIDATE CREATED\n"
            +
            `Status: ${data.status}\n`
            +
            "Holdout passed: false\n"
            +
            `Failed pairs: ${
                (
                    data.failed_pairs
                    || []
                ).join(", ")
            }\n\n`
            +
            "ยังไม่เปลี่ยน Active Runtime\n"
            +
            "ไปทำ True North / Final Verification / Revision / Activate ต่อ";


        const statusBox =
            document.getElementById(
                "geometryForceStatus"
            );


        statusBox.textContent =
            "⚠ Geometry Candidate นี้ถูกสร้างด้วย LAB operator override\n"
            +
            "Independent Holdout = FAILED";

        statusBox
            .classList
            .remove(
                "hidden"
            );


        document
            .getElementById(
                "btnForceGeometry"
            )
            .classList
            .add(
                "hidden"
            );


        const state =
            await api(
                `/api/wizard/state/${siteId}`
            );


        wizardState =
            state.state;


    }catch(error){

        box.textContent =
            String(
                error
            );
    }
};


'''
        t=replace_once(t,marker,helper+marker,'wizard force helpers')

    # solve success hide / error refresh
    # Only within solve block
    solve_marker='''document
    .getElementById(
        "btnSolveGeometry"
    )'''
    north_marker='''document
    .getElementById(
        "btnBuildNorth"
    )'''
    s=t.index(solve_marker)
    e=t.index(north_marker,s)
    seg=t[s:e]
    if 'hideGeometryForceOverride();' not in seg:
        anchor='''        box.textContent =
            JSON.stringify(
                data,
                null,
                2
            );
'''
        if anchor not in seg:
            raise RuntimeError('wizard solve success anchor missing')
        seg=seg.replace(
            anchor,
            anchor + "\n        hideGeometryForceOverride();\n",
            1,
        )
    if 'refreshGeometryForceStatus' not in seg.split('}catch(error){',1)[1]:
        anchor='''        box.textContent =
            String(
                error
            );
    }
};
'''
        repl='''        box.textContent =
            String(
                error
            );

        await refreshGeometryForceStatus();
    }
};
'''
        if anchor not in seg:
            raise RuntimeError('wizard solve catch anchor missing')
        seg=seg.replace(anchor,repl,1)
    t=t[:s]+seg+t[e:]

    write(rel,t)
    return changed


root = Path(
    os.environ["SMART_FIRE_ROOT"]
)

changed = patch_force_geometry(
    root
)

print("FORCE_GEOMETRY_OVERRIDE=PATCHED")
for item in changed:
    print("  ", item)
PY

"$ROOT/venv/bin/python" -m py_compile   solve_final_mixed_rotation_AB_v3.py   manager/services/geometry_solver_runner.py   manager/geometry_adapter_api.py   preset_geometry.py   manager/services/final_verification.py   activate_preset_rotation.py

# Validate browser-side JS if Node.js is available.
if command -v node >/dev/null 2>&1; then
  "$ROOT/venv/bin/python" - <<'PY'
from pathlib import Path
import re

text = Path(
    "manager/templates/wizard.html"
).read_text(
    encoding="utf-8"
)

match = re.search(
    r"<script>(.*?)</script>",
    text,
    re.S,
)

if not match:
    raise SystemExit(
        "wizard script block not found"
    )

Path(
    "/tmp/smart-fire-wizard-force-check.js"
).write_text(
    match.group(1),
    encoding="utf-8",
)
PY

  node --check     /tmp/smart-fire-wizard-force-check.js

  rm -f     /tmp/smart-fire-wizard-force-check.js
fi

# Check only files touched by this patch.
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check --     solve_final_mixed_rotation_AB_v3.py     manager/services/geometry_solver_runner.py     manager/geometry_adapter_api.py     preset_geometry.py     manager/services/final_verification.py     manager/templates/wizard.html     activate_preset_rotation.py
fi

echo
echo "Restarting Manager..."
sudo systemctl restart smart-fire-manager.service

echo
echo "Service status:"
printf "manager   : "
systemctl is-active smart-fire-manager.service || true
printf "detection : "
systemctl is-active smart-fire-detection.service || true

echo
echo "Backup:"
echo "$BACKUP_DIR"

echo
echo "PATCH COMPLETE"
echo "After a HOLDOUT_FAILED solve, reload the Wizard."
echo "A red LAB Override button should appear."
