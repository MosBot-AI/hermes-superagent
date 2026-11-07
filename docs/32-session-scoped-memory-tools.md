# 32. Session-Scoped Memory Model Tools

English | [简体中文](32-session-scoped-memory-tools-zh.md)

Follow-on: [49](49-session-memory-recall.md) adds separately enabled session automatic recall through the existing turn hook. Ordinary tool activation still does not enable it; no extraction or provider replacement is added.

Follow-on: [45](45-explicit-memory-expiry.md) adds optional expires_at to remember/correct and explicit include_expired list/search inspection. Omission preserves expiry on correct; null clears it. Record expiry is separate from the tool activation TTL and does not grant access or erase prior model context.

Status: implemented opt-in model-tool access to the [local records](31-explicit-local-memory.md), through the same pinned in-process native turn boundaries as [task tools](29-session-scoped-task-tools.md). Real-provider natural-language acceptance is pending. This does not implement the native MemoryProvider bridge, automatic extraction/prefetch, embeddings or third-party backend loading in [30](30-pluggable-memory-contracts.md).

## 1. Explicit Configuration and Separate Activation

In the tested trusted single-user profile, preserve existing configuration and explicitly enable:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_memory: true
        memory_model_tools: true
```

`memory_model_tools` defaults to `false`, requires the other three settings and accepts only a boolean. `local_model_tools` is a separate task-tool option and is not required here. Loading registers `personal_memory_read` and `personal_memory_write` in the existing `personal_agent` toolset, without opening memory storage or activating a session. Select that toolset using the host's normal controls and reload/start the session as required.

Use the native session command:

```text
/personal-memory-tools enable-read
/personal-memory-tools enable-write
/personal-memory-tools status
/personal-memory-tools disable
```

Read access allows bounded local memory data into this session's configured model. Write access additionally permits local remember/correct/forget operations. Both last 30 minutes, with at most 64 activated sessions per loaded memory-tool instance. Status does not extend expiry. Enabling read after write downgrades access. State is in memory, keyed by exact profile/session/route, and is cleared by reload, unload or process restart.

**Task and memory permissions are independent.** `/personal-tools` cannot grant memory access; `/personal-memory-tools` cannot grant task access. Disabling one leaves the other's independently selected activation unchanged. Neither activation grants remote authority or changes other Hermes tools.

## 2. Natural-Language Path and Tool Contract

After write activation, ask the existing model to remember a preference, find it, correct it and forget it. For example: “Remember that I prefer concise Chinese summaries,” then “Find my summary preference.” These are operator requests to the configured model, not tested claims that every model will choose the correct tool. Inspect the returned receipt and read-back instead of accepting a verbal “I remembered it.”

- `personal_memory_read`: `list`, `show`, `search`, `recall`. There is no model-facing export operation. Pages are at most 50 records; query text is at most 128 characters and literal/case-sensitive, not semantic search.
- `personal_memory_write`: `remember`, `correct`, `forget`. Every mutation requires a stable `request_id`. Corrections/forgetting require the actual record ID and current `expected_revision` from a read; correction changes content and/or topic.
- Unknown, irrelevant, owner/profile/session/source/approval fields are rejected. The model cannot choose the storage path or claim an operator source. Contents remain bounded to 2,048 characters and topics to 128.
- Schemas instruct the model to perform explicitly requested changes, not infer lasting preferences or grants from arbitrary text. The admission boundary is nevertheless the activated session, not deterministic proof of each fresh human instruction.

Illustrative synthetic call:

```json
{"action":"remember","content":"Use concise Chinese summaries","topic":"preference","request_id":"summary-preference-1"}
```

The response envelope is `personal.session-memory-tools.v1`, with status/data/error, request ID and replay flag. Mutation receipts are metadata-only historical evidence. Replaying an old successful remember after forgetting returns its old receipt but does not restore content; read current state before describing it. Changed payload under the same key conflicts. A new explicit key can create a new record. There are no automatic retries or claim that forgetting is global erasure.

## 3. Model Provenance and Storage Upgrade

Model-created/corrected records use `source: activated_session_model`, while direct `/personal-memory` edits use `explicit_local_operator`. This is the **latest editing route**, not a verified original speaker or independent fact-check. Model-written records cannot become owner permissions merely by saying “the user approved.” Read results expose the source distinction. Replaying an old receipt does not rewrite the current record or its source.

The adapter, not tool arguments, binds `source_kind` when opening storage. The exact owned memory schema upgrades atomically from v1 to v2 under the writer transaction, after namespace/schema/application checks. It preserves record IDs, revisions, tombstones, ordering high-water marks, event rows and exact receipt bytes/digests. Unknown schemas, foreign databases or moved namespaces fail rather than being adopted. This changes only the plugin memory DB, not native memory or task DBs.

The first supported open may migrate a v1 DB, including a read command. Back up the private plugin data before upgrading; earlier code rejects v2 and must not be used as a data downgrade. Recovery/migration across profiles and full portable restore remain unsupported. Do not roll back by replacing current data with an old backup that revives forgotten content.

## 4. Admission, Revocation and Privacy

Every tool call, including direct registry dispatch, checks the actual pinned host active turn, dispatcher task/session IDs, profile lease, supported `cli`/`tui`/`desktop` platform, no parent/delegated/cron context, exact bound route, current configuration and unexpired memory activation. Tool schema visibility is not permission. A copied session ID or source object without the live context cannot activate or access storage.

The shared mechanism retains the lock order: actual turn finalization lock, then the feature's activation lock, held through the bounded storage operation. Disable or unload blocks future admission, while a previously admitted transaction may finish. Expiry similarly affects future admission, not rollback. Task and memory activation objects and locks are distinct. Configuration reads are not a promise of instant cross-process policy propagation; reload using the host workflow.

**All model activity and already admitted controllers in an activated session share access.** This is not per-message human-intent verification, protection against arbitrary same-process code, or a sandbox for other Hermes tools. Prompt injection or a poor model decision inside that scope is a reason to use read-only activation or direct commands, not a reason to claim the plugin proved user intent.

Memory content and source/session references returned by these tools enter the existing configured model context and normal host history. Ordinary provider costs may apply. No second model or provider switch is introduced. Forget clears the canonical payload and future plugin retrieval but cannot retract context already sent, host history, provider retention, backups or delivered exports. Retained digests/IDs are still potentially personal metadata. Only activate access when that model and session are permitted to receive these records.

## 5. Unsupported Modes and Verification

Only the tested ordinary native in-process mode is supported. Managed workers and hosted plugins do not inherit the parent's process-local activation/turn context. Delegated/cron/remote-messaging paths and missing-context code-execution RPC remain rejected. Do not disable isolation to use this feature. Profiles remain storage/configuration partitions, not human identities; do not deploy this local mode on an exposed or shared multiuser gateway.

Tests use synthetic records and temporary profiles, real pinned slash/SessionAuthority admission, TurnFacade lifecycle and `model_tools.handle_function_call`, without a live model. They cover independent task/memory activation, read/write downgrade, TTL/session/route/profile mismatch, finalization races, disable/unload/reload, source labels, validation, CAS, replay after forgetting, exact v1 migration and rollback. Existing task-tool and direct memory-command regressions also pass. The historically restricted nine identity socket cases are not rerun.

Real natural-language acceptance still requires an eligible session, an explicitly selected provider/model and safe credential configuration if needed. No API Key, credential save, paid request or production deployment is implied by these tests. Verify “remember → query → correct → forget → denied after disable” with synthetic data before real personal records. This advances local E2.6/E2.7; E0.9's complete native-provider matrix and E2.8 automatic lifecycle integration remain separate gates.

[36](36-bounded-memory-recall.md) adds multi-keyword literal ranking, whole-record budgets and current-snapshot rules for `recall`; it retains separate memory activation and does not enable automatic recall.

Storage follow-on: [37](37-durable-memory-progress.md) advances current stores from v1/v2 to v3 with atomic consumer-progress tables. The v1→v2 provenance migration above remains part of that transaction; earlier builds reject v3. No new model actions or native checkpoint guarantee are added.
