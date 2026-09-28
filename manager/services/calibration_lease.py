from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time

from pathlib import Path


from manager.services.wizard_store import (
    ROOT,
    safe_site_id,
)


LEASE_FILE = (
    ROOT
    / "calibration_lease.json"
)

LOCK_FILE = (
    ROOT
    / "calibration_lease.lock"
)


DEFAULT_TTL_SEC = 180


class CalibrationLeaseBusy(
    RuntimeError
):
    pass


class CalibrationLeaseMissing(
    RuntimeError
):
    pass


class CalibrationLeaseExpired(
    RuntimeError
):
    pass


def _atomic_write(
    data,
):

    LEASE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    fd, temp_name = (
        tempfile.mkstemp(
            dir=str(
                LEASE_FILE.parent
            ),
            prefix=".calibration_lease.",
        )
    )


    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:

            json.dump(
                data,
                handle,
                ensure_ascii=False,
                indent=2,
            )

            handle.flush()

            os.fsync(
                handle.fileno()
            )


        os.replace(
            temp_name,
            LEASE_FILE,
        )


    finally:

        try:

            os.unlink(
                temp_name
            )

        except FileNotFoundError:
            pass


def _read_unlocked():

    if not LEASE_FILE.exists():

        return None


    try:

        data = json.loads(
            LEASE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


    if not isinstance(
        data,
        dict,
    ):

        return None


    return data


def _locked(
    callback,
):

    ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOCK_FILE.touch(
        exist_ok=True
    )


    with LOCK_FILE.open(
        "r+"
    ) as lock:

        fcntl.flock(
            lock,
            fcntl.LOCK_EX,
        )


        try:

            return callback()

        finally:

            fcntl.flock(
                lock,
                fcntl.LOCK_UN,
            )


def lease_expired(
    lease,
    *,
    now=None,
):

    if not lease:

        return False


    if now is None:

        now = time.time()


    try:

        expires_at = float(
            lease[
                "expires_at"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        return True


    return (
        now
        >=
        expires_at
    )


def read_lease():

    def read():

        return _read_unlocked()


    return _locked(
        read
    )


def create_lease(
    site_id,
    *,
    ttl_sec=DEFAULT_TTL_SEC,
):

    site_id = safe_site_id(
        site_id
    )

    ttl_sec = float(
        ttl_sec
    )


    if ttl_sec < 30:

        raise ValueError(
            "Calibration lease TTL "
            "ต้องไม่น้อยกว่า 30 วินาที"
        )


    def create():

        now = time.time()

        current = (
            _read_unlocked()
        )


        if current:

            current_site = str(
                current.get(
                    "site_id"
                )
                or ""
            )


            if lease_expired(
                current,
                now=now,
            ):

                raise CalibrationLeaseExpired(
                    "พบ Calibration Lease "
                    "ที่หมดอายุแล้ว "
                    "กำลังรอ Watchdog recovery"
                )


            if (
                current_site
                != site_id
            ):

                raise CalibrationLeaseBusy(
                    "Calibration Mode "
                    "กำลังถูกใช้งานโดย "
                    f"Site {current_site}"
                )


            # Same Site: renew existing lease.
            started_at = float(
                current.get(
                    "started_at",
                    now,
                )
            )

        else:

            started_at = now


        lease = {
            "version":
                1,

            "site_id":
                site_id,

            "started_at":
                started_at,

            "updated_at":
                now,

            "ttl_sec":
                ttl_sec,

            "expires_at":
                now
                +
                ttl_sec,
        }


        _atomic_write(
            lease
        )


        return lease


    return _locked(
        create
    )


def renew_lease(
    site_id,
):

    site_id = safe_site_id(
        site_id
    )


    def renew():

        now = time.time()

        current = (
            _read_unlocked()
        )


        if not current:

            raise CalibrationLeaseMissing(
                "Calibration Lease "
                "ไม่พบ"
            )


        if (
            str(
                current.get(
                    "site_id"
                )
            )
            != site_id
        ):

            raise CalibrationLeaseBusy(
                "Calibration Lease "
                "เป็นของ Site อื่น"
            )


        if lease_expired(
            current,
            now=now,
        ):

            raise CalibrationLeaseExpired(
                "Calibration Lease "
                "หมดอายุแล้ว"
            )


        ttl_sec = float(
            current.get(
                "ttl_sec",
                DEFAULT_TTL_SEC,
            )
        )


        current[
            "updated_at"
        ] = now

        current[
            "expires_at"
        ] = (
            now
            +
            ttl_sec
        )


        _atomic_write(
            current
        )


        return current


    return _locked(
        renew
    )


def release_lease(
    site_id=None,
    *,
    force=False,
):

    if site_id is not None:

        site_id = safe_site_id(
            site_id
        )


    def release():

        current = (
            _read_unlocked()
        )


        if not current:

            return False


        if (
            not force
            and
            site_id is not None
            and
            str(
                current.get(
                    "site_id"
                )
            )
            != site_id
        ):

            raise CalibrationLeaseBusy(
                "ไม่สามารถ release "
                "Calibration Lease "
                "ของ Site อื่น"
            )


        try:

            LEASE_FILE.unlink()

        except FileNotFoundError:
            pass


        return True


    return _locked(
        release
    )
