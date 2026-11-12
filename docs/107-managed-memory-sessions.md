# 107. Managed Local Memory Sessions

English | [简体中文](107-managed-memory-sessions-zh.md)

## Implemented boundary

Issue [#155](https://github.com/MosBot-AI/hermes-superagent/issues/155) adds resource lifetime management for explicitly reviewed local Python factories. `memory_sessions.FACTORY_VERSION = 1` is independent of SDK/API/schema versions. `MemoryFactory.acquire(resources, binding, mode)` receives an immutable `LocalBinding` and explicit `readonly` or `writable` mode. Version, binding type and mode are checked before acquisition. No module string, installed entry point or configuration value is executed to choose a factory.

Register every acquired resource immediately with `ResourceScope.register(cleanup)`, before the next fallible step. Register backend cleanup before backend initialization. Each registered callback is attempted exactly once, in reverse registration order, including after acquisition, descriptor/export admission, namespace rejection, body or cleanup failures and `BaseException`. A callback attempt is not a guarantee that an operating-system resource successfully closed. Undisclosed resources cannot be cleaned up automatically. Factories remain trusted in-process code, not a sandbox, authentication mechanism or hard timeout boundary.

`LocalMemorySDK.session(factory, binding, mode=...)` owns acquisition through cleanup and performs the existing bounded descriptor/export/namespace admission. Explicit `sdk.close()` drains managed resources; repeated close and later context exit do not repeat cleanup. The SDK is unusable after exit, including after cleanup failure. Cleanup callback attempts and error reporting are separate: an explicit close in an exception handler provisionally defers a cleanup error so a truly propagating primary error can win. If the managed context instead exits successfully, it reports that deferred `cleanup_failed` once. An already reported cleanup error is not reported again. Thus `ResourceScope.close(primary=error); close()` can report a deferred failure without repeating callbacks. Header and maintenance-lock cleanup capture only exceptions from their own operation, never unrelated ambient handled exceptions. The existing `LocalMemorySDK(backend, binding)` constructor retains its already-open contract: callers own acquisition/admission failures and the host connection; its `close()` closes only the backend.

Readonly managed SDK sessions reject all SDK mutations before backend dispatch, even when the factory advertises writable capabilities. Existing operator/model provenance and namespace validation remain in force. A binding is a trusted routing assertion, not proof of owner identity or honesty of arbitrary Python code.

## Production integration and error precedence

Both existing `open_memory_backend` and `open_existing_memory_reader` use the bundled `SQLiteMemoryFactory` and shared managed resource scope. Their signatures and yielded backend interfaces are unchanged. Profile/path checks, private-file admission and the complete maintenance-lock lifetime stay in the storage boundary. The factory itself accepts already-admitted paths; it is not an alternate path-validation or production replacement API. SQLite remains the only canonical authority for maintenance, projections and source operations.

The connection is registered before backend construction; backend cleanup is registered before PRAGMAs/open. A failed backend close cannot skip connection or lock cleanup. The raw readonly header descriptor is still closed before opening SQLite, preserving the existing POSIX descriptor/lock caveat. Readonly remains existing-only, with no creation/migration, unchanged header/journal refusal, `mode=ro` and `query_only`. Native production readers use the resource layer directly, with no new SDK export probe: metadata-only source recovery and bounded native recall retain their existing contracts.

An existing acquisition/admission/body error is preserved when cleanup also fails, including cancellation and `outcome_unknown`. Without a primary error, failed cleanup produces only redacted `cleanup_failed`, with retry disabled. Cleanup cannot retract a committed mutation and does not imply rollback. Keep an uncertain operation's original request identity and reconcile through the existing backend protocol; do not automatically issue another write.

## Independent example and conformance

Use only a fresh, explicitly isolated synthetic directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from personal_agent.memory_conformance import run_managed_conformance
from personal_agent.memory_sdk import LocalBinding
from personal_agent.memory_sdk_example import SyntheticMemoryFactory

with TemporaryDirectory() as directory:
    report = run_managed_conformance(
        SyntheticMemoryFactory(Path(directory)),
        LocalBinding("synthetic-example", "synthetic-session"),
        isolated_synthetic=True,
    )
    print(report)
```

The shared runner exercises durable CRUD/reopening/exact replay, explicit repeated close, escaped-handle invalidation and readonly refusal. Both the bundled SQLite factory and independently implemented synthetic factory run it. The independent example is educational, not production storage security or migration certification. Fault tests separately inject constructor/connect/PRAGMA/open, descriptor/export/binding, body and cleanup failures, including cancellation and combined cleanup faults. Existing CRUD/progress/checkpoint/source suites remain required; native contract tests verify actual production routes and fresh-process replay using synthetic data.

These are offline local observations, not deployed acceptance, power-loss guarantees, malicious-code containment or full E2.6 completion. No schema, recall semantics, frozen fixture/report, host pin/patch, public REST contract, provider selection, credentials, paid model calls or deployment changes are introduced. The broader doc30 replacement/migration and native lifecycle gates remain open.
