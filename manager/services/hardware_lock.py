from __future__ import annotations

import fcntl
import os
import time

from contextlib import (
    contextmanager,
)

from pathlib import Path


LOCK_FILE = Path(
    "/opt/smart-fire-detection-v2/"
    "calibration/.manager/"
    "hardware.lock"
)


class HardwareBusyError(
    RuntimeError
):
    pass


@contextmanager
def hardware_lock(
    owner,
    *,
    timeout=2.0,
):

    owner = str(
        owner
        or "unknown"
    )


    LOCK_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    handle = LOCK_FILE.open(
        "a+",
        encoding="utf-8",
    )


    deadline = (
        time.monotonic()
        +
        float(
            timeout
        )
    )


    acquired = False


    try:

        while True:

            try:

                fcntl.flock(
                    handle.fileno(),
                    (
                        fcntl.LOCK_EX
                        |
                        fcntl.LOCK_NB
                    ),
                )

                acquired = True
                break


            except BlockingIOError:

                if (
                    time.monotonic()
                    >= deadline
                ):

                    raise HardwareBusyError(
                        "Camera/PTZ กำลังถูกใช้งาน "
                        "โดยงานอื่น"
                    )


                time.sleep(
                    0.05
                )


        handle.seek(
            0
        )

        handle.truncate(
            0
        )

        handle.write(
            (
                f"pid={os.getpid()}\n"
                f"owner={owner}\n"
                f"acquired_unix={time.time()}\n"
            )
        )

        handle.flush()


        yield


    finally:

        if acquired:

            try:

                handle.seek(
                    0
                )

                handle.truncate(
                    0
                )

                handle.flush()

            except Exception:
                pass


            try:

                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_UN,
                )

            except Exception:
                pass


        handle.close()
