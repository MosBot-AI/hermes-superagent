"""Standard-library behavioral checks on caller-owned EMPTY synthetic stores.

Runs real mutations. Never point the factory at an existing user store. The
explicit consent flag and empty export check are guardrails, not a sandbox.
Passing verifies these observations, not malicious-code isolation, fsync or
crash safety, authenticated remote ownership, or complete SDK certification.
"""

from dataclasses import dataclass

from .memory_backend import MemoryError


@dataclass(frozen=True)
class ConformanceReport:
    sdk_version: int
    passed: tuple[str, ...]


def _check(condition):
    if not condition:
        raise MemoryError("conformance_failed")


def _reject(service, operation, payload, code):
    try:
        service.execute(operation, payload)
    except MemoryError as error:
        _check(error.code == code)
    else:
        raise MemoryError("conformance_failed")


def run_conformance(factory, *, isolated_synthetic: bool = False) -> ConformanceReport:
    """Factory returns a context manager for SDK sessions on ONE fresh test store.

    The caller owns store creation, connection closing, isolation and cleanup.
    This runner never deletes stores or chooses filesystem paths. Failure stops
    immediately and leaves synthetic evidence for inspection by the caller.
    """
    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    with factory() as service:
        page = service.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        request = {"content": "中文 Hermes % _ synthetic", "request_id": "sdk-create"}
        receipt = service.execute("remember", request)
        rid = receipt["data"]["record_id"]
    with factory() as service:
        _check(service.execute("remember", request) == {"data": receipt["data"], "replayed": True})
        _check(service.execute("get", {"record_id": rid})["data"]["content"] == request["content"])
        _reject(service, "remember", {**request, "content": "changed"}, "idempotency_conflict")
        _reject(
            service,
            "correct",
            {"record_id": rid, "expected_revision": 2, "request_id": "sdk-stale", "content": "bad"},
            "revision_conflict",
        )
        for query in ("中", "%", "_", "Hermes"):
            _check(len(service.execute("search", {"query": query})["data"]["items"]) == 1)
        _check(not service.execute("search", {"query": "hermes"})["data"]["items"])
        corrected = service.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "request_id": "sdk-correct",
                "content": "中文 updated",
            },
        )
        _check(corrected["data"]["revision"] == 2)
        service.execute("remember", {"content": "中文 " + "x" * 1800, "request_id": "sdk-large"})
        first = service.execute("list", {"limit": 1})["data"]
        _check(first["has_more"])
        second = service.execute("list", {"limit": 1, "after": first["next_cursor"]})["data"]
        _check(len(second["items"]) == 1 and not second["has_more"])
        context = service.context("中文", max_chars=1024)
        _check(context["items_json_chars"] <= 1024 and context["omitted_from_page"] == 1)
        _check(context["items"][0]["content"] == "中文 updated")
        service.execute(
            "forget", {"record_id": rid, "expected_revision": 2, "request_id": "sdk-forget"}
        )
    with factory() as service:
        _check(service.execute("remember", request)["replayed"])
        record = service.execute("get", {"record_id": rid})["data"]
        _check(record["status"] == "forgotten" and record["revision"] == 3)
        _check(all(record[key] is None for key in ("content", "topic", "source", "session_ref")))
        _check(not service.execute("search", {"query": "updated"})["data"]["items"])
        _reject(
            service,
            "correct",
            {
                "record_id": rid,
                "expected_revision": 3,
                "request_id": "sdk-revive",
                "content": "bad",
            },
            "record_forgotten",
        )
    return ConformanceReport(
        1,
        (
            "reopen_receipt",
            "cas",
            "idempotency",
            "literal_chinese",
            "pagination",
            "bounded_context",
            "terminal_tombstone",
        ),
    )


def run_progress_conformance(factory, *, isolated_synthetic: bool = False) -> ConformanceReport:
    """Optional progress suite on its own fresh store; CRUD-only factories need not run it.

    Uses the same isolation and reviewed-opener requirements as run_conformance.
    A cursor proves caller-reported local progress, never native checkpointing.
    """
    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    with factory() as service:
        page = service.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        _check(not service.execute("changes", {})["data"]["items"])
        _check(
            not service.execute("consumer_get", {"consumer_id": "projection"})["data"]["registered"]
        )
        created = service.execute("remember", {"content": "synthetic secret", "request_id": "p-r"})
        rid = created["data"]["record_id"]
        corrected = service.execute(
            "correct",
            {
                "record_id": rid,
                "content": "replacement secret",
                "expected_revision": 1,
                "request_id": "p-c",
            },
        )
        bound = corrected["data"]["event_sequence"]
        first = service.execute("changes", {"limit": 1, "through_sequence": bound})["data"]
        _check(first["has_more"] and first["items"][0]["operation"] == "remember")
        forgotten = service.execute(
            "forget",
            {
                "record_id": rid,
                "expected_revision": 2,
                "request_id": "p-f",
            },
        )
        last = forgotten["data"]["event_sequence"]
        second = service.execute(
            "changes",
            {
                "after_sequence": first["next_sequence"],
                "through_sequence": bound,
                "limit": 1,
            },
        )["data"]
        _check(not second["has_more"] and second["current_watermark"] == last)
        _check(second["items"][0]["operation"] == "correct")
        request = {
            "consumer_id": "projection",
            "through_sequence": bound,
            "expected_revision": 0,
            "request_id": "p-progress",
        }
        receipt = service.execute("consumer_advance", request)
    with factory() as service:
        _check(
            service.execute("consumer_advance", request)
            == {"data": receipt["data"], "replayed": True}
        )
        _reject(
            service,
            "consumer_advance",
            {**request, "through_sequence": last},
            "idempotency_conflict",
        )
        _reject(
            service, "consumer_advance", {**request, "request_id": "stale"}, "revision_conflict"
        )
        for sequence in (0, bound):
            _reject(
                service,
                "consumer_advance",
                {
                    **request,
                    "expected_revision": 1,
                    "through_sequence": sequence,
                    "request_id": "regressive",
                },
                "cursor_not_advanced",
            )
        _reject(
            service,
            "consumer_advance",
            {
                **request,
                "expected_revision": 1,
                "through_sequence": last + 1,
                "request_id": "future",
            },
            "future_watermark",
        )
        service.execute(
            "consumer_advance",
            {**request, "expected_revision": 1, "through_sequence": last, "request_id": "p-final"},
        )
        _check(
            not service.execute("consumer_get", {"consumer_id": "independent"})["data"][
                "registered"
            ]
        )
        _check(service.execute("consumer_advance", request)["replayed"])
    with factory() as service:
        current = service.execute("consumer_get", {"consumer_id": "projection"})["data"]
        _check(current["revision"] == 2 and current["through_sequence"] == last)
        feed = service.execute("changes", {})["data"]
        _check([item["operation"] for item in feed["items"]] == ["remember", "correct", "forget"])
        _check(service.execute("get", {"record_id": rid})["data"]["content"] is None)
    return ConformanceReport(
        1,
        (
            "bounded_metadata_changes",
            "progress_reopen",
            "progress_cas",
            "progress_idempotency",
            "no_rewind",
            "independent_consumers",
        ),
    )


def run_checkpoint_conformance(factory, *, isolated_synthetic: bool = False) -> ConformanceReport:
    """Optional metadata-checkpoint suite on a separate fresh synthetic store.

    Uses the same trusted-opener/isolation requirements as run_conformance.
    Receipts are historical metadata, never payload backups or native checkpoints.
    """
    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    with factory() as service:
        page = service.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        request = {"expected_watermark": 0, "request_id": "checkpoint-empty"}
        empty = service.execute("checkpoint_create", request)
        empty_id = empty["data"]["checkpoint_id"]
        _check(empty["data"]["event_count"] == empty["data"]["record_count"] == 0)
        _check(
            service.execute("checkpoint_status", {"checkpoint_id": empty_id})["data"]["is_current"]
        )
        created = service.execute(
            "remember", {"content": "synthetic checkpoint secret", "request_id": "checkpoint-r"}
        )["data"]
        rid = created["record_id"]
        first_request = {
            "expected_watermark": created["event_sequence"],
            "request_id": "checkpoint-first",
        }
        first = service.execute("checkpoint_create", first_request)
        _check(first["data"]["active_count"] == first["data"]["record_count"] == 1)
        _check(first["data"]["forgotten_count"] == 0)
        corrected = service.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "synthetic replacement secret",
                "request_id": "checkpoint-c",
            },
        )["data"]
        _check(
            not service.execute(
                "checkpoint_status",
                {
                    "checkpoint_id": first["data"]["checkpoint_id"],
                },
            )["data"]["is_current"]
        )
        _reject(
            service,
            "checkpoint_create",
            {
                **first_request,
                "request_id": "checkpoint-stale",
            },
            "watermark_conflict",
        )
        _reject(
            service,
            "checkpoint_create",
            {
                "expected_watermark": corrected["event_sequence"] + 1,
                "request_id": "checkpoint-future",
            },
            "watermark_conflict",
        )
        forgotten = service.execute(
            "forget",
            {
                "record_id": rid,
                "expected_revision": 2,
                "request_id": "checkpoint-f",
            },
        )["data"]
        final_request = {
            "expected_watermark": forgotten["event_sequence"],
            "request_id": "checkpoint-final",
        }
        final = service.execute("checkpoint_create", final_request)
        _check(final["data"]["event_count"] == 3)
        _check(final["data"]["record_count"] == final["data"]["forgotten_count"] == 1)
        _check(final["data"]["active_count"] == 0)
    with factory() as service:
        for payload, receipt in ((request, empty), (first_request, first), (final_request, final)):
            _check(
                service.execute("checkpoint_create", payload)
                == {
                    "data": receipt["data"],
                    "replayed": True,
                }
            )
        _reject(
            service,
            "checkpoint_create",
            {
                **request,
                "expected_watermark": forgotten["event_sequence"],
            },
            "idempotency_conflict",
        )
        status = service.execute(
            "checkpoint_status",
            {
                "checkpoint_id": final["data"]["checkpoint_id"],
            },
        )["data"]
        _check(status["is_current"] and status["checkpoint"] == final["data"])
        old = service.execute("checkpoint_status", {"checkpoint_id": empty_id})["data"]
        _check(not old["is_current"] and old["current_watermark"] == forgotten["event_sequence"])
        record = service.execute("get", {"record_id": rid})["data"]
        _check(record["status"] == "forgotten" and record["content"] is None)
    return ConformanceReport(
        1,
        (
            "empty_checkpoint",
            "current_and_stale",
            "checkpoint_reopen",
            "checkpoint_idempotency",
            "watermark_fence",
            "historical_replay_after_forget",
        ),
    )


def run_mutation_status_conformance(factory, *, isolated_synthetic=False) -> ConformanceReport:
    """Optional status checks on a separate, fresh caller-owned synthetic store.

    Writes fixtures intentionally; reconciliation itself never replays a write.
    This does not certify crash durability or a dishonest adapter's integrity.
    """
    from .memory_sdk import mutation_request_identity

    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    request = {"content": "Synthetic receipt fixture", "request_id": "status-create"}
    identity = mutation_request_identity("remember", request)
    with factory() as service:
        page = service.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        _check(
            service.execute("mutation_receipt_status", identity)["data"]["state"]
            == "absent_at_snapshot"
        )
        receipt = service.execute("remember", request)["data"]
    with factory() as service:
        status = service.execute("mutation_receipt_status", identity)
        _check(status["replayed"] is False and status["data"]["receipt"] == receipt)
        _reject(
            service,
            "mutation_receipt_status",
            {**identity, "expected_digest": "0" * 64},
            "idempotency_conflict",
        )
        _reject(
            service,
            "mutation_receipt_status",
            {**identity, "operation": "forget"},
            "idempotency_conflict",
        )
        correction = {
            "record_id": receipt["record_id"],
            "expected_revision": 1,
            "request_id": "status-correct",
            "expires_at": "2000-01-01T00:00:00Z",
        }
        correction_identity = mutation_request_identity("correct", correction)
        corrected = service.execute("correct", correction)["data"]
        status = service.execute("mutation_receipt_status", identity)["data"]
        _check(status["receipt"] == receipt and status["current"]["expired"] is True)
        forget = {
            "record_id": receipt["record_id"],
            "expected_revision": 2,
            "request_id": "status-forget",
        }
        forget_identity = mutation_request_identity("forget", forget)
        forgotten = service.execute("forget", forget)["data"]
    with factory() as service:
        for query, historical in (
            (identity, receipt),
            (correction_identity, corrected),
            (forget_identity, forgotten),
        ):
            status = service.execute("mutation_receipt_status", query)["data"]
            _check(status["receipt"] == historical)
            _check(
                status["current"]
                == {
                    "record_id": receipt["record_id"],
                    "revision": 3,
                    "status": "forgotten",
                    "expired": False,
                }
            )
        _check(service.execute("export", {"limit": 1})["data"]["watermark"] == 3)
    return ConformanceReport(
        1,
        (
            "missing_identity",
            "reopened_receipt",
            "identity_conflict",
            "historical_receipt",
            "expiry",
            "terminal_forget",
            "status_without_mutation_replay",
        ),
    )


def run_retained_source_conformance(factory, *, isolated_synthetic=False) -> ConformanceReport:
    """Optional retained-snapshot checks on a fresh caller-owned synthetic store.

    Deliberately stages and accepts synthetic snapshots; never reads native data.
    This is not evidence of live-source validity, host fencing or crash durability.
    """
    from hashlib import sha256

    from .memory_sdk import source_request_identity

    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    request = {
        "request_id": "source-conformance",
        "consumer_id": "synthetic-source",
        "expected_sequence": 0,
        "content": "Synthetic retained snapshot",
        "expires_at": None,
        "retention": "independent_snapshot",
        "source": {
            "identity": "a" * 64,
            "fingerprint": sha256(b"Synthetic retained snapshot").hexdigest(),
            "role": "user",
            "receipt_id": "b" * 64,
        },
    }
    identity = source_request_identity(request)
    with factory() as service:
        page = service.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        _check(service.execute("source_status", identity)["data"]["state"] == "absent_at_snapshot")
        staged = service.execute("source_stage", request)
        _check(staged["data"]["state"] == "pending" and staged["data"]["record"] is None)
        _check(service.execute("export", {"limit": 1})["data"]["watermark"] == 0)
        cursor = service.execute("source_cursor", {"consumer_id": request["consumer_id"]})["data"]
        _check(cursor["through_sequence"] == 0 and cursor["pending"] == staged["data"])
    with factory() as service:
        _check(
            service.execute("source_stage", request) == {"data": staged["data"], "replayed": True}
        )
        accepted = service.execute("source_accept", request)
        record = accepted["data"]["record"]
        _check(accepted["data"]["state"] == "accepted")
        _check(
            service.execute("get", {"record_id": record["record_id"]})["data"]["content"]
            == request["content"]
        )
        _reject(
            service,
            "source_status",
            {**identity, "expected_digest": "0" * 64},
            "idempotency_conflict",
        )
        service.execute(
            "forget",
            {
                "request_id": "source-forget",
                "record_id": record["record_id"],
                "expected_revision": 1,
            },
        )
    with factory() as service:
        _check(
            service.execute("source_accept", request)
            == {"data": accepted["data"], "replayed": True}
        )
        status = service.execute("source_status", identity)["data"]
        _check(status["decision"] == accepted["data"])
        _check(status["current"]["status"] == "forgotten" and status["suppressed"] is True)
        cursor = service.execute("source_cursor", {"consumer_id": request["consumer_id"]})["data"]
        _check(cursor["through_sequence"] == 1 and cursor["pending"] is None)
        discarded_request = {
            **request,
            "request_id": "source-discard-fixture",
            "expected_sequence": 1,
            "content": "Distinct discard snapshot",
            "source": {
                **request["source"],
                "identity": "c" * 64,
                "fingerprint": sha256(b"Distinct discard snapshot").hexdigest(),
            },
        }
        discarded_identity = source_request_identity(discarded_request)
        service.execute("source_stage", discarded_request)
        discarded = service.execute("source_discard", discarded_identity)
        _check(discarded["data"]["state"] == "discarded" and discarded["data"]["record"] is None)
    with factory() as service:
        _check(
            service.execute("source_discard", discarded_identity)
            == {"data": discarded["data"], "replayed": True}
        )
        cursor = service.execute("source_cursor", {"consumer_id": request["consumer_id"]})["data"]
        _check(cursor["through_sequence"] == 2 and cursor["pending"] is None)
        _check(service.execute("export", {"limit": 1})["data"]["watermark"] == 2)
    return ConformanceReport(
        1,
        (
            "absent_source",
            "metadata_stage",
            "pending_cursor",
            "reopen_accept",
            "identity_conflict",
            "terminal_replay",
            "source_discard",
            "independent_cursor",
        ),
    )


def run_managed_conformance(factory, binding, *, isolated_synthetic=False):
    """Exercise an explicit reviewed factory on ONE fresh synthetic store.

    Includes existing durable CRUD/replay gates, escaped-handle invalidation,
    repeated explicit close and readonly refusal. Fault injection and real
    native opener integration remain separate required tests.
    """
    from .memory_sdk import LocalMemorySDK

    report = run_conformance(
        lambda: LocalMemorySDK.session(factory, binding, mode="writable"),
        isolated_synthetic=isolated_synthetic,
    )
    with LocalMemorySDK.session(factory, binding, mode="writable") as sdk:
        sdk.close()
        sdk.close()
        _reject(sdk, "list", {}, "closed")
    _reject(sdk, "list", {}, "closed")
    with LocalMemorySDK.session(factory, binding, mode="readonly") as reader:
        _reject(reader, "remember", {"content": "must not write", "request_id": "ro"}, "read_only")
        reader.execute("list", {})
    _reject(reader, "list", {}, "closed")
    return ConformanceReport(
        sdk_version=report.sdk_version,
        passed=report.passed + ("managed_close", "escaped_handle", "readonly_session"),
    )


def run_record_origin_conformance(factory, *, isolated_synthetic=False):
    """Optional origin contract on ONE empty synthetic store; writes deliberate fixtures.

    Exercises direct-record absence of durable lineage and historical replay across
    correction, forgetting and reopening. Source-family lineage and corruption
    require adapter-specific fixtures, not fabricated universal source support.
    """
    if isolated_synthetic is not True:
        raise MemoryError("synthetic_store_required")
    with factory() as sdk:
        page = sdk.execute("export", {"limit": 1})["data"]
        if page["items"] or page["has_more"] or page["watermark"] != 0:
            raise MemoryError("empty_store_required")
        request = {"content": "Origin conformance synthetic record", "request_id": "origin-create"}
        receipt = sdk.execute("remember", request)["data"]
        rid = receipt["record_id"]
        first = sdk.execute("record_origin", {"record_id": rid})["data"]
        _check(first["origin"] == {"kind": "unavailable", "reason": "no_durable_lineage"})
        _check(first["current"]["revision"] == 1 and first["current"]["status"] == "active")
        _check(first["current_editing_route"] == "explicit_local_operator")
    with factory() as sdk:
        sdk.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "Corrected synthetic record",
                "request_id": "origin-edit",
            },
        )
        corrected = sdk.execute("record_origin", {"record_id": rid})["data"]
        _check(corrected["origin"] == first["origin"] and corrected["current"]["revision"] == 2)
        sdk.execute(
            "forget", {"record_id": rid, "expected_revision": 2, "request_id": "origin-forget"}
        )
    with factory() as sdk:
        _check(sdk.execute("remember", request) == {"data": receipt, "replayed": True})
        forgotten = sdk.execute("record_origin", {"record_id": rid})["data"]
        _check(forgotten["origin"] == first["origin"])
        _check(
            forgotten["current"]
            == {
                "record_id": rid,
                "revision": 3,
                "status": "forgotten",
                "expires_at": None,
                "expired": False,
            }
        )
        _check(forgotten["current_editing_route"] is None)
    return ConformanceReport(
        1,
        (
            "direct_origin_unavailable",
            "reopen_correction",
            "terminal_origin",
            "historical_replay_without_reconstruction",
        ),
    )
