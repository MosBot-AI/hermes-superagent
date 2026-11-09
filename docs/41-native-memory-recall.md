# 41. Optional Native Memory Recall Provider

English | [简体中文](41-native-memory-recall-zh.md)

Follow-on: [69](69-chinese-automatic-recall.md) updates the historical query description below with shared finite Chinese function-word splitting and conservative multi-term selection. Explicit retrieval and authority are unchanged; see its fixed evaluation and misses.

Alternative supported route: [49](49-session-memory-recall.md) adds separately enabled automatic recall inside the standalone plugin, without installing/selecting this provider. Both routes can overlap if independently enabled; neither performs extraction or checkpoint-v2.

Follow-on: [45](45-explicit-memory-expiry.md) requires schema v5 and excludes expired records from each fresh recall at its captured UTC wall-clock time. The read-only provider never migrates. A permitted store-opening command or already-activated model-tool operation can upgrade an owned old store before recall resumes; /personal-memory list is the recommended deliberate operator workflow. Evaluation time is sampled after actual SQLite snapshot acquisition, not before any lock wait. No provider selection/configuration changes are made. Expiry cannot retract a pack already in native history or model context.

Status: an optional real Hermes `MemoryProvider` now connects the existing local memory store to native prefetch and session lifecycle. It is **read-only for canonical records**, has no ingestion, and still advertises checkpoint API v1. Required native checkpoint-v2 remains unsupported. This is a tested offline implementation, not a live-provider acceptance result or production activation.

## 1. Explicit Selection and Data Disclosure

The standalone plugin does not import, register, select or install this provider. The separate optional packaging declaration supplies `personal-records = personal_agent.native_memory_provider:register` in the actual `hermes_agent.memory_providers` entry-point group. Each native load creates a fresh instance. A wheel built from this source contains the implementation and metadata; no package is installed by loading the existing standalone plugin. Build with `python scripts/build_native_memory_provider.py --output-dir /tmp/personal-provider-wheel`, using an existing setuptools installation. The script downloads/installs nothing and stages the build separately so the main plugin retains its zero-install declaration.

The installation owner must admit the reviewed package through their supported Hermes environment workflow. Do not inject packages into a PM-managed environment or disable existing isolation to expose this provider. Package installation and native provider selection are separate steps. This slice supports only an explicitly selected, file-configured, ordinary in-process trusted single-user profile on Linux. Native CLI/TUI/Desktop primary sessions are supported; remote messaging, cron, subagents, flush, hosted plugins, managed workers and non-file configuration backends are refused. A LOCAL/native label does not prove physical locality or a verified human identity. Any host-detected managed-policy scope is also refused, even when its config is empty or malformed. Scope presence is checked before and after reading saved user configuration and again before returning recall; raw user opt-in cannot override managed policy. This is separate from the package-manager `HERMES_MANAGED` setting.

The operator must deliberately choose this provider in Hermes's single external-provider slot. It cannot coexist as a second external provider or silently preserve another selected external provider. Existing users who keep another provider retain explicit personal-memory tools instead. Preserve all other configuration, including the selected model and credentials. The provider makes no model/API call itself, but recalled data becomes input to the session's configured model and may affect its normal token costs and retention.

Illustrative settings, to merge only after the explicit selection and data-sharing decision:

```json
{
  "memory": {
    "provider": "personal-records",
    "personal_records": {"recall_enabled": true, "max_chars": 6000, "max_records": 6}
  },
  "plugins": {
    "enabled": ["hermes-personal-agent"],
    "entries": {
      "hermes-personal-agent": {
        "settings": {"mode": "local_tasks", "local_conversation": true, "local_memory": true}
      }
    }
  }
}
```

The standalone plugin must remain enabled with its local-memory settings, and neither it nor `personal-records` may appear in `plugins.disabled`. Explicit opt-in is checked on every new recall admission and again after reading. This is profile-wide automatic read permission for supported primary local sessions, distinct from the 30-minute model-tool activation. It creates no new memory write permission. Restart the native agent after installation/selection; existing instances are not rebound to a different profile.

## 2. Bounded Fresh Recall

Prefetch reads the current session query, extracts at most eight distinct literal word/script chunks of at most 128 characters, and runs the existing bounded recall operation. It skips slash commands, host-classified trivial prompts, invalid control characters and queries over 2,048 characters. Chunks are case-sensitive; Chinese punctuation and whitespace create boundaries, but arbitrary Chinese sentences are not semantically segmented. This is deterministic literal retrieval, not a semantic-recall quality claim.

Each prefetch opens and closes its own connection. No payload cache, background prefetch result or transcript buffer is retained by the provider. The existing ranker selects current active records, keeping revisions and editing-route labels. The returned JSON identifies the text as untrusted stored evidence, not instructions, verified facts, grants or task truth. The complete returned ASCII JSON is bounded by `max_chars` (2,048–12,000, default 6,000), with at most `max_records` (1–20, default 6). Whole records are omitted rather than cut; metadata reports omitted matches. If nothing fits, retrieval is unavailable or admission fails, no context is returned.

**Fresh recall is not transcript erasure.** The pinned host stores successful prefetch content in native transcript `api_content` and replays prior `api_content` on later model requests. A correction, forget, disable, session switch or provider removal prevents new unsupported recall but cannot remove context already delivered or persisted by the host. Starting a new session does not delete older history, exports, backups or model-provider copies. Any deletion of those destinations is separate authorized work. Do not promise that forgetting a local record makes every future prompt free of its prior text.

## 3. Session, Profile and Shutdown Contract

Initialization binds exactly one host-provided profile and nonempty session ID. It requires `agent_context: primary` and platform `cli`, `tui` or `desktop`; missing context fails closed. Reinitialization is refused, including after shutdown. Current native profile context must match the bound home on every read. The real Hermes manager also applies its caller-profile and single-external-provider checks.

Prefetch requires the exact current session ID. Native `on_session_switch` changes only the session binding and clears the recall count. Unsupported switches refuse subsequent recall. A lock orders switch/shutdown against already admitted bounded reads. Shutdown is terminal and releases the binding; no provider-owned threads, open database handles or write queues remain to drain. Existing host-owned background calls can still invoke no-op hooks, but cannot make the closed instance read again.

`sync_turn`, session-end extraction, delegation, built-in-memory mirroring and background queue-prefetch remain no-ops. They do not copy transcripts, create facts, advance consumer cursors or create metadata checkpoints. `on_pre_compress` remains best-effort v1 with no durable conversation coverage. The actual native manager still raises when strict checkpoint-v2 is required. The local [metadata checkpoint](39-local-memory-checkpoints.md) must not be substituted for that guarantee.

## 4. Canonical Read-Only Storage and Limits

The reader uses the existing fixed profile-local path with private directory/file checks and opens SQLite with `mode=ro` plus `query_only`. It requires the exact current owned schema and namespace. Missing stores, old schemas, unsafe paths, observed sidecars and WAL mode are refused without creation, migration, permissions repair or fallback. Initialize/upgrade memory explicitly through the existing operator workflow before native recall. Canonical write operations and write capabilities are unavailable through this reader.

The supported store uses SQLite rollback journaling. The reader checks its header before opening and rechecks journal mode under the database read transaction before reading records. An unrelated process can race the preliminary check by switching the database to WAL. SQLite may create or update WAL/shared-memory sidecars before the later rejection, even with `mode=ro`. Therefore this is a **canonical-read-only contract, not a strict filesystem/VFS sandbox against unrelated same-UID code**. The plugin never deletes those sidecars to hide the race. Do not externally change the journal mode of the live store.

Normal record correction/forgetting is ordered by SQLite's read snapshot. An already admitted returned pack may become historical immediately after its read transaction ends. Writer contention or an observed journal can temporarily suppress recall rather than use stale cached data. This does not secure other native tools, prove record truth or solve restoration of an old database backup.

## 5. Verification and Remaining Work

Synthetic unit tests cover opt-in/disable/revocation, profile/session mismatch, non-primary refusal, shutdown, byte budgets, literal queries, injection-as-data, correction/forget freshness, read-only operation denial, missing stores, unsafe files, old schemas and the external WAL-transition race. Native contracts use the real entry-point loader and `MemoryManager`, with only a synthetic entry-point inventory supplied. They verify fresh instances, the external-provider slot, prefetch/sync/switch/shutdown, profile refusal, unchanged canonical DB/configuration and strict checkpoint failure. A locally built wheel is checked separately; it is not installed into a live Hermes environment.

No live LLM, actual personal data, Gateway listener, credentials, production profile or remote write is used. Automatic ingestion, conversation-evidence checkpoints, provider setup UI, hosted/managed compatibility, semantic Chinese recall evaluation and permissioned live acceptance remain open. All real-provider acceptance must retain the user's selected model/provider rather than silently changing it.

Pinned source evidence: [provider ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_provider.py), [loader](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/memory/__init__.py), [manager and checkpoint gate](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py), and [prefetch persistence/replay](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_context.py#L1030-L1072).

Follow-on: [reviewed candidates](50-reviewed-memory-candidates.md) add an independently selected draft workflow, not automatic canonical ingestion. Current writable storage upgrades to schema v6; read-only recall never migrates v1–v5 stores and remains unavailable until an authorized normal store opening.
