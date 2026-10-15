from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    request,
)


from manager.security import (
    require_manager_session,
)

from manager.services.telegram_setup import (
    save_telegram_candidate,
    telegram_status,
    test_telegram_candidate,
)


# Stage 3B.1: Evidence of a successful Telegram test is tied to the
# exact Candidate bytes. Never store or expose the Token / Chat ID here.
import fcntl
import hashlib
import json
from pathlib import Path
from manager.services import wizard_store as _wizard_store


# Only delivery-test *metadata* may change during a test. Any Telegram
# operational setting, including token or chat ID, remains in the fingerprint.
# The Final Verification proof itself binds to the SHA-256 of the entire
# Candidate file *after* the test has completed.
_TEST_METADATA_KEYS = frozenset({
    "tested", "tested_at", "tested_ok", "test", "test_status",
    "test_result", "test_ok", "test_passed", "test_error",
    "test_message_id", "test_response", "test_timestamp",
    "last_test", "last_test_at", "last_tested_at", "last_test_ok",
    "last_tested_ok", "last_test_status", "last_test_result",
    "last_test_error", "last_test_message", "last_test_response",
    "last_test_timestamp", "last_delivery_test",
    "updated_at",
})


def _candidate_snapshot(site_id):
    site_id = _wizard_store.safe_site_id(site_id)
    directory = _wizard_store.CANDIDATE_DIR / site_id
    path = directory / "telegram.json"
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise RuntimeError("telegram_candidate_unavailable")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("telegram_candidate_invalid") from None
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("telegram_candidate_invalid")
    config = {k: v for k, v in payload.items() if k not in _TEST_METADATA_KEYS}
    if not config:
        raise RuntimeError("telegram_candidate_missing_configuration")
    # Canonical JSON ignores purely formatting/key-order rewrites by the
    # Telegram send/test backend, but not changes to operational settings.
    canonical = json.dumps(
        config, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return (hashlib.sha256(raw).hexdigest(),
            hashlib.sha256(canonical).hexdigest())


def _candidate_fingerprint(site_id):
    return _candidate_snapshot(site_id)[0]


def _record_telegram_proof(site_id, *, candidate_digest, tested):
    site_id = _wizard_store.safe_site_id(site_id)
    path = _wizard_store.STATE_DIR / (site_id + ".json")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("telegram_wizard_state_missing")
    _wizard_store.LOCK_FILE.touch(exist_ok=True)
    with _wizard_store.LOCK_FILE.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("site_id") != site_id:
                raise RuntimeError("telegram_wizard_state_invalid")
            if _candidate_fingerprint(site_id) != candidate_digest:
                raise RuntimeError("telegram_candidate_changed_during_test")
            previous = data.get("telegram") or {}
            if not isinstance(previous, dict):
                raise RuntimeError("telegram_wizard_state_invalid")
            entry = dict(previous)
            entry.update({
                "configured": True,
                "tested": bool(tested),
                "candidate_sha256": candidate_digest,
                "tested_candidate_sha256": candidate_digest if tested else None,
                "tested_at": _wizard_store.utc_now() if tested else None,
                "proof_version": 1,
            })
            data["telegram"] = entry
            data["updated_at"] = _wizard_store.utc_now()
            _wizard_store._atomic_write(path, data)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


telegram_setup_bp = Blueprint(
    "manager_telegram_setup",
    __name__,
)


@telegram_setup_bp.get(
    "/api/telegram-setup/"
    "<site_id>/status"
)
def telegram_setup_status(
    site_id,
):

    return jsonify({
        "ok":
            True,

        "status":
            telegram_status(
                site_id
            ),
    })


@telegram_setup_bp.post(
    "/api/telegram-setup/"
    "<site_id>/save"
)
@require_manager_session
def telegram_setup_save(
    site_id,
):

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )


    try:

        result = (
            save_telegram_candidate(
                site_id,

                token=
                    data.get(
                        "telegram_token"
                    ),

                chat_id=
                    data.get(
                        "telegram_chat_id"
                    ),
            )
        )


        # Successful save invalidates any previous test proof, even if the
        # replacement happens to contain the same credentials.
        proof_digest = _candidate_fingerprint(site_id)
        status_now = telegram_status(site_id)
        if not isinstance(status_now, dict) or status_now.get("configured") is not True:
            raise RuntimeError("telegram_candidate_not_configured")
        _record_telegram_proof(site_id, candidate_digest=proof_digest, tested=False)

        return jsonify({
            "ok": True,
            "status": result,
        })


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                f"{type(exc).__name__}: {exc}",
        }), 400


@telegram_setup_bp.post(
    "/api/telegram-setup/"
    "<site_id>/test"
)
@require_manager_session
def telegram_setup_test(
    site_id,
):

    try:
        # Snapshot before the network operation. A concurrent edit must not
        # inherit the successful test result of the old Candidate.
        _raw_before, configuration_before = _candidate_snapshot(site_id)
        result = test_telegram_candidate(site_id)
        if not isinstance(result, dict) or result.get("ok") is not True:
            return jsonify(result if isinstance(result, dict) else {
                "ok": False,
                "error": "telegram_test_failed",
                "runtime_changed": False,
            }), 400

        status_now = telegram_status(site_id)
        if (not isinstance(status_now, dict) or
                status_now.get("configured") is not True or
                status_now.get("tested") is not True):
            raise RuntimeError("telegram_test_status_not_verified")
        # The legacy send/test function is allowed to update test metadata
        # inside telegram.json, so compare operational configuration instead
        # of demanding that all Candidate file bytes remain identical.
        # Never use the old SHA for the new proof after a legitimate test.
        proof_digest, configuration_after = _candidate_snapshot(site_id)
        if configuration_after != configuration_before:
            raise RuntimeError("telegram_configuration_changed_during_test")
        _record_telegram_proof(site_id, candidate_digest=proof_digest, tested=True)
        return jsonify(result), 200


    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "error":
                f"{type(exc).__name__}: {exc}",

            "runtime_changed":
                False,
        }), 400
