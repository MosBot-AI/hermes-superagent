# 16. Opt-in Local Task Inbox

English | [简体中文](16-local-task-inbox-zh.md)

**Implemented development slice, not the complete personal agent.** A trusted local operator can capture, inspect, edit, complete and cancel plugin-owned tasks through the real Hermes CLI. Records survive process restarts. No model, HTTP, personal-data slash-command, Bot binding, scheduler, native Kanban or outbound-action surface is enabled by this slice.

The tested Hermes baseline remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, Python 3.14.9. This is a narrow local precursor to E2.1, not completion of E1, E2 or M1. The [full roadmap](08-roadmap-and-acceptance.md) and controlled-write release gate remain in force.

Date-only deadlines and agenda are now available as a compatible extension; see [17](17-local-task-agenda.md) for commands, migration and legacy receipt semantics.

## 1. Scope and Trust Boundary

- Default `mode: read_only` still refuses task commands before opening plugin storage. Status and coverage do not open task storage in either mode.
- Explicit `mode: local_tasks` enables only local CLI operations on this plugin's own inbox. It does not change delegation, credentials, tool permissions or native project/task/schedule state.
- The only registered model tool remains `personal_agent_status`. It reports capability/configuration without reading task records. There is no task-data tool, HTTP route, personal-data conversational slash command or automatic capture from messages. The separate access diagnostic does not read this inbox.
- This trusts the local OS account and the selected Hermes profile. A CLI command is not cryptographic proof of a human owner. Profile labels, task IDs and `source: local_cli` are not authorization credentials.
- It does not contain shell/Python tools, other plugins, other processes running as the same UID, or arbitrary filesystem replacement races. It is not a substitute for E1 identity/action authorization. Do not expose the CLI through an untrusted remote executor.
- Personal task content is plaintext in local storage and command output. Command-line arguments may appear in shell history/process listings. Do not put credentials or secrets in task fields. Encryption, secure input UI, export/forget/backup policy and remote identity are not implemented here.

The first supported storage platform is POSIX with `O_NOFOLLOW`. Linux is tested. macOS is not yet device-certified, and Windows storage is explicitly refused; diagnostics remain available. Windows ignore-file support does not imply runtime storage support.

## 2. Enable and Use

Use an isolated, compatibility-tested Hermes profile first, following [the setup instructions](../README.md). Preserve all existing plugin settings when adding this explicit opt-in:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
```

The CLI still requires the pinned host's `in_process` plugin mode. Host isolation does not support `register_cli_command`; do not turn an existing isolation setting off merely for this feature. Changing `mode` does not install a plugin or imply that another host version is compatible.

```bash
hermes personal-agent tasks capture \
  --title "Prepare the weekly review" \
  --details "Check unresolved commitments and attach sources." \
  --request-id review-capture-001
hermes personal-agent tasks list --state captured --limit 20
```

Copy the returned UUID and its current revision. The examples below use shell placeholders; replace them with that actual task ID/revision before running:

```bash
TASK_ID="UUID returned by capture"
hermes personal-agent tasks show "$TASK_ID"
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 1 --title "Prepare and check the weekly review" \
  --request-id review-edit-001
hermes personal-agent tasks complete "$TASK_ID" \
  --expected-revision 2 --note "Reviewed manually by the local operator." \
  --request-id review-complete-001
hermes personal-agent tasks list --state done
```

`cancel` uses the same revision, request-ID and note parameters as `complete`. `update` accepts a title, details, or both; an explicit empty details string clears details. These commands never launch a worker or send a reminder. Completion records the local operator's assertion, not evidence that an external action or native worker succeeded.

## 3. Command Contract

| Command | Required input | Result |
|---|---|---|
| `tasks capture` | title, request-id; optional details | New UUID task in `captured`, revision 1 |
| `tasks list` | Optional state, limit and after | Bounded newest-first page with next_cursor/has_more |
| `tasks show` | Task UUID | Current task, including terminal states |
| `tasks update` | UUID, expected-revision, request-id, title and/or details | Edited captured task, revision incremented |
| `tasks complete` | UUID, expected-revision, request-id, note | Task marked done by explicit local command |
| `tasks cancel` | UUID, expected-revision, request-id, note | Task marked cancelled by explicit local command |

Validation happens before storage opens. Unknown operations/fields, invalid canonical UUID4 IDs, boolean revisions, empty updates, unsafe controls and out-of-range values are refused. Titles are 1–240 characters and single-line; details are at most 5,000 characters; resolution notes are 1–2,000. Details/notes permit newline and tab but reject other control/format characters. Request IDs are 1–128 ASCII letters, digits, periods, underscores or hyphens.

List states are `captured` (default), `done`, `cancelled` or `all`; limit defaults to 20 and must be 1–100. Pass the returned `next_cursor` UUID as `--after`. It is local keyset pagination, not a durable change feed or consistent cross-page snapshot. A task from another profile is not a valid cursor in this database.

All successful command results have `schema_version: personal.local-tasks.v1`, `status: ok`, `scope: trusted_local_cli_only`, `data`, `replayed` and `error: null`. List `data` contains items, next_cursor and has_more. A task contains id, title, details, state, revision, created_at, updated_at, resolved_at, resolution_note, source and nullable due_date in current views. Event times are UTC; due_date is a calendar date with no inferred timezone. Historical receipts can lack due_date; see [17](17-local-task-agenda.md).

```json
{
  "schema_version":"personal.local-tasks.v1",
  "status":"error",
  "scope":"trusted_local_cli_only",
  "data":null,
  "replayed":false,
  "error":{"code":"revision_conflict","retryable":false}
}
```

CLI exit status is 0 for success, 1 for a handled operation failure and 2 for argparse usage errors. Error results do not echo task text, SQL or private paths. Stable codes include local_tasks_disabled, profile_context_changed, invalid_request, not_found, invalid_cursor, revision_conflict, terminal_state, idempotency_conflict, unsafe_storage_file, unsafe_storage_path, foreign_database and unsupported_schema. Unexpected host/filesystem failures become local_tasks_unavailable; there is no silent reset or fallback to another store.

## 4. Transactions, Replay and Lifecycle

The inbox is a local presentation record with `captured → done / cancelled`; terminal tasks cannot be edited or reopened. This is not the entire domain Task state machine or native Kanban execution lifecycle. A future integration needs explicit mapping/migration rather than assuming these records are already dispatched tasks.

Every mutation requires a stable request ID. The database stores a digest of the operation and validated payload, plus its result receipt, in the same `BEGIN IMMEDIATE` transaction as the task and minimal event record. Receipt replay is checked before a now-old resource revision would be rejected. Different content/operation under the same request ID gives idempotency_conflict. Two concurrent identical requests allocate only one task/transition.

**Replay returns the original receipt, not necessarily the current task.** It has `replayed: true`; use `tasks show` for current state. For example, replaying capture after completion returns the original revision-1 capture receipt, while show returns the done task. Never present a replayed receipt as a fresh read.

Changes compare expected_revision under the same transaction and increment it once. A competing edit returns revision_conflict. On transaction failure, task, event and receipt roll back together. A lost CLI response can be retried with the same request ID/payload; using a new key means a new requested operation and is not a recovery mechanism. There is no distributed exactly-once claim because this slice performs no remote effect.

Receipts are retained locally without automatic expiration in this first schema. No delete, automatic cleanup, backup/restore or forgetting command is added. Schema upgrades are covered separately in [17](17-local-task-agenda.md). This is a development limitation, not a complete personal-data retention policy.

## 5. Storage and Profile Safety

Use the documented `plugins.plugin_storage.plugin_data_dir()` to resolve the current profile's plugin data root [S1, S2], then open only this plugin's `tasks.sqlite3` with Python SQLite. Runtime data is never written into the install tree or host Projects/Kanban/cron databases. First use in local_tasks mode, including a list, initializes this own store. Default diagnostics and read_only mode do not.

The handler captures the resolved profile at registration and checks it again before task access. It also checks that the profile still exists **before** calling the host configuration reader, because that reader can recreate a deleted profile. Mode is read again per task command. A changed profile, invalid config, or switch back to read_only refuses the next command. This command gate is not a transactional hard-revocation service for arbitrary concurrent OS activity.

The main file is created with mode 0600. Existing main/journal/WAL/SHM files must be regular, owned by the current UID, singly linked and private. Existing profile/plugin-data/plugin directories must be current-UID directories without group/world write permissions. Unsafe links or permissions are refused without chmod, unlink, truncation or repair. These checks prevent the tested pre-existing-file hazards; they do not promise race-proof filesystem containment.

SQLite uses its default rollback journal, `synchronous=FULL`, foreign keys and trusted_schema off. The plugin does not enable WAL independently of the host's compatibility controls. Application ownership and supported schemas are verified transactionally; exact v1 stores upgrade to v2 as documented in [17](17-local-task-agenda.md). Foreign, modified, corrupt or newer schemas fail closed; the original database is not silently replaced. Keep the original files and investigate before attempting a manual recovery.

Plugin data survives install updates/removal under the native storage convention [S1]. Disabling or removing the plugin is not data deletion. Do not assume uninstall implements forgetting.

## 6. Why Native Overview Reads Were Not Added

Source inspection and synthetic probes rejected a misleading “read-only native overview” at this pin:

| Native operation | Observed limitation |
|---|---|
| Project list | Opens a store that initializes/migrates tables [S3] |
| Kanban list | Calls recompute_ready and can change task states; boards are shared across profiles [S4, S5] |
| Cron list | Creates directories and may repair/rewrite legacy job storage; listing is unbounded [S6] |

Wrapping those operations in a read-only tool would not remove their effects or create owner isolation. This slice does not call them, read their database schemas privately, start a gateway, or treat unavailable native data as zero tasks. E0.3 still needs supported native contracts before the inbox can map to native work.

## 7. Verification and Remaining Gates

The source and real-host suites cover validation, replay/restart, concurrent same-key capture/update, competing revision changes, transaction rollback, foreign/newer/corrupt schema refusal, bounded pagination, mode changes, profile switching/deletion, default storage laziness and error redaction. Storage regressions cover main files and all three SQLite sidecars, hardlinks/symlinks, permissive files and writable directories. Real top-level CLI subprocesses run with a clean environment and socket-connect guard.

Verification is against synthetic temporary profiles, not personal accounts, a phone, a real Bot binding or production data. No model/provider call or API Key is needed. Run [the full repository checker](../README.md#development-checks) for unit, lint/type, bilingual docs and pinned-host contracts. Exact counts and CI belong to the tested commit, not a promise that later edits pass.

Before agent/channel/HTTP access: complete E1 verified identity, source scope, action policy and audit; finish the relevant E0.4 paths; design the E2 migration/data-retention boundary; and verify native adapters separately. The optional primary-Bot and client designs cannot be enabled merely because this local inbox works. The controlled-write release gate stays blocked.

## 8. Pinned Sources

- S1: [Official durable plugin storage guidance](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#store-durable-state).
- S2: [Profile-resolved plugin storage helper](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/plugin_storage.py).
- S3: [Project store open/init behavior](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/projects_db.py).
- S4: [Kanban list operation and readiness recomputation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/kanban_tools.py).
- S5: [Shared Kanban board storage](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/kanban_db.py).
- S6: [Cron store loading, repair and listing](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/jobs.py).
