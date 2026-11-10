# 33. Explicit Memory Adapter Admission

English | [简体中文](33-memory-adapter-admission-zh.md)

Status: an implemented internal contract layer for the [explicit local slice](31-explicit-local-memory.md), plus **review-only installed-package metadata discovery**. This is not the complete SDK, a provider loader, a new configuration option or a native MemoryProvider bridge. The [full memory design](30-pluggable-memory-contracts.md) still governs future lifecycle, migration and remote-storage work.

## 1. Runtime Negotiation

`MemoryService` now validates the complete API-v1 descriptor before admitting an already selected backend. API/schema versions and numeric limits require actual integers, not booleans or coercible strings. Missing or unknown fields, unsupported major versions, duplicate/unknown capabilities, conflicting capability declarations and incompatible semantics fail with redacted `unsupported_backend`.

This version admits only `trusted_profile_local` explicit records with no declared external data recipients, literal case-sensitive substring search, terminal payload-purging tombstones and the existing non-restorable record-page export format. A descriptor is a declaration by reviewed code, not evidence that the code is honest, durable or unable to access the network. No malicious-Python containment is claimed.

The service takes an immutable copy of the negotiated capabilities and limits. Every request still passes ordinary payload validation, then operation-specific capability and size checks **before** calling the backend. Remember requires durable writes and idempotency; correction/forgetting also require CAS. Search and export require their corresponding capabilities. Read-only or reduced-capability adapters cannot silently receive unsupported writes. A smaller declared request limit produces `backend_limit_exceeded` instead of silently truncating data or widening the limit. The declared total-storage limits remain backend-enforced, not an independently counted service quota.

The existing SQLite backend satisfies this contract unchanged. Its storage schema, direct commands, session activation rules, native provider selection and persisted data are unchanged. Negotiation does not open a store, authenticate a human, certify factual truth, or promise automatic recall.

## 2. Metadata-Only Discovery and Selection

`discover_adapter_candidates()` explicitly reads installed entry-point metadata in the proposed project group `hermes_personal_agent.memory_backends`. It never calls an entry point's `load()`, imports its target, executes a factory, installs dependencies or accesses a credential. Ordinary plugin initialization does not invoke discovery. The native Hermes group `hermes_agent.memory_providers` is separate and is not inspected.

Each immutable `AdapterCandidate` contains the adapter ID, normalized distribution name, exact version and exact module/factory target. Discovery is limited to 128 entries and fails closed on malformed entries, duplicate IDs or attempts to reserve `local_sqlite`, `builtin`, `default` or `none`. It never chooses an arbitrary duplicate or falls back to another backend.

`select_reviewed_candidate(candidate)` re-reads metadata and requires the exact reviewed candidate to remain installed. A changed distribution, version or target returns `adapter_review_changed`; absence returns `adapter_not_installed`. This is a review helper, **not authorization, activation, an executable handle or an artifact signature**. A same-version package can still change its bytes. A future loader requires a reviewed artifact/installation and time-of-check/time-of-use policy, a common opening/resource ABI, scope binding, data-sharing admission and supported isolation before any third-party execution. The proposed `create_backend(host, config)` factory in [30](30-pluggable-memory-contracts.md) remains unimplemented.

## 3. Reusable Behavioral Gates

`tests/unit/test_memory_adapter_conformance.py` provides an `ExplicitRecordConformance` suite. An adapter can reuse it with an `open_adapter` fixture returning a context manager for the same fresh, isolated synthetic durable store across reopenings. The fixture owns resource creation, binding and cleanup. The bundled SQLite adapter runs it through both operator and activated-model provenance modes.

The shared gates cover durable reopen and exact receipt replay, changed-payload conflict, stale-revision rejection without mutation, terminal forgetting, tombstone export, historical replay without resurrection, short Chinese/literal wildcard searches, case sensitivity and bounded pagination. Mutation receipts exclude payload text. Separate admission tests cover malformed descriptors, capability/limit denial before execution, metadata changes, duplicate/reserved packages and no-import discovery. The repository's socket guard remains active.

These tests do not certify remote acknowledgements, malicious code, encrypted storage, snapshots, rollback/cutover, source attribution, native lifecycle or production recall quality. Existing SQLite transaction, migration, race and private-storage tests remain required alongside this reusable subset.

## 4. Verification and Remaining Gates

Run the ordinary aggregate checker, including the pinned-host contracts when that checkout/interpreter is available:

```bash
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

No new package is installed or selected, no production profile is modified, and no paid provider call is required. E2.6 gains a strict explicit-record contract and metadata-review precursor; it is not complete. The complete public SDK/loader and replacement activation/migration remain future work. Later local source, projection and checkpoint slices do not establish the full native lifecycle or external-storage contract. Passing these tests is not permission to enable them.

[36](36-bounded-memory-recall.md) adds the optional `bounded_recall` capability for explicit, single-snapshot literal retrieval with a whole-record JSON budget. Missing capability fails closed; it does not enable automatic native recall.

[85](85-local-memory-sdk.md) adds a separately invoked versioned local SDK facade and reusable standard-library conformance runner for reviewed explicit-record adapters. The ordinary plugin path described above remains unchanged; full E2.6 and loading/migration gates remain open.
