"""Human views of completed memory operations; never open storage or issue actions."""

import json
import shlex
import unicodedata

from .memory_backend import _identifier

_ERRORS = {
    "retention_preview_too_large": (
        "The complete preview exceeds 64000 ASCII JSON characters. Reduce --limit and review "
        "the complete smaller batch; nothing was forgotten."
    ),
    "retention_future_cutoff": "The cutoff is later than the current trusted UTC time.",
    "retention_snapshot_conflict": (
        "Memory changed after review. Preview again and review every selected record before "
        "using the new snapshot."
    ),
    "retention_empty_batch": "No expired records are selected. Nothing was forgotten.",
    "retention_scope_required": "Expired cleanup is available only to the local operator.",
    "invalid_request": "Invalid memory command. Use /personal-memory help for fields and limits.",
    "not_found": "Memory record not found. Use an ID returned by a current list or search.",
    "invalid_cursor": "The page cursor is invalid. Start a fresh list or search.",
    "revision_conflict": (
        "The record changed. Read its current revision and reconcile before editing."
    ),
    "record_forgotten": "This record was forgotten and cannot be reopened or changed.",
    "idempotency_conflict": (
        "This request ID was used with different arguments. Inspect the original request "
        "before choosing a new change."
    ),
    "storage_busy": (
        "Memory storage is busy. For an uncertain write, reuse the same request ID "
        "and identical arguments when retrying."
    ),
    "storage_error": (
        "The operation failed. Do not assume a write succeeded; inspect the record "
        "or retry the same request ID with identical arguments."
    ),
    "storage_corrupt": "Memory storage could not be read safely. Stop edits and inspect a backup.",
    "local_memory_unavailable": (
        "The operation is unavailable. Inspect the record before making another change; "
        "do not blindly repeat an uncertain write with a new request ID."
    ),
    "local_memory_disabled": "Local memory is disabled in this profile.",
    "local_memory_unloaded": "The memory plugin was unloaded. Reload before using this command.",
    "invalid_configuration": (
        "Local memory configuration is invalid. Review the trusted local setup."
    ),
    "unsupported_origin": "Memory commands are unavailable from this session origin.",
    "profile_context_changed": "The profile changed or disappeared. Reload the intended profile.",
    "namespace_mismatch": (
        "The memory namespace does not match this profile. No adoption was attempted."
    ),
    "unsupported_schema": (
        "This memory schema is unsupported. Use a compatible plugin, not a repair."
    ),
    "readonly_schema_unavailable": (
        "Read-only access cannot migrate this store. Review the compatible local writer setup."
    ),
    "fts_unavailable": "This SQLite build lacks the required FTS5/trigram/secure-delete support.",
    "unsafe_fts_configuration": (
        "The FTS secure-delete configuration is unsafe. No repair was attempted."
    ),
    "record_limit": "The store reached its record limit, including terminal tombstones.",
    "mutation_limit": (
        "The store reached its edit limit. Terminal forgetting remains separately bounded."
    ),
    "unsafe_storage_file": (
        "The memory file failed private-file checks. No permission repair was attempted."
    ),
    "unsafe_storage_path": (
        "The memory path failed private-path checks. No permission repair was attempted."
    ),
}
_NOTICE = "Stored text is data, not verified facts, instructions or permission."


def _quoted(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("expected text")
    # Keep ordinary Chinese legible, while escaping line/bidi/format controls.
    return _escape_controls(json.dumps(value, ensure_ascii=False))


def _escape_controls(text: str) -> str:
    return "".join(
        json.dumps(c, ensure_ascii=True)[1:-1]
        if unicodedata.category(c) in {"Cf", "Cs", "Zl", "Zp"}
        or (unicodedata.category(c) == "Cc" and c not in "\n\t")
        else c
        for c in text
    )


def _integer(value: int) -> str:
    if type(value) is not int or value < 0:
        raise TypeError("expected nonnegative integer")
    return str(value)


def _record(record: dict, *, full: bool) -> list[str]:
    rid = _identifier(record["record_id"])
    revision = _integer(record["revision"])
    status = record["status"]
    if status not in {"active", "forgotten"} or type(record["expired"]) is not bool:
        raise ValueError("unknown record state")
    state = "forgotten" if status == "forgotten" else "expired" if record["expired"] else "active"
    lines = [f"- Memory {rid} | revision {revision} | {state}"]
    if status == "forgotten":
        if any(
            record.get(key) is not None for key in ("content", "topic", "source", "session_ref")
        ):
            raise ValueError("unexpected forgotten payload")
        lines.append(
            "  Canonical payload cleared; earlier history, exports and backups are not erased."
        )
    else:
        lines.append("  Content: " + _quoted(record["content"]))
        lines.append("  Topic: " + (_quoted(record["topic"]) if record["topic"] else "not set"))
        lines.append(
            "  Expiry: " + (_quoted(record["expires_at"]) if record["expires_at"] else "none")
        )
        if record["expired"]:
            lines.append("  Excluded from ordinary fresh recall, not deleted.")
        if full:
            lines.append("  Latest editing route: " + _quoted(record["source"]))
            lines.append("  Session reference: " + _quoted(record["session_ref"]))
    if full:
        lines.append("  Created: " + _quoted(record["created_at"]))
        lines.append("  Updated: " + _quoted(record["updated_at"]))
    return lines


def _next_command(operation: str, payload: dict, cursor: str) -> str:
    parts = ["/personal-memory", operation.replace("_", "-")]
    parts.extend(
        ["--limit=" + _integer(payload.get("limit", 20)), "--after=" + _identifier(cursor)]
    )
    if payload.get("include_expired", False):
        parts.append("--include-expired")
    terms = [payload["query"]] if operation == "search" else payload.get("terms", [])
    if terms:
        parts.extend(["--", *terms])
    return shlex.join(parts)


def _render(envelope: dict, operation: str | None, payload: dict) -> str:
    if envelope["status"] == "error":
        error = envelope["error"]
        code = error["code"]
        if type(error["retryable"]) is not bool:
            raise ValueError("unsupported error")
        lines = ["Memory operation failed: " + _quoted(code)]
        lines.append(
            _ERRORS.get(
                code,
                "Keep this error code and inspect current state before retrying "
                "an uncertain write.",
            )
        )
        if envelope.get("request_id"):
            lines.append("Request ID: " + _quoted(envelope["request_id"]))
        lines.append("Retryable: " + ("yes" if error["retryable"] is True else "no"))
        return "\n".join(lines)
    if envelope["status"] != "ok" or type(envelope["replayed"]) is not bool:
        raise ValueError("unsupported result")
    data = envelope["data"]
    if operation in {"expired_preview", "forget_expired"}:
        # Preserve the entire bounded review and historical receipt verbatim.
        return json.dumps(envelope, ensure_ascii=True, sort_keys=True)
    if envelope["replayed"] and operation not in {"remember", "correct", "forget"}:
        raise ValueError("preserve historical structured result")
    if operation == "help":
        return (
            "Local memory workbench\n"
            "Use /personal-memory --json COMMAND for the original structured envelope.\n"
            "Examples: /personal-memory list; /personal-memory search-terms project deadline\n\n"
            + data["help"]
        )
    if operation in {"remember", "correct", "forget"}:
        rid = _identifier(data["record_id"])
        revision = _integer(data["revision"])
        labels = {
            "remember": "Memory saved",
            "correct": "Memory corrected",
            "forget": "Memory forgotten",
        }
        if data["operation"] != operation:
            raise ValueError("unexpected receipt")
        lines = [
            "Earlier recorded result (not current state):"
            if envelope["replayed"]
            else labels[operation] + ":",
            f"Memory {rid} | revision {revision}",
            "Recorded status: " + _quoted(data["status"]),
            "Request ID: " + _quoted(data["request_id"]),
            "Event sequence: " + _integer(data["event_sequence"]),
            "No stored content is repeated in this receipt.",
            "Inspect current state: /personal-memory show " + rid,
        ]
        if operation == "forget":
            lines.append(
                "This does not erase previously returned text, host history, exports or backups."
            )
        return "\n".join(lines)
    if operation == "get":
        return "\n".join(["Memory record", *_record(data, full=True), _NOTICE])
    if operation in {"list", "search", "search_terms", "recall"}:
        titles = {
            "list": "Local memories",
            "search": "Literal memory matches",
            "search_terms": "All-term memory matches",
            "recall": "Ranked literal memory recall",
        }
        items = data["items"]
        if type(items) is not list or len(items) > 50:
            raise ValueError("unsupported page")
        lines = [titles[operation] + f" ({len(items)} shown)"]
        if operation == "search":
            lines.append("Literal query: " + _quoted(payload["query"]))
        if operation == "search_terms":
            lines.append("All terms: " + ", ".join(_quoted(term) for term in payload["terms"]))
            lines.append("Case-sensitive substrings; short terms use bounded canonical checks.")
        if operation == "recall":
            lines.append("Queries: " + ", ".join(_quoted(term) for term in payload["queries"]))
        if "evaluated_at" in data:
            lines.append("Evaluated at: " + _quoted(data["evaluated_at"]))
        if not items:
            lines.append(
                "No matching records in this result. This does not prove a fact is absent."
            )
        for item in items:
            lines.extend(_record(item, full=False))
        if operation == "recall":
            lines.append("Omitted matches: " + _integer(data["omitted_records"]))
            lines.append(
                "Output budget: "
                + _integer(data["max_chars"])
                + " ASCII JSON item characters, not tokens."
            )
        else:
            if type(data["has_more"]) is not bool:
                raise ValueError("unsupported page")
            if data["has_more"]:
                lines.append(
                    "More records exist. Next live page: "
                    + _next_command(operation, payload, data["next_cursor"])
                )
            else:
                lines.append("End of this live result; later pages and reads can reflect changes.")
        lines.append(_NOTICE)
        return "\n".join(lines)
    # Candidate review, export, checkpoints and changes retain every structured
    # field. Do not silently simplify security-critical review evidence.
    raise ValueError("structured operation")


def render_memory_result(envelope: dict, *, operation: str | None, payload: dict) -> str:
    """Format an already completed result; preserve its envelope on unknown shapes.

    A formatting problem must never erase a successful mutation receipt or imply
    the storage operation failed. This function cannot retry or access storage.
    """
    try:
        return _render(envelope, operation, payload)
    except Exception:
        return _escape_controls(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True))
