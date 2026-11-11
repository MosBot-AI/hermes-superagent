# 85. Versioned Local Memory SDK

English | [简体中文](85-local-memory-sdk-zh.md)

## Scope

The project-owned local SDK is an explicit facade for **already reviewed and opened** adapters. It gives adapter authors a reusable request/result boundary and behavioral conformance runner for the API-v1 explicit-record subset. It is not the complete E2.6 design in [30](30-pluggable-memory-contracts.md), a public REST API, a third-party loader or a replacement for Hermes's native memory provider.

The supported scope is `trusted_profile_local`. A trusted opener owns store selection, resource lifetime and profile binding. SDK admission requires a bounded export read and checks its namespace against the binding before permitting operations; adapters without export capability are not admitted. This catches ordinary mismatched routing, not a dishonest adapter that lies about its namespace. Passing a Python binding object is not proof of human identity, tenant authorization or malicious-code containment. Request payloads cannot choose an owner, namespace, arbitrary filesystem path, URL or SQL statement. Reviewed in-process Python remains trusted code.

The ordinary plugin's existing `MemoryService` and SQLite storage remain unchanged. No configured provider is switched, no production profile is opened by conformance tests, and no credentials, network recipients or paid model calls are introduced.

## Contract and failure semantics

The local facade supports `remember`, `correct`, `forget`, `get`, `list`, `search` and `export`. It negotiates the existing strict descriptor and validates requests before execution. It validates actual results before returning them to the caller, including bounded record fields, revisions, payload-free mutation receipts, terminal tombstones and pagination. Unsupported operations are rejected explicitly rather than emulated.

Backend exceptions and invalid results must not expose arbitrary exception strings or backend payloads. The finite allowlist of domain rejections (including CAS conflicts and missing/forgotten records) is trusted only under the adapter contract that these exceptions certify no new mutation was committed. Their codes are preserved, with retry disabled; unknown codes and arbitrary messages are not passed through. A dishonest adapter that commits and then reports a whitelisted rejection violates this contract and cannot be detected by Python result validation. A write may already have committed when its acknowledgement is lost or invalid: `outcome_unknown` does **not** mean that no write occurred. The facade does not automatically retry it. Keep the original request ID and reconcile against the reviewed backend's durable receipt semantics; do not create a new mutation merely because an acknowledgement was rejected. A read-side failure is not evidence of data absence.

Explicit context assembly uses validated search results and a finite budget measured as characters in the compact `ensure_ascii=False` JSON `items` array. The envelope is excluded; this is not a byte, token or complete-context budget. It preserves whole records instead of silently truncating individual text values. It is not automatic recall, semantic search, factual validation or complete native context-budget integration.

## Behavioral conformance

The standard-library runner accepts a caller-owned factory for a fresh, explicitly isolated synthetic store. It exercises the same store across reopenings. Never point it at a production profile: the suite intentionally writes, corrects and forgets synthetic records. An isolation declaration is a caller obligation, not a sandbox that can contain a malicious factory.

The bundled SQLite adapter and an independent synthetic example exercise durable reopening, exact request replay, changed-request conflicts, stale CAS rejection, terminal forgetting, payload-free historical receipts, literal Chinese search and bounded result/context behavior. The example is educational, not a production adapter or a storage-security certification.

Passing these gates is bounded evidence about the exercised backend and fixture. It does not certify power-loss durability, adversarial Python isolation, encrypted storage, remote acknowledgements, source authenticity, migration, snapshots or production recall quality. Existing SQLite transaction, race, migration and private-storage tests remain required.

## Run the independent example

From the repository root, or with the installed runtime package on the import path, run this standard-library-only example. Each run creates and cleans up its own synthetic directory. A real adapter author supplies a separately reviewed opener and must not replace this temporary path with a production store.

```python
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from personal_agent.memory_conformance import run_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from personal_agent.memory_sdk_example import SyntheticMemoryAdapter

with TemporaryDirectory() as directory:
    @contextmanager
    def open_synthetic():
        backend = SyntheticMemoryAdapter(Path(directory))
        sdk = LocalMemorySDK(
            backend, LocalBinding("synthetic-example", "synthetic-session")
        )
        try:
            yield sdk
        finally:
            sdk.close()

    print(run_conformance(open_synthetic, isolated_synthetic=True))
```

## Optional durable progress extension

The additive API-v1 SDK operations `changes`, `consumer_get` and `consumer_advance` reuse the existing [37](37-durable-memory-progress.md) backend contract. CRUD-only adapters remain admissible and the existing `run_conformance` runner is unchanged. Missing advertised capabilities fail before dispatch, without fallback. Advancement requires `metadata_changes`, `durable_consumer_cursor`, durable writes, CAS and idempotency. The SDK additionally rejects a model-source binding before backend dispatch, including receipt replay. A trusted opener must still bind the actual backend correctly; this is not authentication.

Change pages contain only sequence, record ID, revision and operation, never historical payload, source labels, request keys or digests. Strict validation checks exact fields, integer types, increasing sequences, request bounds, watermark relationships, pagination and the fixed zero retention floor. Within one page, repeated record IDs must have increasing revisions and no event may follow that record’s terminal forget. No contiguous-sequence requirement or cross-call history cache is introduced. Consumer reads and receipts validate exact identifiers, registration/revision consistency, scope and requested advancement. A successful advance receipt is historical metadata, not necessarily the current cursor. Neither a cursor nor a validated reply proves native checkpoint completion, external publication, source coverage or malicious-adapter honesty.

Advancement is a write: an unexpected exception or malformed acknowledgement yields `outcome_unknown`, with no automatic retry. Retain the original request ID and reconcile with an exact replay plus `consumer_get`; replaying an older receipt must not rewind current progress. The trusted no-new-commit rejection allowlist includes sequence/future-watermark, non-advancing cursor, consumer quota and operator-scope failures. Arbitrary backend messages remain redacted.

Adapter authors may separately run `run_progress_conformance(factory, isolated_synthetic=True)` from `personal_agent.memory_conformance` on a **different fresh synthetic store**. This optional suite checks bounded/fixed-upper-bound pages through correction and forgetting, persisted cursors across reopen, exact retries, changed-key-payload conflicts, stale CAS, regressive/future rejection, independent consumers and old-receipt replay without rewind. It requires the optional capabilities; it does not silently skip unsupported adapters. The independent CRUD example does not claim progress support. SQLite-backed tests also inject malformed metadata/receipts and lost acknowledgements. These are offline observations, not production, power-loss or native lifecycle acceptance.

## Optional local metadata checkpoint extension

The additive API-v1 operations `checkpoint_create` (`expected_watermark`, `request_id`) and `checkpoint_status` (`checkpoint_id`) expose the existing [39](39-local-memory-checkpoints.md) local metadata contract through the SDK. Both require `local_metadata_checkpoint`; creation additionally requires `durable_write`, `cas` and `idempotency`. Missing capabilities fail before dispatch, without emulation. Creation requires an SDK binding with `explicit_local_operator` provenance before any backend dispatch, including exact receipt replay. A trusted opener must still bind the actual store correctly; the binding is not authentication. CRUD-only adapters and the existing CRUD/progress operations and runners remain unchanged.

Requests and replies use exact key sets. Validation rejects extra fields, invalid identifiers and types, out-of-bound counts or watermarks, inconsistent count relationships, malformed metadata hashes and request/receipt mismatches. Receipts contain only bounded record/event metadata, not record text, content hashes, source/session labels or arbitrary backend fields. Their fixed scope is `local_record_metadata_not_native_conversation`, with `restorable: false` and `native_checkpoint: false`. Status validates the nested receipt and its requested checkpoint ID, `is_current`, `current_watermark` and the fixed scope `metadata_comparison_at_this_read_snapshot_not_restore_or_authority`. Valid metadata is not proof of a dishonest adapter's integrity, payload correctness or native source coverage.

Creation fences the observed watermark. Empty stores can capture watermark zero; later correction or forgetting makes an earlier checkpoint stale. Exact replay returns the original historical receipt, not a new snapshot or a statement that it is current. Use `checkpoint_status` for freshness at that read snapshot; even a current result may become stale immediately afterward. Neither operation restores records or forgotten content. The existing bounded store scan and receipt quota still apply; this SDK extension adds no schema migration, pruning, automatic scheduling or retention mechanism.

Creation is a write. Unknown backend failures or malformed acknowledgements yield a redacted `outcome_unknown` with automatic retry disabled, because the checkpoint may already have committed. Retain the original `request_id` and unchanged `expected_watermark`: reconcile by explicitly replaying that exact key and payload, then inspect the returned checkpoint with `checkpoint_status`. Do not issue a new key merely because the acknowledgement was lost, and do not treat a failed status read as absence. Known domain rejections are preserved only under the reviewed adapter's no-new-commit contract; arbitrary backend messages are never returned.

Adapter authors can separately run `run_checkpoint_conformance(factory, isolated_synthetic=True)` from `personal_agent.memory_conformance` on a **different fresh synthetic store**, not a production profile or a store already used by the CRUD/progress suites. The optional runner exercises empty/current/stale checkpoints, correction and terminal forgetting, persistence across reopening, exact historical replay, changed-request conflicts and stale-watermark fencing. Unsupported checkpoint adapters fail explicitly rather than silently skipping the suite. The independent CRUD example above does not claim checkpoint support. This is isolated local offline conformance, not production acceptance or native checkpoint-v2 support. No native provider, network operation, shared REST contract or host lifecycle behavior changes.

## Remaining E2.6 work

The broader [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) remains open: complete versioned source/event and multi-kind contracts, remote reconciliation, replacement activation/migration, a reviewed loading/resource ABI and native lifecycle integration are not delivered by this local facade. The shared client contract in [82](82-shared-client-api.md) is unchanged; a Python SDK does not establish authenticated HTTP availability or cross-backend feature parity.
