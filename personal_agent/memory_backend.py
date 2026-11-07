"""Small project-owned memory contract, not a native Hermes provider or plugin SDK."""

import re
import unicodedata
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


def validate_request(operation: str, payload: dict) -> dict:
    fields = {
        "remember": ({"content", "request_id"}, {"topic"}),
        "correct": ({"record_id", "expected_revision", "request_id"}, {"content", "topic"}),
        "forget": ({"record_id", "expected_revision", "request_id"}, set()),
        "get": ({"record_id"}, set()),
        "list": (set(), {"limit", "after"}),
        "search": ({"query"}, {"limit", "after"}),
        "export": (set(), {"limit", "after"}),
    }
    if not isinstance(operation, str) or operation not in fields or not isinstance(payload, dict):
        raise MemoryError("invalid_request")
    required, optional = fields[operation]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise MemoryError("invalid_request")
    result = dict(payload)
    if operation == "remember":
        result.setdefault("topic", "")
    if operation == "correct" and not ({"content", "topic"} & result.keys()):
        raise MemoryError("invalid_request")
    for key, maximum, empty, multiline in (
        ("content", 2048, False, True),
        ("topic", 128, True, False),
        ("query", 128, False, False),
    ):
        if key in result:
            result[key] = _text(result[key], maximum, empty=empty, multiline=multiline)
    if "record_id" in result:
        result["record_id"] = _identifier(result["record_id"])
    if "request_id" in result:
        value = result["request_id"]
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is None:
            raise MemoryError("invalid_request")
    if "expected_revision" in result:
        value = result["expected_revision"]
        if type(value) is not int or not 1 <= value < 2**63 - 1:
            raise MemoryError("invalid_request")
    if operation in {"list", "search", "export"}:
        result = {"limit": 20, "after": None, **result}
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 50:
            raise MemoryError("invalid_request")
        if result["after"] is not None:
            result["after"] = _identifier(result["after"])
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
        if operation in {"remember", "correct", "forget"}:
            return result
        return {"data": result, "replayed": False}
