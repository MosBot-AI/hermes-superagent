"""Small project-owned memory contract, not a native Hermes provider or plugin SDK."""

import re
import unicodedata
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID


class MemoryError(Exception):
    """Redacted, stable boundary error; never includes stored content."""

    def __init__(self, code: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(f"Local memory operation failed ({code}).")


def _text(value: object, maximum: int, *, empty: bool = False, multiline: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise MemoryError("invalid_request")
    if any(
        unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for c in value
        if not (multiline and c in "\n\t")
    ):
        raise MemoryError("invalid_request")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str):
        raise MemoryError("invalid_request")
    try:
        parsed = UUID(value)
    except ValueError:
        raise MemoryError("invalid_request") from None
    if parsed.version != 4 or str(parsed) != value:
        raise MemoryError("invalid_request")
    return value


def validate_expiry(value: object, *, error_code: str = "invalid_request") -> str | None:
    """Accept only a full, canonical Gregorian UTC second, or explicit null."""
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None
    ):
        raise MemoryError(error_code)
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise MemoryError(error_code) from None
    return value


def validate_request(operation: str, payload: dict) -> dict:
    if isinstance(operation, str) and operation.startswith("index_"):
        from .memory_index import validate

        return validate(operation, payload)
    if isinstance(operation, str) and operation.startswith("edit_"):
        from .memory_edits import validate

        return validate(operation, payload)
    if isinstance(operation, str) and operation.startswith("candidate_"):
        from .memory_candidate_store import validate

        return validate(operation, payload)
    fields = {
        "remember": ({"content", "request_id"}, {"topic", "expires_at"}),
        "correct": (
            {"record_id", "expected_revision", "request_id"},
            {"content", "topic", "expires_at"},
        ),
        "forget": ({"record_id", "expected_revision", "request_id"}, set()),
        "get": ({"record_id"}, set()),
        "list": (set(), {"limit", "after", "include_expired"}),
        "search": ({"query"}, {"limit", "after", "include_expired"}),
        "search_terms": ({"terms"}, {"limit", "after", "include_expired"}),
        "recall": ({"queries"}, {"limit", "max_chars"}),
        "export": (set(), {"limit", "after"}),
        "projection_disable": (set(), set()),
        "projection_status": (set(), set()),
        "projection_refresh": (set(), set()),
        "changes": (set(), {"limit", "after_sequence", "through_sequence"}),
        "checkpoint_create": ({"expected_watermark", "request_id"}, set()),
        "checkpoint_status": ({"checkpoint_id"}, set()),
        "consumer_get": ({"consumer_id"}, set()),
        "consumer_advance": (
            {"consumer_id", "through_sequence", "expected_revision", "request_id"},
            set(),
        ),
    }
    if not isinstance(operation, str) or operation not in fields or not isinstance(payload, dict):
        raise MemoryError("invalid_request")
    required, optional = fields[operation]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise MemoryError("invalid_request")
    result = dict(payload)
    if operation == "remember":
        result.setdefault("topic", "")
    if operation == "correct" and not ({"content", "topic", "expires_at"} & result.keys()):
        raise MemoryError("invalid_request")
    for key, maximum, empty, multiline in (
        ("content", 2048, False, True),
        ("topic", 128, True, False),
        ("query", 128, False, False),
    ):
        if key in result:
            result[key] = _text(result[key], maximum, empty=empty, multiline=multiline)
    # Do not inject defaults: historical mutation digests must remain identical.
    if "expires_at" in result:
        result["expires_at"] = validate_expiry(result["expires_at"])
    if "include_expired" in result and type(result["include_expired"]) is not bool:
        raise MemoryError("invalid_request")
    if "record_id" in result:
        result["record_id"] = _identifier(result["record_id"])
    if "checkpoint_id" in result:
        result["checkpoint_id"] = _identifier(result["checkpoint_id"])
    if "request_id" in result:
        value = result["request_id"]
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is None:
            raise MemoryError("invalid_request")
    if "expected_revision" in result:
        value = result["expected_revision"]
        minimum = 0 if operation == "consumer_advance" else 1
        if type(value) is not int or not minimum <= value < 2**63 - 1:
            raise MemoryError("invalid_request")
    if operation in {"list", "search", "search_terms", "export"}:
        result = {"limit": 20, "after": None, **result}
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 50:
            raise MemoryError("invalid_request")
        if result["after"] is not None:
            result["after"] = _identifier(result["after"])
    if operation == "search_terms":
        terms = result["terms"]
        if type(terms) is not list or not 1 <= len(terms) <= 8:
            raise MemoryError("invalid_request")
        validated_terms = [_text(term, 128) for term in terms]
        result["terms"] = validated_terms
        if len(set(validated_terms)) != len(terms):
            raise MemoryError("invalid_request")
    if operation == "recall":
        result = {"limit": 6, "max_chars": 6000, **result}
        queries = result["queries"]
        if type(queries) is not list or not 1 <= len(queries) <= 8:
            raise MemoryError("invalid_request")
        result["queries"] = [_text(query, 128) for query in queries]
        if len(set(result["queries"])) != len(queries):
            raise MemoryError("invalid_request")
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 20:
            raise MemoryError("invalid_request")
        if type(result["max_chars"]) is not int or not 1024 <= result["max_chars"] <= 12000:
            raise MemoryError("invalid_request")
    if operation == "changes":
        result = {"limit": 20, "after_sequence": 0, "through_sequence": None, **result}
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 50:
            raise MemoryError("invalid_request")
    for key in ("after_sequence", "through_sequence", "expected_watermark"):
        if key in result:
            value = result[key]
            if key == "through_sequence" and value is None and operation == "changes":
                continue
            if type(value) is not int or not 0 <= value < 2**63 - 1:
                raise MemoryError("invalid_request")
    if "consumer_id" in result:
        value = result["consumer_id"]
        if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None:
            raise MemoryError("invalid_request")
    return result


@runtime_checkable
class MemoryBackend(Protocol):
    """API v1 for the explicit local slice; no package-discovery or lifecycle claims."""

    def describe(self) -> dict: ...
    def execute(self, operation: str, payload: dict) -> dict: ...
    def close(self) -> None: ...


class MemoryService:
    """Use one backend after negotiating the explicit-record API and its limits."""

    def __init__(self, backend: MemoryBackend):
        from .memory_adapters import validate_backend_descriptor

        try:
            if not isinstance(backend, MemoryBackend) or not all(
                callable(getattr(backend, method)) for method in ("describe", "execute", "close")
            ):
                raise MemoryError("unsupported_backend")
            self.descriptor = validate_backend_descriptor(backend.describe())
        except Exception:
            raise MemoryError("unsupported_backend") from None
        self.backend = backend

    def execute(self, operation: str, payload: dict) -> dict:
        request = validate_request(operation, payload)
        self.descriptor.check_request(operation, request)
        result = self.backend.execute(operation, request)
        if operation.startswith(("candidate_", "edit_")) or operation in {
            "remember",
            "correct",
            "forget",
            "consumer_advance",
            "checkpoint_create",
        }:
            return result
        return {"data": result, "replayed": False}
