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
