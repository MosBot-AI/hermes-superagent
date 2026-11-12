"""Versioned resource lifetime for explicit reviewed trusted-local factories.

Factories are code, not a sandbox: register each acquired resource before the
next fallible step. Undisclosed resources and committed effects cannot be undone.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from .memory_backend import MemoryBackend, MemoryError, _text

FACTORY_VERSION = 1
SessionMode = Literal["readonly", "writable"]


@dataclass(frozen=True)
class LocalBinding:
    """Host assertion of local routing, not proof of remote owner identity."""

    namespace_id: str
    session_ref: str
    source_kind: str = "explicit_local_operator"

    def __post_init__(self):
        _text(self.namespace_id, 256)
        _text(self.session_ref, 256)
        if self.source_kind not in {"explicit_local_operator", "activated_session_model"}:
            raise MemoryError("invalid_request")


class ResourceScope:
    """Attempt registered cleanup once in reverse order, including cancellation.

    Cleanup cannot retract a committed mutation. A primary failure always wins;
    otherwise only a redacted retry-disabled cleanup error crosses the boundary.
    """

    def __init__(self):
        self._callbacks: list[Callable[[], object]] = []
        self._closed = False
        self._unreported_failure = False

    def register(self, cleanup: Callable[[], object]) -> None:
        if self._closed or not callable(cleanup):
            raise MemoryError("invalid_resource_registration")
        self._callbacks.append(cleanup)

    def close(self, *, primary: BaseException | None = None) -> None:
        if not self._closed:
            self._closed = True
            while self._callbacks:
                cleanup = self._callbacks.pop()
                try:
                    cleanup()
                except BaseException:
                    self._unreported_failure = True
        # Explicit SDK close may run in an except/finally block. An active
        # exception is only a provisional primary until the managed scope exits.
        # Preserve it now, but report deferred cleanup if exit actually succeeds.
        if self._unreported_failure and primary is None:
            self._unreported_failure = False
            raise MemoryError("cleanup_failed") from None


class MemoryFactory(Protocol):
    """Explicit trusted object, never a module string or entry-point loader.

    acquire must register resources immediately, including backend.close before
    backend initialization. Returned backend remains bound for this scope only.
    """

    factory_version: int

    def acquire(
        self, resources: ResourceScope, binding: LocalBinding, mode: SessionMode
    ) -> MemoryBackend: ...


@contextmanager
def managed_backend(
    factory: MemoryFactory, binding: LocalBinding, *, mode: SessionMode
) -> Generator[tuple[MemoryBackend, ResourceScope]]:
    """Own acquisition and cleanup; deliberately perform no SDK export probe."""
    if (
        type(binding) is not LocalBinding
        or type(mode) is not str
        or mode not in {"readonly", "writable"}
    ):
        raise MemoryError("invalid_request")
    if (
        type(getattr(factory, "factory_version", None)) is not int
        or factory.factory_version != FACTORY_VERSION
        or not callable(getattr(factory, "acquire", None))
    ):
        raise MemoryError("unsupported_factory")
    resources = ResourceScope()
    primary = None
    try:
        backend = factory.acquire(resources, binding, mode)
        yield backend, resources
    except BaseException as error:
        primary = error
        raise
    finally:
        resources.close(primary=primary)
