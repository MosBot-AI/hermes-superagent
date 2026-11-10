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

## Remaining E2.6 work

The broader [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) remains open: complete versioned source/event and multi-kind contracts, remote reconciliation, replacement activation/migration, a reviewed loading/resource ABI and native lifecycle integration are not delivered by this local facade. The shared client contract in [82](82-shared-client-api.md) is unchanged; a Python SDK does not establish authenticated HTTP availability or cross-backend feature parity.
