"""Unwired, default-denied synchronous read coordination, not an identity issuer.

Only independently trusted adapters may implement these protocols. Python types
and pending database labels are not authentication. No production adapter, route,
TaskStore access, durable admission audit or reusable authorization token exists.
Lock order: host invalidation guard -> enrollment transaction -> resource fence.
Never prompt, network, dispatch workers or perform long tasks inside these fences.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from unicodedata import category

from .authorization import (
    ReadGrant,
    ReadRequest,
    VerifiedReadContext,
    _identifier,
    _revision,
    _scope,
    evaluate_read,
)
from .enrollment import EnrollmentError, EnrollmentStore

MAX_TASKS = 32
MAX_TITLE_LENGTH = 240
_ERROR_CODES = frozenset(
    {
        "unavailable",
        "admission_failed",
        "policy_denied",
        "invalid_request",
        "invalid_confirmation",
        "confirmation_mismatch",
        "authorization_denied",
        "identity_mismatch",
        "scope_mismatch",
        "snapshot_incomplete",
        "invalid_snapshot",
    }
)


class ReadAdmissionError(Exception):
    """Redacted failure, with no private data or adapter exception text."""

    def __init__(self, code: str):
        code = code if type(code) is str and code in _ERROR_CODES else "admission_failed"
        self.code = code
        super().__init__(f"Read admission failed ({code}).")


@dataclass(frozen=True, slots=True)
class ReadConfirmation:
    """Independent approval bound to exact host, enrollment, identity and request.

    Issued only by a trusted host authority, never synthesized from pending rows.
    Context/grant include session, policy revision and epoch. The authority owns
    one-shot consumption and checks host incarnation, expiry and invalidation.
    """

    enrollment_id: str
    enrollment_revision: int
    host_incarnation: str
    context: VerifiedReadContext
    grant: ReadGrant
    request: ReadRequest


@dataclass(frozen=True, slots=True)
class TaskSummary:
    task_id: str
    title: str
    state: str
    due_date: str | None


class AdmissionGuard(Protocol):
    confirmation: ReadConfirmation
    host_incarnation: str

    def validate_and_now(self) -> datetime:
        """Revalidate live confirmation/fences; sample trusted UTC AFTER waits.

        Hold real identity/session/route/connection invalidation and host-instance
        fences until context-manager exit. Raise on any invalidation or expiry.
        A timestamp supplied by the request or copied handle is never sufficient.
        """
        ...


class HostAuthority(Protocol):
    def hold_admission(self, live_handle: object) -> AbstractContextManager[AdmissionGuard]:
        """Consume independently approved one-shot handle; hold invalidation fence.

        Do not interpret caller JSON as authority. Failed attempts remain consumed.
        No production implementation is provided by this package.
        """
        ...


class ResourceSnapshot(Protocol):
    def read_summaries(self) -> tuple[TaskSummary, ...]:
        """Eager bounded minimal projection, under already established ownership.

        Never fetch full details, source bodies or secrets and then redact them.
        No lazy cursors. Keep resource ownership/data stable until snapshot exit.
        """
        ...


class ResourceSource(Protocol):
    def open_snapshot(
        self, owner_id: str, profile_id: str, request: ReadRequest
    ) -> AbstractContextManager[ResourceSnapshot]:
        """Fence exact resources and independently establish ownership before read.

        Enter may wait but must NOT read private summary fields. Only the later
        read_summaries call reads them, after authorization inside every fence.
        No automatic adoption of existing local tasks or unbounded collection scan.
        """
        ...


def _bounded_request(request: object) -> bool:
    return (
        type(request) is ReadRequest
        and _scope(request)
        and request.operation == "personal.tasks.read"
        and request.target == "exact_tasks"
        and request.data_scope == "tasks.summary"
        and 1 <= len(request.resource_ids) <= MAX_TASKS
    )


def _due_date(value: object) -> bool:
    if value is None:
        return True
    if type(value) is not str or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _summaries(value: object, request: ReadRequest) -> tuple[TaskSummary, ...]:
    if type(value) is not tuple or len(value) != len(request.resource_ids):
        raise ReadAdmissionError("invalid_snapshot")
    ids = []
    by_id: dict[str, TaskSummary] = {}
    for item in value:
        if (
            type(item) is not TaskSummary
            or not _identifier(item.task_id)
            or type(item.title) is not str
            or not 1 <= len(item.title) <= MAX_TITLE_LENGTH
            or not item.title.strip()
            or any(category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in item.title)
            or type(item.state) is not str
            or item.state not in ("captured", "done", "cancelled")
            or not _due_date(item.due_date)
        ):
            raise ReadAdmissionError("invalid_snapshot")
        ids.append(item.task_id)
        by_id[item.task_id] = item
    if len(set(ids)) != len(ids) or set(ids) != set(request.resource_ids):
        raise ReadAdmissionError("invalid_snapshot")
    # Preserve requested ordering, never return an adapter's mutable/lazy result.
    return tuple(by_id[task_id] for task_id in request.resource_ids)


class ReadAdmissionService:
    def __init__(
        self,
        store: EnrollmentStore,
        *,
        host_authority: HostAuthority | None = None,
        resource_source: ResourceSource | None = None,
        enabled: bool = False,
    ):
        self._store = store
        self._host_authority = host_authority
        self._resource_source = resource_source
        self._enabled = enabled

    def read(
        self, key: dict, request: ReadRequest, *, live_handle: object
    ) -> tuple[TaskSummary, ...]:
        """Return data only after snapshot close, successful commit and guard exit.

        The selector is not identity evidence. Exact confirmation/grant/request
        tuples must match (no subset reuse); proposed policy may be a superset.
        Exceptions cannot return data. No authorization decision is cached/replayed.
        """
        if (
            self._enabled is not True
            or self._host_authority is None
            or self._resource_source is None
        ):
            raise ReadAdmissionError("unavailable")
        try:
            return self._read(key, request, live_handle)
        except ReadAdmissionError as error:
            # Never propagate adapter-owned messages, args or subclass __str__.
            code = (
                getattr(error, "code", "admission_failed")
                if type(error) is ReadAdmissionError
                else "admission_failed"
            )
            raise ReadAdmissionError(code) from None
        except EnrollmentError:
            raise ReadAdmissionError("policy_denied") from None
        except Exception:
            raise ReadAdmissionError("admission_failed") from None

    def _read(
        self, key: dict, request: ReadRequest, live_handle: object
    ) -> tuple[TaskSummary, ...]:
        if (
            type(key) is not dict
            or key.keys() != {"owner_id", "profile_id", "enrollment_id"}
            or not all(_identifier(value) for value in key.values())
            or not _bounded_request(request)
        ):
            raise ReadAdmissionError("invalid_request")
        key = dict(key)
        assert self._host_authority is not None and self._resource_source is not None
        with self._host_authority.hold_admission(live_handle) as guard:
            confirmation = guard.confirmation
            if (
                type(confirmation) is not ReadConfirmation
                or not _identifier(confirmation.enrollment_id)
                or not _revision(confirmation.enrollment_revision)
                or confirmation.enrollment_revision < 1
                or not _identifier(confirmation.host_incarnation)
                or type(guard.host_incarnation) is not str
                or confirmation.host_incarnation != guard.host_incarnation
                or type(confirmation.context) is not VerifiedReadContext
                or type(confirmation.grant) is not ReadGrant
                or not _bounded_request(confirmation.request)
                or confirmation.request != request
                or confirmation.enrollment_id != key["enrollment_id"]
            ):
                raise ReadAdmissionError("invalid_confirmation")
            context, grant = confirmation.context, confirmation.grant
            if (
                context.owner_id != key["owner_id"]
                or context.profile_id != key["profile_id"]
                or (grant.operation, grant.target, grant.resource_ids, grant.data_scope)
                != (request.operation, request.target, request.resource_ids, request.data_scope)
            ):
                raise ReadAdmissionError("confirmation_mismatch")

            def check(policy_revision: int, epoch: int) -> None:
                decision = evaluate_read(
                    context,
                    grant,
                    request,
                    current_policy_revision=policy_revision,
                    current_epoch=epoch,
                    now=guard.validate_and_now(),
                )
                if not decision.allowed:
                    raise ReadAdmissionError("authorization_denied")

            # Reject malformed authority before accessing storage at all.
            check(context.policy_revision, context.epoch)

            def read_current(record: dict) -> tuple[TaskSummary, ...]:
                if any(
                    record[name] != getattr(context, name)
                    for name in (
                        "owner_id",
                        "profile_id",
                        "transport_id",
                        "transport_receiver_id",
                        "principal_id",
                    )
                ):
                    raise ReadAdmissionError("identity_mismatch")
                candidate = ReadRequest(**record["scope"])
                if not _bounded_request(candidate) or not set(request.resource_ids).issubset(
                    candidate.resource_ids
                ):
                    raise ReadAdmissionError("scope_mismatch")
                check(record["policy_revision"], record["epoch"])
                assert self._resource_source is not None
                completed = False
                with self._resource_source.open_snapshot(
                    context.owner_id, context.profile_id, request
                ) as snapshot:
                    check(record["policy_revision"], record["epoch"])
                    summaries = _summaries(snapshot.read_summaries(), request)
                    check(record["policy_revision"], record["epoch"])
                    completed = True
                if not completed:
                    raise ReadAdmissionError("snapshot_incomplete")
                return summaries

            result = self._store.with_current_record(
                key,
                expected_revision=context.policy_revision,
                expected_enrollment_revision=confirmation.enrollment_revision,
                expected_epoch=context.epoch,
                operation=read_current,
            )
        return result
