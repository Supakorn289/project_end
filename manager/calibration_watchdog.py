from __future__ import annotations

import sys
import time
import traceback


from manager.services.calibration_lease import (
    lease_expired,
    read_lease,
    release_lease,
)

from manager.services.runtime_settings import (
    start_detection,
)

from manager.services.wizard_store import (
    load_state,
    save_state,
)


CHECK_INTERVAL_SEC = 10


def log(
    message,
):

    print(
        message,
        flush=True,
    )


def recover_once():

    lease = read_lease()


    if not lease:

        return {
            "ok":
                True,

            "status":
                "IDLE",
        }


    if not lease_expired(
        lease
    ):

        return {
            "ok":
                True,

            "status":
                "LEASE_ACTIVE",

            "site_id":
                lease.get(
                    "site_id"
                ),

            "expires_at":
                lease.get(
                    "expires_at"
                ),
        }


    site_id = str(
        lease.get(
            "site_id"
        )
        or ""
    )


    log(
        "[watchdog] expired "
        f"calibration lease: {site_id}"
    )


    started = (
        start_detection()
    )


    if not started.get(
        "ok"
    ):

        log(
            "[watchdog] "
            "failed to resume Detection: "
            f"{started}"
        )


        return {
            "ok":
                False,

            "status":
                "RECOVERY_FAILED",

            "site_id":
                site_id,

            "detail":
                started,
        }


    try:

        state = load_state(
            site_id
        )


        state[
            "calibration_mode"
        ] = False


        state[
            "calibration_recovery"
        ] = {
            "reason":
                "LEASE_EXPIRED",

            "recovered_at_unix":
                time.time(),

            "detection_resume":
                started,
        }


        save_state(
            site_id,
            state,
        )


    except Exception:

        log(
            "[watchdog] warning: "
            "could not update wizard state\n"
            +
            traceback.format_exc()
        )


    release_lease(
        site_id,
        force=True,
    )


    log(
        "[watchdog] "
        "Detection resumed successfully"
    )


    return {
        "ok":
            True,

        "status":
            "RECOVERED",

        "site_id":
            site_id,
    }


def serve():

    log(
        "[watchdog] started"
    )


    while True:

        try:

            recover_once()

        except Exception:

            log(
                "[watchdog] exception\n"
                +
                traceback.format_exc()
            )


        time.sleep(
            CHECK_INTERVAL_SEC
        )


def main():

    if (
        len(
            sys.argv
        )
        > 1
        and
        sys.argv[
            1
        ]
        ==
        "--once"
    ):

        print(
            recover_once()
        )

        return


    serve()


if __name__ == "__main__":

    main()
