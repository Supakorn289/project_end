#!/usr/bin/env bash
set -euo pipefail

cd /opt/smart-fire-detection-v2

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/var/backups/smart-fire/geometry-diagnostics-${STAMP}"

sudo mkdir -p "$BACKUP_DIR"

sudo cp -a \
  solve_final_mixed_rotation_AB_v3.py \
  "$BACKUP_DIR/solve_final_mixed_rotation_AB_v3.py"

sudo cp -a \
  manager/services/geometry_solver_runner.py \
  "$BACKUP_DIR/geometry_solver_runner.py"

sudo cp -a \
  manager/templates/wizard.html \
  "$BACKUP_DIR/wizard.html"

python3 - <<'PY'
from pathlib import Path

ROOT = Path("/opt/smart-fire-detection-v2")

# ============================================================
# 1) Solver: ตรวจทุก Pair ก่อน แล้วส่ง structured diagnostic
# ============================================================

solver_path = ROOT / "solve_final_mixed_rotation_AB_v3.py"
text = solver_path.read_text(encoding="utf-8")

start = text.index("def evaluate_relative_rotation(\n")
end = text.index("\ndef compact_global(\n", start)

new_function = r'''def evaluate_relative_rotation(
    train,
    holdout,
):

    print()
    print("=" * 118)
    print(
        "PAIRWISE A -> B TRANSFER DIAGNOSTIC"
    )
    print("=" * 118)

    results = {}

    hard_failures = []
    review_pairs = []


    for index, (a, b) in enumerate(
        core.PAIR_LIST,
        start=1,
    ):

        key = f"{a}-{b}"

        train_count = len(
            train[
                key
            ]
        )

        holdout_count = len(
            holdout[
                key
            ]
        )


        try:

            fit = (
                core.robust_relative_rotation(
                    train[key],
                    seed=(
                        81000
                        + index
                    ),
                )
            )


        except Exception as exc:

            residuals = []
            suspect_mark_index = None


            # Best-effort residuals เพื่อช่วยบอกว่า
            # mark ไหนน่าสงสัยที่สุด
            try:

                rays_a = np.asarray(
                    [
                        obs["ray_a"]
                        for obs
                        in train[key]
                    ],
                    dtype=float,
                )

                rays_b = np.asarray(
                    [
                        obs["ray_b"]
                        for obs
                        in train[key]
                    ],
                    dtype=float,
                )


                if (
                    len(rays_a) >= 2
                    and
                    len(rays_a)
                    ==
                    len(rays_b)
                ):

                    direct_R = (
                        core.fit_rotation_b_to_a(
                            rays_a,
                            rays_b,
                        )
                    )

                    direct_errors = (
                        core.residual_angles_deg(
                            direct_R,
                            rays_a,
                            rays_b,
                        )
                    )

                    residuals = [
                        float(value)
                        for value
                        in direct_errors
                    ]


                    if residuals:

                        suspect_mark_index = (
                            int(
                                np.argmax(
                                    direct_errors
                                )
                            )
                            + 1
                        )


            except Exception:
                # Diagnostic ต้องไม่บดบัง root cause เดิม
                residuals = []
                suspect_mark_index = None


            failure = {
                "pair":
                    key,

                "phase":
                    "train",

                "stage":
                    "ransac",

                "reason":
                    str(
                        exc
                    ),

                "train_count":
                    int(
                        train_count
                    ),

                "holdout_count":
                    int(
                        holdout_count
                    ),

                "train_residuals_deg":
                    residuals,

                "suspect_mark_index":
                    suspect_mark_index,
            }


            hard_failures.append(
                failure
            )


            results[
                key
            ] = {
                "passed":
                    False,

                "hard_failure":
                    True,

                **failure,
            }


            print(
                f"{key:>5} "
                f"| train="
                f"{train_count:3d} "
                f"| holdout="
                f"{holdout_count:3d} "
                f"| FAIL "
                f"| {exc}"
            )


            continue


        R = fit[
            "R_b_to_a"
        ]


        rays_a = np.asarray(
            [
                obs["ray_a"]
                for obs
                in holdout[key]
            ],
            dtype=float,
        )

        rays_b = np.asarray(
            [
                obs["ray_b"]
                for obs
                in holdout[key]
            ],
            dtype=float,
        )


        errors = (
            core.residual_angles_deg(
                R,
                rays_a,
                rays_b,
            )
        )


        median = float(
            np.median(
                errors
            )
        )

        p90 = float(
            np.percentile(
                errors,
                90,
            )
        )

        maximum = float(
            np.max(
                errors
            )
        )


        passed = (
            median <= 2.0
            and
            p90 <= 3.5
        )


        item = {
            "pair":
                key,

            "train_count":
                int(
                    train_count
                ),

            "holdout_count":
                int(
                    holdout_count
                ),

            "median_deg":
                median,

            "p90_deg":
                p90,

            "max_deg":
                maximum,

            "passed":
                bool(
                    passed
                ),
        }


        results[
            key
        ] = item


        if not passed:

            review_pairs.append(
                item
            )


        print(
            f"{key:>5} "
            f"| train="
            f"{train_count:3d} "
            f"| holdout="
            f"{holdout_count:3d} "
            f"| median="
            f"{median:7.3f}° "
            f"| p90="
            f"{p90:7.3f}° "
            f"| max="
            f"{maximum:7.3f}° "
            f"| "
            f"{'PASS' if passed else 'REVIEW'}"
        )


    # --------------------------------------------------------
    # ถ้า Train RANSAC พังอย่างน้อยหนึ่ง Pair:
    # ส่ง JSON marker ให้ Manager แสดงสาเหตุในหน้าเว็บ
    # --------------------------------------------------------

    if hard_failures:

        diagnostic = {
            "stage":
                "pairwise_transfer_preflight",

            "hard_failures":
                hard_failures,

            "review_pairs":
                review_pairs,

            "ransac_threshold_deg":
                float(
                    core.RANSAC_THRESHOLD_DEG
                ),

            "minimum_pair_inliers":
                int(
                    core.MIN_PAIR_INLIERS
                ),
        }


        print(
            "GEOMETRY_DIAGNOSTIC_JSON="
            +
            json.dumps(
                diagnostic,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )


        raise RuntimeError(
            "Geometry pair preflight failed: "
            +
            ", ".join(
                item[
                    "pair"
                ]
                for item
                in hard_failures
            )
        )


    return results

'''

text = (
    text[:start]
    + new_function
    + text[end:]
)

solver_path.write_text(
    text,
    encoding="utf-8",
)


# ============================================================
# 2) Manager runner:
#    parse diagnostic + สร้างข้อความสำหรับ UI
# ============================================================

runner_path = (
    ROOT
    / "manager/services/geometry_solver_runner.py"
)

text = runner_path.read_text(
    encoding="utf-8"
)

marker = "GEOMETRY_DIAGNOSTIC_PREFIX = "

if marker not in text:

    insert_at = text.index(
        "def run_existing_geometry_solver(\n"
    )

    helpers = r'''
GEOMETRY_DIAGNOSTIC_PREFIX = (
    "GEOMETRY_DIAGNOSTIC_JSON="
)


def _extract_geometry_diagnostic(
    stdout,
):

    stdout = str(
        stdout
        or ""
    )


    for line in reversed(
        stdout.splitlines()
    ):

        line = line.strip()


        if not line.startswith(
            GEOMETRY_DIAGNOSTIC_PREFIX
        ):
            continue


        raw = line[
            len(
                GEOMETRY_DIAGNOSTIC_PREFIX
            ):
        ]


        try:

            value = json.loads(
                raw
            )


            if isinstance(
                value,
                dict,
            ):
                return value


        except Exception:
            return None


    return None


def _geometry_failure_user_message(
    diagnostic,
    stderr,
):

    lines = [
        "GEOMETRY SOLVER FAILED",
    ]


    if isinstance(
        diagnostic,
        dict,
    ):

        failures = (
            diagnostic.get(
                "hard_failures",
                [],
            )
            or []
        )

        reviews = (
            diagnostic.get(
                "review_pairs",
                [],
            )
            or []
        )


        if failures:

            lines.extend([
                "",
                (
                    "สาเหตุ: Training Landmark "
                    "บาง Pair ไม่สามารถสร้าง "
                    "rotation ที่สอดคล้องกันได้"
                ),
            ])


            for item in failures:

                pair = item.get(
                    "pair",
                    "?",
                )

                reason = item.get(
                    "reason",
                    "RANSAC failed",
                )

                lines.append(
                    f"❌ TRAIN Pair {pair}: "
                    f"{reason}"
                )


                residuals = (
                    item.get(
                        "train_residuals_deg",
                        [],
                    )
                    or []
                )


                if residuals:

                    values = ", ".join(
                        f"M{i + 1}="
                        f"{float(value):.3f}°"

                        for i, value
                        in enumerate(
                            residuals
                        )
                    )

                    lines.append(
                        "   Direct-fit residual: "
                        + values
                    )


                suspect = item.get(
                    "suspect_mark_index"
                )


                if suspect is not None:

                    lines.append(
                        "   จุดที่ควรตรวจอันดับแรก: "
                        f"Mark {suspect}"
                    )


            threshold = diagnostic.get(
                "ransac_threshold_deg"
            )

            minimum = diagnostic.get(
                "minimum_pair_inliers"
            )


            if (
                threshold is not None
                and
                minimum is not None
            ):

                lines.append(
                    ""
                    "เกณฑ์ RANSAC: "
                    f"ต้องมีอย่างน้อย {minimum} "
                    "inliers ภายใน "
                    f"{float(threshold):.2f}°"
                )


        if reviews:

            lines.extend([
                "",
                (
                    "คู่ที่ยังไม่ทำให้ Solver crash "
                    "แต่ควรตรวจเพิ่มเติม:"
                ),
            ])


            for item in reviews:

                lines.append(
                    "⚠ HOLDOUT Pair "
                    f"{item.get('pair', '?')}: "
                    "median="
                    f"{float(item.get('median_deg', 0.0)):.3f}° "
                    "p90="
                    f"{float(item.get('p90_deg', 0.0)):.3f}° "
                    "max="
                    f"{float(item.get('max_deg', 0.0)):.3f}°"
                )


        if failures:

            lines.extend([
                "",
                (
                    "วิธีแก้: ตรวจ/เพิ่ม Landmark "
                    "ของ Pair ที่ระบุ โดยเลือก "
                    "วัตถุไกล คงที่ และจุดชัด"
                ),
                (
                    "หลังแก้ Landmark ให้กด "
                    "\"เตรียมข้อมูลสำหรับ Solver\" "
                    "ใหม่ แล้วค่อยคำนวณอีกครั้ง"
                ),
            ])


            return "\n".join(
                lines
            )


    # Fallback เมื่อไม่มี structured diagnostic
    stderr = str(
        stderr
        or ""
    ).strip()


    if stderr:

        last_line = (
            stderr.splitlines()[-1]
        )

        lines.extend([
            "",
            "รายละเอียด:",
            last_line,
        ])


    return "\n".join(
        lines
    )


def _holdout_gate_diagnostic(
    result_file,
):

    result_file = Path(
        result_file
    )


    if not result_file.exists():
        return None


    try:

        payload = _read_json(
            result_file
        )


    except Exception:
        return None


    checks = (
        payload.get(
            "production_pair_checks",
            {},
        )
        or {}
    )

    evaluation = (
        payload.get(
            "holdout_evaluation",
            {},
        )
        or {}
    )

    pair_metrics = (
        evaluation.get(
            "pairs",
            {},
        )
        or {}
    )


    failed = []


    for pair, passed in checks.items():

        if bool(
            passed
        ):
            continue


        metrics = (
            pair_metrics.get(
                pair,
                {},
            )
            or {}
        )


        failed.append({
            "pair":
                pair,

            "median_deg":
                metrics.get(
                    "median_abs_azimuth_error_deg"
                ),

            "p90_deg":
                metrics.get(
                    "p90_abs_azimuth_error_deg"
                ),

            "max_deg":
                metrics.get(
                    "max_abs_azimuth_error_deg"
                ),

            "status":
                metrics.get(
                    "status"
                ),
        })


    return {
        "stage":
            "holdout_gate",

        "failed_pairs":
            failed,

        "global_metrics":
            (
                evaluation.get(
                    "global_metrics",
                    {},
                )
                or {}
            ),
    }


def _holdout_failure_user_message(
    diagnostic,
):

    lines = [
        "GEOMETRY HOLDOUT FAILED",
        "",
        (
            "Solver ทำงานจบ แต่ Independent "
            "Holdout ไม่ผ่าน Production Gate"
        ),
    ]


    if not isinstance(
        diagnostic,
        dict,
    ):

        return "\n".join(
            lines
        )


    failed = (
        diagnostic.get(
            "failed_pairs",
            [],
        )
        or []
    )


    if failed:

        lines.extend([
            "",
            "Pair ที่ไม่ผ่าน:",
        ])


        for item in failed:

            pair = item.get(
                "pair",
                "?",
            )

            median = item.get(
                "median_deg"
            )

            p90 = item.get(
                "p90_deg"
            )

            maximum = item.get(
                "max_deg"
            )


            parts = [
                f"❌ HOLDOUT Pair {pair}",
            ]


            if median is not None:
                parts.append(
                    "median="
                    f"{float(median):.3f}°"
                )

            if p90 is not None:
                parts.append(
                    "p90="
                    f"{float(p90):.3f}°"
                )

            if maximum is not None:
                parts.append(
                    "max="
                    f"{float(maximum):.3f}°"
                )


            lines.append(
                " | ".join(
                    parts
                )
            )


    metrics = (
        diagnostic.get(
            "global_metrics",
            {},
        )
        or {}
    )


    if metrics:

        median = metrics.get(
            "median_abs_azimuth_error_deg"
        )

        p90 = metrics.get(
            "p90_abs_azimuth_error_deg"
        )


        if (
            median is not None
            or
            p90 is not None
        ):

            lines.extend([
                "",
                "Global Holdout:",
            ])


            if median is not None:
                lines.append(
                    "median="
                    f"{float(median):.3f}°"
                )

            if p90 is not None:
                lines.append(
                    "p90="
                    f"{float(p90):.3f}°"
                )


    lines.extend([
        "",
        (
            "ให้ตรวจ Landmark ของ Pair ที่ระบุ "
            "แล้ว Prepare Solver ใหม่ก่อนคำนวณซ้ำ"
        ),
    ])


    return "\n".join(
        lines
    )


'''

    text = (
        text[:insert_at]
        + helpers
        + text[insert_at:]
    )


# -------- process.returncode != 0 --------

start = text.index(
    "    if process.returncode != 0:\n"
)

end = text.index(
    "\n\n    if not candidate_file.exists():",
    start,
)

replacement = r'''    if process.returncode != 0:

        diagnostic = (
            _extract_geometry_diagnostic(
                process.stdout
            )
        )


        return {
            "ok": False,

            "error":
                "geometry_solver_failed",

            "user_message":
                _geometry_failure_user_message(
                    diagnostic,
                    process.stderr,
                ),

            "diagnostic":
                diagnostic,

            "return_code":
                int(
                    process.returncode
                ),

            "stdout_tail":
                (
                    process.stdout
                    or ""
                )[-4000:],

            "stderr_tail":
                (
                    process.stderr
                    or ""
                )[-4000:],

            "runtime_changed":
                False,
        }
'''

text = (
    text[:start]
    + replacement
    + text[end:]
)


# -------- candidate missing / holdout failed --------

start = text.index(
    "    if not candidate_file.exists():\n"
)

end = text.index(
    "\n\n    candidate = (",
    start,
)

replacement = r'''    if not candidate_file.exists():

        diagnostic = (
            _holdout_gate_diagnostic(
                result_file
            )
        )


        return {
            "ok": False,

            "error":
                "holdout_failed_or_"
                "candidate_not_created",

            "user_message":
                _holdout_failure_user_message(
                    diagnostic
                ),

            "diagnostic":
                diagnostic,

            "result_file":
                (
                    str(
                        result_file
                    )
                    if result_file.exists()
                    else None
                ),

            "stdout_tail":
                (
                    process.stdout
                    or ""
                )[-4000:],

            "runtime_changed":
                False,
        }
'''

text = (
    text[:start]
    + replacement
    + text[end:]
)


runner_path.write_text(
    text,
    encoding="utf-8",
)


# ============================================================
# 3) Wizard API helper:
#    ถ้ามี user_message ให้แสดงข้อความละเอียดแทน error code
# ============================================================

wizard_path = (
    ROOT
    / "manager/templates/wizard.html"
)

text = wizard_path.read_text(
    encoding="utf-8"
)

api_start = text.index(
    "async function api("
)

api_end = text.index(
    "async function authState()",
    api_start,
)

segment = text[
    api_start:
    api_end
]

old = '''        throw new Error(
            data.error
            || JSON.stringify(data)
        );'''

new = '''        throw new Error(
            data.user_message
            || data.error
            || JSON.stringify(data)
        );'''

if old not in segment:

    if "data.user_message" not in segment:
        raise RuntimeError(
            "wizard api() error block not found"
        )

else:

    segment = segment.replace(
        old,
        new,
        1,
    )

    text = (
        text[:api_start]
        + segment
        + text[api_end:]
    )


wizard_path.write_text(
    text,
    encoding="utf-8",
)

print("GEOMETRY_SOLVER_DIAGNOSTICS=UPDATED")
PY

# ============================================================
# Validation
# ============================================================

./venv/bin/python -m py_compile \
  solve_final_mixed_rotation_AB_v3.py \
  manager/services/geometry_solver_runner.py

git diff --check

grep -nE \
  'GEOMETRY_DIAGNOSTIC_JSON|hard_failures|user_message|data.user_message' \
  solve_final_mixed_rotation_AB_v3.py \
  manager/services/geometry_solver_runner.py \
  manager/templates/wizard.html

sudo systemctl restart smart-fire-manager.service

echo
echo "manager:"
systemctl is-active smart-fire-manager.service

echo "detection:"
systemctl is-active smart-fire-detection.service || true

echo
echo "Backup: $BACKUP_DIR"
echo
echo "PATCH COMPLETE"
