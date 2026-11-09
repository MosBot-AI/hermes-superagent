# 31. Explicit Local Memory Records

English | [简体中文](31-explicit-local-memory-zh.md)

Follow-on: [45](45-explicit-memory-expiry.md) adds explicit UTC expiry and schema v5. Correction can also set or clear expiry; ordinary list/search exclude expired records, while show/export retain inspection access. Expiry is not forgetting.

Follow-on: [32](32-session-scoped-memory-tools.md) adds separately configured and activated model access, without changing the direct-command consent boundary below. Storage now uses schema v5; durable progress was added in [37](37-durable-memory-progress.md), and distinguishes direct operator edits from activated model edits; source is the latest editing route. The original direct-command feature alone adds no model access.

Status: an implemented, explicitly enabled local precursor of E2.6/E2.7, not completion of the [full memory design](30-pluggable-memory-contracts.md). Users can save, inspect, correct and forget short records inside an existing native Hermes session. This slice adds no memory model tool, automatic recall/extraction, native MemoryProvider bridge, package loader, Markdown projection, vector service or remote account.

Current follow-on: [explicit multi-term FTS search](66-local-memory-full-text-search.md) adds schema v7 and transactional indexing. The literal-search behavior described here is unchanged.


## 1. Enable the Narrow Local Mode

Use the pinned Hermes version and an isolated trusted single-user profile, as described in [28](28-profile-first-local-conversations.md). Preserve all other settings and explicitly add:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_memory: true
```

`local_memory` defaults to `false`, accepts only a boolean and requires the other two settings. Reload through the host after configuration changes. Loading or requesting help creates no memory database. The feature registers `/personal-memory`, not a model tool or background hook. It leaves native provider configuration and MEMORY.md/USER.md unchanged. The existing task model tools, if separately enabled, do not gain memory access.

Supported scope is the tested native in-process LOCAL command route on POSIX storage. Existing host-authorized owner/operator controllers share access. Profile scope is a storage boundary, not an authenticated person, and LOCAL does not prove physical locality. Do not enable on an exposed or multiuser deployment. Managed/hosted-plugin and remote messaging modes are not certified; do not disable existing isolation to enable this feature.

## 2. Use It in a Native Conversation

Examples use synthetic information. Substitute the returned record ID and current revision in later commands:

```text
/personal-memory remember "Use concise Chinese summaries" --topic preference --request-id preference-1
/personal-memory list --limit 10
/personal-memory search "Chinese"
/personal-memory show RECORD_ID
/personal-memory correct RECORD_ID --text "Use concise bilingual summaries" --expected-revision 1 --request-id preference-2
/personal-memory forget RECORD_ID --expected-revision 2 --request-id preference-3
/personal-memory export --limit 10
```

Use POSIX quotes, including on native desktop. `correct` can change content with `--text`, topic with `--topic`, or both. `list`, `search` and `export` accept `--after RECORD_ID` from `next_cursor`. Search is literal, case-sensitive content/topic substring matching, including short Chinese strings; `%` and `_` have no wildcard meaning. It is not semantic retrieval or fuzzy person matching.

Every mutation uses a stable `request_id`; an omitted key is generated and echoed. An uncertain outcome should be inspected or retried manually using the same key and identical payload. A different key can create another record. Changing the payload under an old key fails. Corrections and forgetting require the latest `expected_revision`; read before retrying a revision conflict. Commands never silently retry.

Results use `personal.local-memory.v1` with `status`, `data`, `replayed`, `request_id` and a redacted `error`. Mutation receipts contain record ID, revision, operation, status and event sequence, not private content. An old receipt is historical, not proof of current state; `show` reads current state. After forgetting, `show` returns a tombstone with null content/topic/source/session fields, while normal lists/search hide the record. No correction can revive that ID. An explicit new `remember` can create a separate record; this slice has no automatic re-extraction engine.

## 3. Truth and Privacy Boundaries

A record saved through the direct command is an **explicit local operator edit**, not a verified external fact or proof of the human author. Its source tag is `explicit_local_operator` and its session reference records the admitted route's session. No invented owner ID, transcript quote or native message ID is attached. Notes cannot grant permissions, complete tasks or prove an external action succeeded.

The command's own handler makes no model request or automatic prompt injection. However, commands and results may be retained in normal host session history and later included in that session's configured model context. Saving locally is not a promise that history never reaches the user's model provider. Do not use this plaintext store for passwords, tokens or payment credentials.

`forget` atomically replaces canonical payload/source/session fields with a terminal tombstone. Retained metadata in records/receipts/events includes IDs, revisions, operation keys, digests and timestamps for replay and ordering. Those identifiers/digests are still potentially personal metadata. SQLite secure-delete and rollback journaling are not encryption or guaranteed physical-media erasure. Previously returned text, host history, backups and exported pages are not erased by this operation; it must not be described as “deleted everywhere.”

There are no generated Markdown or external indexes in this slice, so no asynchronous derivative can republish deleted content. Their required publication fences remain future gates in [30](30-pluggable-memory-contracts.md). A read already admitted before forgetting may finish; a later read observes the tombstone. Unload waits for an admitted local command, then permanently rejects retained callbacks. Reload applies configuration consistently rather than claiming immediate policy revocation from a frozen profile snapshot.

## 4. Storage, Limits and the Adapter Seam

Storage is `plugin-data/hermes-personal-agent/memory/records.sqlite3` under the registered current profile. Namespace binding derives from that profile path and is not owner authentication. Moving/copying to another path fails namespace validation; there is no supported cross-profile migration yet. Private POSIX file/sidecar checks reject unsafe links, shared files and writable parent directories without repairing existing data. Unsupported platforms fail closed. This is not protection against arbitrary malicious code running as the same OS user.

SQLite is the sole authority here. Exact owned schema/version checks, transactions, revision checks, atomic receipts and terminal tombstones protect the supported operations. Inputs are bounded to 2,048 content characters, 128 topic/query characters, 50 records per page, 1,000 total records including tombstones, and 10,000 nonterminal mutations. Up to one terminal forget per record remains available after the edit quota; replay does not consume capacity. Quota exhaustion is an explicit error, not an automatic purge or backend switch. Literal scanning is bounded by that record cap; no FTS/CJK tokenizer quality is claimed.

The small internal `MemoryBackend` protocol exposes `describe`, `execute` and `close`; `MemoryService` validates the operation before dispatch. SQLite connection setup belongs only to the bundled adapter. This isolates the command from its store and provides a tested replaceability seam, **not the full public SDK or dynamic third-party package loading** from [30](30-pluggable-memory-contracts.md). Unsupported lifecycle/checkpoint/import/change-feed operations return a typed error. No native provider is discovered, installed or selected.

`export` returns a bounded, versioned `personal.memory.record_page.v1` page of current records and tombstones with a committed watermark. Each page is an independent snapshot; concurrent changes may prevent a consistent multi-page export. It explicitly returns `restorable: false`, omits receipt/event history, writes no file and cannot be imported as a portable backup. Full consistent export, migration, retention/metadata cleanup and adapter selection remain planned.

## 5. Verification and Remaining Work

Unit tests cover input bounds, Unicode/literal search, receipts, revision races, rollback, quotas, forgotten payloads, schema/namespace isolation, private paths and configuration/unload rejection. Native contracts use the actual pinned plugin loader and SessionAuthority/LOCAL command dispatch with synthetic profiles, including preexisting native-memory configuration preservation, separate profiles, operator admission, invalid/disabled settings, reload and retained callbacks.

These checks use no real model, API Key, microphone, listener or personal accounts. They do not certify a live GUI/network transport, arbitrary custom adapters, MemoryProvider lifecycle, recall quality or remote identity. The historically restricted identity socket tests are untouched. Native command preservation does not complete E0.9's full provider lifecycle/checkpoint matrix.

Next: complete the versioned SDK and conformance gates, bounded retrieval/context and user-reviewed candidate workflows, then opt-in native lifecycle integration. Markdown projections, full export/import and automatic memory exposure must pass their own deletion, source, privacy and recovery gates before enablement. E2.6/E2.7 are In Progress; the full memory system is not Done.
