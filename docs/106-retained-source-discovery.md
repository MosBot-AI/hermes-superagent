# 106. Retained-source recovery discovery

English | [简体中文](106-retained-source-discovery-zh.md)

## Implemented boundary

[Issue #153](https://github.com/MosBot-AI/hermes-superagent/issues/153) adds bounded operator discovery of durable retained-source decisions. Operators no longer need to remember a request key, digest or consumer before finding an interrupted attempt. The native LOCAL workbench and optional API-v1 SDK operation use canonical metadata only. This is production-package code with synthetic checks, not deployment, live personal-data acceptance, native checkpoint-v2 or complete E2.6/E2.8 acceptance.

The existing `mode: local_tasks`, `local_conversation: true`, `local_memory: true`, admitted profile and exact current Gateway-backed LOCAL session gates apply. Foreign, remote and model entry paths remain denied. There is no automatic capture, replay, discard, provider switch, REST change, source lookup or general canonical-record provenance expansion.

## Discover, inspect, then deliberately act

```text
/personal-memory source-discover
/personal-memory --json source-discover --state all --limit 20
/personal-memory source-discover --state accepted --consumer-id reviewed
```

The default filter is `pending`. Explicit `--state` values are `pending`, `accepted`, `discarded` and `all`; `--consumer-id` is an exact optional filter. The consumer format is unchanged: a lowercase initial letter followed by lowercase letters, digits, `_`, `.` or `-`, at most 64 characters. A missing canonical store returns `memory_store_missing`, not an empty successful result. Existing-only read-only opening refuses older schemas without migration, and never opens native text.

Each item contains `query.request_id` and normalized `query.expected_digest`, consumer ID, source sequence, historical decision state, historical accepted record receipt or null, separate current record ID/revision/status/expired metadata or null, and suppression state. It contains no canonical/source text, topic, session label, source identity, fingerprint or native provenance. These request identities and record identifiers still require private handling.

Use the returned query with the existing exact-key commands:

```text
/personal-memory source-status --expected-digest=DIGEST -- REQUEST_KEY
/personal-memory source-discard --expected-digest=DIGEST -- REQUEST_KEY
```

Human output supplies a safely quoted exact status command for each item, including keys beginning with `-`. Discovery never emits an automatic discard or repeats a write. Inspect the current decision before deliberately discarding an unresolved pending slot. Discard cannot undo an accepted record; canonical forget remains the operation for that purpose. The exact-key operation rechecks identity and state at its own execution, without treating the discovery token as authorization.

Terminal decisions are historical. An accepted receipt can still describe revision 1 and `active` while current metadata reports correction, expiry or terminal forgetting. Pending decisions do not automatically expire. Source loss does not erase decisions, restore canonical payload or relax suppression. Existing source lifecycle, source cursor, suppression, expiry, repack and retry semantics from [96](96-retained-source-acceptance.md), [98](98-observed-source-retention.md) and [104](104-retained-source-expiry.md) remain unchanged.

## Bounded snapshot-fenced pages

The default page size is 20, with `limit` from 1 through 50. The existing store bounds remain 1,000 decisions and 64 consumers. Ordering is ascending `(consumer_id, source_sequence)`, identified by `order: consumer_id_source_sequence`. A page exposes `total`, `offset`, `next_offset`, `snapshot`, `evaluated_at`, namespace and the normalized filters. The compact JSON data budget is 65,536 characters; field and item bounds apply independently. This is not a model token budget.

The first request uses offset zero. To continue, preserve the filters and page size, and use the returned `next_offset` and `snapshot`:

```text
/personal-memory source-discover --state all --limit 20 --offset 20 --expected-snapshot HASH
```

Replace `20` and `HASH` with the actual returned next offset and token; human output prints the exact next-page command. Offsets must be nonnegative page-size multiples, no greater than 1,000, and nonzero offsets must be inside the current result set. Nonzero offsets require a valid expected snapshot. An exhausted page has `next_offset: null`; an empty first page is valid. There is no silent restart, fallback or cursor advancement.

The digest binds the namespace, filters, ordering, page size and the bounded summaries of **all** retained decisions, including current revision/status/expired and suppression. A change elsewhere in the same namespace's retained decisions can conservatively invalidate continuation, even outside the selected filter. Staging, acceptance, discard, canonical correction/forgetting and relevant expiry transitions invalidate stale pages with `source_discovery_changed`. Evaluation wall-clock time is excluded, so passing seconds alone does not invalidate a page. Repack preserving logical metadata preserves the token. Moving to another namespace does not.

A token only compares read snapshots. It is not authority, a reservation, a cross-store transaction, proof of source availability or a fence against future writes. Discovery and absence describe only the inspected snapshot: an unobserved writer may still commit later. Do not replace an uncertain attempt's request key merely because it was absent. On changed discovery, start at offset zero and review the fresh results before acting.

## SDK and read-only contract

`source_discover` requires the new optional `retained_source_discovery` capability plus `explicit_records`. Existing adapters are not assumed to implement it and remain compatible. SDK requests use the command field names with underscores, defaulting to `{state: pending, consumer_id: null, limit: 20, offset: 0, expected_snapshot: null}`. Unknown fields, invalid types, unsafe limits and missing continuation tokens are rejected before dispatch. Activated-session-model bindings refuse before dispatch even when capability is advertised.

Strict result validation checks exact fields, namespace binding, filters, pagination arithmetic, item order and uniqueness, historical receipt relationships, current metadata, suppression consistency and output bounds. Malformed replies yield `invalid_result`; unexpected read failures are redacted `backend_failure`, not evidence of absence. `source_discovery_changed` and `invalid_cursor` remain explicit refusal codes. Reviewed Python adapters are trusted code; validation is not a sandbox or proof that a dishonest adapter performed no writes.

The SQLite operation uses one read transaction, existing bounded canonical/retained metadata integrity checks and bounded SQL string projections. It performs no creation, migration, payload validation reads, source/native store opening, canonical mutation or cursor advancement. The native route uses the existing-only read-only opener. SDK construction retains its existing bounded `export` binding admission, which can read canonical payload: the metadata-only guarantee applies to the discovery operation, **not the entire SDK lifetime**. No alternate SDK initializer or schema change is introduced.

## Verification and limits

Synthetic tests exercise exact page boundaries through the 1,000-decision bound, filters and token tampering, namespace binding, separate-connection changes, expiry crossings, malformed/oversized metadata and SDK replies, old-schema refusal, missing stores, safe command quoting and SQL authorizers that deny payload reads/writes. Fresh-process tests discover unknown identities before and after normal/interrupted repack, then inspect and explicitly discard pending decisions and verify exact-source anti-resurrection.

Native contracts run against Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, with synthetic profiles and no model/provider calls. They cover disabled/foreign/remote admission, actual source loss and reload recovery, explicit pending discard, and human/JSON entry. Use the [development checks](../README.md#development-checks) for the pinned-host setup. Focused suites include `test_retained_source_discovery.py`, `test_source_discovery_recovery.py`, `test_source_discovery_commands.py` and `tests/contracts/test_source_discovery.py`. Exact-source executed checks, independent review and package evidence belong to the PR; test implementation alone is not production acceptance. Frozen recall fixtures and semantics are unchanged.


## Record origin inspection

[108](108-memory-record-origins.md) adds explicit local-operator `record_origin` metadata inspection, separating historical acceptance, current state and latest editing route. The optional capability requires `explicit_records`; shared REST, schema and recall semantics are unchanged. SDK export admission can still read payload; metadata-only applies to this operation and the native readonly path.
