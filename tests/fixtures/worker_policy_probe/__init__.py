"""Test-only independently issued synthetic confirmations and owned resources.

No pending row, model argument or draft is converted into authority. The harness
supplies one-shot handles out of band. This is not a production trust adapter.
"""

import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from personal_agent.authorization import ReadGrant, ReadRequest, VerifiedReadContext
from personal_agent.read_admission import (
    ReadAdmissionError,
    ReadAdmissionService,
    ReadConfirmation,
    TaskSummary,
)

KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "enrollment"}
REQUEST = ReadRequest("personal.tasks.read", "exact_tasks", ("task",), "tasks.summary")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = {
    name: getattr(REQUEST, name) for name in ("operation", "target", "resource_ids", "data_scope")
}
STORE = None
HOST = None
SOURCE = None
HANDLE = None
CALLS = 0


class SyntheticHost:
    def __init__(self, revision=1, epoch=0, enrollment_revision=1):
        self.lock = threading.RLock()
        self.handle = object()
        self.used = False
        self.host_incarnation = "synthetic-host"
        context = VerifiedReadContext(
            "owner",
            "profile",
            "synthetic",
            "bot",
            "actor",
            "session",
            revision,
            epoch,
            ("task",),
        )
        grant = ReadGrant(
            "synthetic-grant",
            "owner",
            "profile",
            "synthetic",
            "bot",
            "actor",
            "session",
            revision,
            epoch,
            REQUEST.operation,
            REQUEST.target,
            REQUEST.resource_ids,
            REQUEST.data_scope,
            NOW - timedelta(seconds=1),
            NOW + timedelta(seconds=60),
            False,
        )
        self.confirmation = ReadConfirmation(
            "enrollment", enrollment_revision, self.host_incarnation, context, grant, REQUEST
        )

    @contextmanager
    def hold_admission(self, handle):
        with self.lock:
            if handle is not self.handle or self.used:
                raise ValueError("synthetic private confirmation error")
            self.used = True
            yield self

    def validate_and_now(self):
        return NOW


class SyntheticSource:
    def __init__(self):
        self.lock = threading.RLock()
        self.reads = 0
        self.entries = 0
        self.on_read = lambda: None

    @contextmanager
    def open_snapshot(self, owner_id, profile_id, request):
        with self.lock:
            assert (owner_id, profile_id, request) == ("owner", "profile", REQUEST)
            self.entries += 1
            yield self

    def read_summaries(self):
        self.reads += 1
        self.on_read()
        return (TaskSummary("task", "Synthetic bounded summary", "captured", None),)


def handler(args, **_context):
    global CALLS
    CALLS += 1
    # Ignore caller-supplied authority claims, including approved/draft metadata.
    service = ReadAdmissionService(STORE, host_authority=HOST, resource_source=SOURCE, enabled=True)
    try:
        rows = service.read(KEY, REQUEST, live_handle=HANDLE)
        return json.dumps({"titles": [row.title for row in rows]})
    except ReadAdmissionError as error:
        return json.dumps({"denied": error.code})


def register(ctx):
    ctx.register_tool(
        name="worker_policy_probe",
        toolset="worker_policy_probe",
        schema={
            "name": "worker_policy_probe",
            "description": "Synthetic bounded read",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=handler,
    )
