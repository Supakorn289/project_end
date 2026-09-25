from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)

from manager.security import (
    require_manager_session,
)

from manager.services.commissioning_workflow import (
    get_workflow,
)

from manager.services.ops_agent import (
    run_existing_tool,
)

from manager.services.tool_registry import (
    get_catalog,
    get_tool,
)


commissioning_bp = Blueprint(
    "manager_commissioning",
    __name__,
)


@commissioning_bp.get(
    "/commissioning"
)
def commissioning_page():

    return render_template(
        "commissioning.html"
    )


@commissioning_bp.get(
    "/api/commissioning/catalog"
)
def commissioning_catalog():

    return jsonify(
        get_catalog()
    )


@commissioning_bp.get(
    "/api/commissioning/workflow"
)
def commissioning_workflow():

    return jsonify(
        get_workflow(
            installation=request.args.get(
                "installation",
                "EXISTING",
            ),

            mode=request.args.get(
                "mode",
                "LAB",
            ),
        )
    )


@commissioning_bp.get(
    "/api/commissioning/tool/<tool_id>/plan"
)
def commissioning_tool_plan(
    tool_id,
):

    try:

        tool = get_tool(
            tool_id
        )

    except KeyError:

        return jsonify({
            "ok": False,
            "error":
                "unknown_tool",
        }), 404


    runnable = bool(
        tool.get(
            "exists"
        )
        and
        tool.get(
            "kind"
        )
        == "cli"
    )


    warnings = []


    if tool.get(
        "hardware_motion"
    ):

        warnings.append(
            "เครื่องมือนี้จะขยับ PTZ"
        )


    if tool.get(
        "heavy"
    ):

        warnings.append(
            "เครื่องมือนี้ใช้ CPU/RAM สูง"
        )


    if tool.get(
        "requires_detection_stopped"
    ):

        warnings.append(
            "Detection จะหยุดชั่วคราว "
            "และคืนสถานะเดิมเมื่อจบ"
        )


    if (
        tool_id
        == "telegram.test"
    ):

        warnings.append(
            "จะส่ง Telegram test จริง"
        )


    return jsonify({
        "ok": True,

        "tool_id":
            tool_id,

        "label":
            tool.get(
                "label"
            ),

        "description":
            tool.get(
                "description"
            ),

        "kind":
            tool.get(
                "kind"
            ),

        "exists":
            tool.get(
                "exists"
            ),

        "runnable":
            runnable,

        "requires_detection_stopped":
            bool(
                tool.get(
                    "requires_detection_stopped"
                )
            ),

        "hardware_motion":
            bool(
                tool.get(
                    "hardware_motion"
                )
            ),

        "heavy":
            bool(
                tool.get(
                    "heavy"
                )
            ),

        "warnings":
            warnings,

        "route":
            tool.get(
                "route"
            ),
    })


@commissioning_bp.post(
    "/api/commissioning/tool/<tool_id>/run"
)
@require_manager_session
def commissioning_tool_run(
    tool_id,
):

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )


    if (
        data.get(
            "confirm"
        )
        is not True
    ):

        return jsonify({
            "ok": False,
            "error":
                "explicit_confirmation_required",
        }), 400


    try:

        tool = get_tool(
            tool_id
        )

    except KeyError:

        return jsonify({
            "ok": False,
            "error":
                "unknown_tool",
        }), 404


    if (
        tool.get(
            "kind"
        )
        != "cli"
    ):

        return jsonify({
            "ok": False,
            "error":
                "tool_uses_ui_adapter",
            "route":
                tool.get(
                    "route"
                ),
        }), 400


    if not tool.get(
        "exists"
    ):

        return jsonify({
            "ok": False,
            "error":
                "tool_missing",
        }), 404


    result = (
        run_existing_tool(
            tool_id
        )
    )


    return jsonify(
        result
    ), (
        200
        if result.get(
            "ok"
        )
        else 500
    )
