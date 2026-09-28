from __future__ import annotations

import subprocess


from manager.app import (
    app,
)

from manager.services.calibration_worker_client import (
    worker_health,
)

from manager.services.runtime_settings import (
    detection_status,
)

from manager.services.revision_engine import (
    list_revisions,
)

from manager.services.activation_plan import (
    build_activation_plan,
)


SITE = (
    "current-site-20260921"
)


required_routes = {
    "/api/final-verification/<site_id>",

    "/api/revisions/<site_id>",

    (
        "/api/activation/"
        "<site_id>/<revision_id>/plan"
    ),

    (
        "/api/activation/"
        "<site_id>/<revision_id>/activate"
    ),

    (
        "/api/wizard/<site_id>/"
        "calibration/heartbeat"
    ),

    (
        "/api/wizard/<site_id>/"
        "capture-image/"
        "<capture_set>/<filename>"
    ),
}


routes = {
    rule.rule
    for rule
    in app.url_map.iter_rules()
}


missing = (
    required_routes
    -
    routes
)


assert not missing, (
    "Missing routes: "
    +
    str(
        sorted(
            missing
        )
    )
)


print(
    "ROUTES=PASS"
)


services = [
    "smart-fire-manager.service",
    "smart-fire-manager-agent.service",
    "smart-fire-detection.service",
    "smart-fire-calibration-worker.service",
    "smart-fire-calibration-watchdog.service",
]


for service in services:

    result = subprocess.run(
        [
            "/usr/bin/systemctl",
            "is-active",
            "--quiet",
            service,
        ],
        check=False,
    )


    assert result.returncode == 0, (
        service
        +
        " not active"
    )


print(
    "SERVICES=PASS"
)


worker = worker_health()

assert worker.get(
    "ok"
), worker


print(
    "WORKER=PASS"
)


detection = detection_status()

assert detection.get(
    "ok"
), detection


assert detection.get(
    "active"
) is True


print(
    "DETECTION=PASS"
)


revisions = list_revisions(
    SITE
)


assert revisions, (
    "No revisions found"
)


print(
    "REVISION_ENGINE=PASS"
)


draft = next(
    (
        revision
        for revision
        in revisions
        if revision.get(
            "status"
        )
        ==
        "DRAFT_BLOCKED"
    ),
    None,
)


assert draft is not None


plan = build_activation_plan(
    SITE,
    draft[
        "revision_id"
    ],
)


assert plan.get(
    "activatable"
) is False


assert (
    plan.get(
        "runtime_changed"
    )
    is False
)


print(
    "DRAFT_ACTIVATION_GATE=PASS"
)


print(
    "SMART_FIRE_MANAGER_SELFTEST=PASS"
)
