from __future__ import annotations

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
)

from manager.security import (
    require_manager_token,
)

from manager.services.discovery import (
    get_discovery_snapshot,
)

from manager.services.setup_planner import (
    get_setup_plan,
)

from manager.services.site_store import (
    get_active_site,
    get_calibration_status,
    list_sites as list_runtime_sites,
)

from manager.services.system_info import (
    get_system_info,
)

from manager.services.site_registry import (
    adopt_current_site,
    create_site,
    list_registered_sites,
    preview_invalidation,
    set_site_mode,
)


from manager.security import configure_session_security
from manager.settings_api import settings_bp
from manager.commissioning_api import commissioning_bp
from manager.calibration_adapter_api import calibration_adapter_bp
from manager.wizard_api import wizard_bp


app = Flask(__name__)

configure_session_security(
    app
)

app.register_blueprint(
    settings_bp
)


app.register_blueprint(
    commissioning_bp
)


app.register_blueprint(
    calibration_adapter_bp
)


app.register_blueprint(
    wizard_bp
)


@app.get("/")
def index():

    return render_template(
        "landing.html"
    )


@app.get("/overview")
def control_center():

    return render_template(
        "index.html"
    )


@app.get("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service":
            "smart-fire-manager",

        "phase": 2,
        "milestone": "2C-A",

        "runtime_write":
            True,

        "metadata_write":
            True,
    })


@app.get("/api/overview")
def overview():

    discovery = (
        get_discovery_snapshot()
    )

    return jsonify({
        "ok": True,
        "discovery":
            discovery,

        "setup":
            get_setup_plan(),
    })


@app.get("/api/discovery")
def discovery():

    return jsonify(
        get_discovery_snapshot()
    )


@app.get("/api/setup/plan")
def setup_plan():

    mode = request.args.get(
        "mode"
    )

    return jsonify(
        get_setup_plan(
            requested_mode=mode
        )
    )


@app.get("/api/system")
def system():

    return jsonify(
        get_system_info()
    )


@app.get("/api/sites")
def sites():

    return jsonify({
        "runtime_sites":
            list_runtime_sites(),

        "manager_registry":
            list_registered_sites(),
    })


@app.get("/api/site/active")
def active_site():

    return jsonify(
        get_active_site()
    )


@app.get("/api/calibration/status")
def calibration_status():

    return jsonify(
        get_calibration_status()
    )


@app.get("/api/manager/sites")
def manager_sites():

    return jsonify(
        list_registered_sites()
    )


@app.post("/api/manager/site/adopt-current")
@require_manager_token
def manager_adopt_current():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:

        record = adopt_current_site(
            mode=payload.get(
                "mode",
                "LAB",
            ),

            display_name=payload.get(
                "display_name"
            ),
        )

        return jsonify({
            "ok": True,
            "site": record,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


@app.post("/api/manager/site/create")
@require_manager_token
def manager_create_site():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:

        record = create_site(
            site_id=payload.get(
                "site_id",
                "",
            ),

            mode=payload.get(
                "mode",
                "LAB",
            ),

            display_name=payload.get(
                "display_name"
            ),
        )

        return jsonify({
            "ok": True,
            "site": record,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


@app.post("/api/manager/site/<site_id>/mode")
@require_manager_token
def manager_set_mode(
    site_id: str,
):

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:

        record = set_site_mode(
            site_id,
            payload.get(
                "mode",
                "",
            ),
        )

        return jsonify({
            "ok": True,
            "site": record,
        })

    except KeyError as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 404

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


@app.get("/api/invalidation/preview/<change>")
def invalidation_preview(
    change: str,
):

    try:

        return jsonify(
            preview_invalidation(
                change
            )
        )

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400
