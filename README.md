# Hermes Personal Agent

English | [简体中文](README-zh.md)

A Hermes-native personal-agent plugin designed for one main agent to manage projects, commitments, reminders, and constrained workers. See the [design index](docs/README.md). It does not run a second agent loop or require another API gateway.

The [local full-text memory search guide](docs/66-local-memory-full-text-search.md) adds explicit multi-term AND search with Chinese short-term checks and transactional FTS5. Memory schema v7 requires SQLite FTS5/trigram/secure-delete; read-only opens never migrate old stores.


The [native memory workbench](docs/67-readable-memory-workbench.md) now uses readable views; prefix `/personal-memory --json` for structured integrations. Model tool JSON is unchanged.

[Private Markdown memory projection](docs/68-private-memory-projection.md): explicit refresh, fixed private files and fenced crash recovery; SQLite remains canonical.

[Bounded Chinese automatic recall](docs/69-chinese-automatic-recall.md): shared local query planning and conservative matching, with fixed synthetic evidence; explicit search and authority are unchanged.


## Current status

The current priority is a **profile-first single-user local MVP**, without mandatory Primary Bot binding. E0 foundations, local task storage and an opt-in native conversation `/personal-tasks` command are implemented; session-scoped task model tools are also implemented, with real-model natural-language acceptance still pending.

- Native loading through `plugin.yaml` and synchronous `register(ctx)`.
- A read-only `personal_agent_status` tool and, in `in_process` plugin mode, the `hermes personal-agent status` CLI.
- Default `read_only` mode opens no task storage. Explicit `local_tasks` enables a profile-local CLI inbox: capture, search, project grouping, list/show, update, complete and cancel, plus explicit due dates and agenda with durable replay receipts and revision checks. No personal-data model tool is registered by default; separate local_model_tools opt-in registers gated tools that also require session activation. Model routing is unimplemented, and plugin loading creates no schedule or external delivery.
- Offline unit tests and real discovery, registry dispatch, configuration, and unload contracts against a pinned Hermes commit.
- Follow-on E0.4 failure-boundary contracts and a read-only inventory of ten blocked write paths. `hermes personal-agent coverage` shows the evidence; it does not authorize or disable host tools.

This plugin **does not disable or secure other Hermes tools**. E0.4 write-path coverage and E1 identity/authorization are incomplete, so this foundation must not be used to enable remote or external writes. Separately opted-in task model tools access only local tasks in an explicitly activated trusted local session. Local task edits are separate explicit local-operator commands. Its status explicitly reports `release_gate: blocked`. See the [first-slice implementation record](docs/12-foundation-progress.md), [enforcement contracts](docs/13-enforcement-contracts.md), and [changelog](CHANGELOG.md).

The detailed [client and connector API contracts](docs/14-client-api-contracts.md) are design work only. No HTTP API is registered by this plugin yet. M1 prioritizes existing native local sessions; mobile channels, a custom app and a selected Primary Bot are optional later lanes with separate authentication/recovery gates.

The [local task inbox guide](docs/16-local-task-inbox.md) documents opt-in, commands, persistence and privacy limits. [Due dates and agenda](docs/17-local-task-agenda.md) explain date semantics and the original v1→v2 store upgrade; they do not deliver reminders. The [primary Bot binding design](docs/15-primary-bot-binding.md) selects an existing native Bot/canonical chat, but binding and owner authentication are not implemented.

The [owner-entry/read-authorization foundation](docs/18-owner-entry-and-read-authorization.md) adds a pure internal evaluator and `/personal-access` / `hermes personal-agent access` denial diagnostics. Public source context lacks verified receiving-Bot/account provenance, so production identity issuance and that protected-read lane remain disabled; this is not completed owner authorization. Separately opted-in single-user local commands do not depend on this future remote protocol.

The [unified voice design](docs/19-unified-voice-provider-contracts.md) covers local ASR/TTS/VAD, user-configured online APIs and explicitly adapted realtime frontends under shared lifecycle/recovery contracts, preserving real backend differences. The [offline voice simulator](docs/20-voice-contract-simulator.md) now exercises a narrow synthetic contract through `hermes personal-agent voice self-test`. It uses generated silence only, with no microphone, speech model, provider call or native turn. Account connections and live voice remain unimplemented.

The [local search guide](docs/22-local-task-search.md) adds literal title/details retrieval with bounded pages. A separate [native voice IPC experiment](docs/21-native-voice-ipc-experiment.md) includes a reviewable host patch and verification record; it is not applied or integrated by this plugin.

The [local project groups](docs/24-local-project-groups.md) add explicit task labels, project filters and progress counts, with a schema-v3 upgrade preserving old receipts. These are local groups, not native Projects or permission scopes. The [host command-context experiment](docs/23-host-command-context-experiment.md) packages a separate unintegrated identity-observation patch and its remaining gates; no owner authorization is enabled. Its command-only repair is verified separately with 87 guarded tests; nine historical socket setup failures remain unresolved.

The opt-in [native planning blueprint](docs/25-native-planning-blueprint.md) is available through Hermes’s existing Blueprint/Cron interfaces. Loading registers a template only, not a job. Native scheduling can incur model costs; existing jobs survive plugin removal. Default delivery is local, not a tool or privacy sandbox.

The [pending enrollment/policy core](docs/26-pending-enrollment-policy.md) now persists prospective mappings and scopes with transactional revisions, terminal revocation and audit. Its internal opener is disabled by default and has no registered runtime entry point. These records do not authenticate an owner, issue grants or adopt local tasks.

The [fenced read-admission core](docs/27-fenced-read-admission.md) adds current-policy transaction ordering and bounded immutable summary coordination. Only synthetic tests supply trusted confirmations/resources; no production adapters, runtime entry point or task adoption are enabled.


[Native local task conversations](docs/28-profile-first-local-conversations.md) connect the existing store to Hermes sessions. In a trusted single-user installation, explicitly set `mode: local_tasks` and `local_conversation: true`, then use `/personal-tasks add "Prepare demo" --project "Personal Agent"`, `list`, `projects`, `update` and `done`. Commands rely on native host session authorization; already-authorized owner/operator controllers share access, and `LOCAL` does not prove physical locality. Do not enable on an exposed/shared gateway. The deterministic commands add no model call or new remote entry; projects remain task labels.


[Session-scoped task tools](docs/29-session-scoped-task-tools.md) add `personal_tasks_read` / `personal_tasks_write`. Separately enable `local_model_tools: true`, then activate 30 minutes with `/personal-tools enable-read` or `enable-write` in the native session. Task results enter the configured model context; all model activity in that session shares access, not per-instruction human-intent verification. Only ordinary native in-process mode is supported, not managed workers/hosted plugins; do not disable isolation. Real-model acceptance has not run.

The [pluggable memory design](docs/30-pluggable-memory-contracts.md) specifies a replaceable project backend and user-written adapter SDK, default SQLite records/events/FTS with Markdown projections, and an optional real Hermes MemoryProvider bridge. Existing native providers remain selected until an approved replacement. The explicit local-record and optional native read-only recall slices below implement limited parts of that design. Automatic ingestion, durable conversation checkpoints and migration remain planned.

The first [explicit local memory slice](docs/31-explicit-local-memory.md) now supports `/personal-memory remember`, `search`, `show`, `correct`, `forget` and bounded `export` in an existing trusted native session after separate `local_memory: true` opt-in. It uses a dedicated SQLite store behind a small internal backend interface, preserves native providers, and performs no automatic recall/extraction. Commands/results may enter normal host history; forgetting does not erase that history or backups.

[Session-scoped memory tools](docs/32-session-scoped-memory-tools.md) now add bounded model remember/query/correct/forget through a separate `memory_model_tools: true` option and `/personal-memory-tools enable-read` or `enable-write` activation. Task-tool activation does not grant memory access. Model edits are labeled `activated_session_model`, not verified human instructions; native providers remain unchanged. Existing memory DBs now upgrade atomically to schema v3; see the durable progress guide below. Real-provider natural-language acceptance remains pending.

[Local task operation history](docs/34-local-task-history.md) adds revision-ordered metadata through the CLI, `/personal-tasks history` and activated task read tools. It survives restart and exposes no old task text. It does not verify authors, execute work or reconcile native workers.

The [offline worker-routing precursor](docs/35-offline-worker-routing.md) checks synthetic candidate constraints and qualified baselines, with partial pinned native contracts. It makes no provider calls, registers no routing backend and does not enable live shadow or automatic switching.

The [bounded recall guide](docs/36-bounded-memory-recall.md) adds explicit multi-keyword literal retrieval through native memory commands and activated read tools, with complete records, current revisions and a serialized-result budget. No automatic prompt injection or native provider replacement is enabled.

The native [`personal-agent routing inspect`](docs/38-routing-readiness-inspection.md) command checks saved local delegation declarations without exposing route identifiers or secrets. It reports inheritance/fallback/effort caveats, never certifies effective session routing, and performs no model call or backend switch.

The [durable progress guide](docs/37-durable-memory-progress.md) adds metadata-only memory change pages and internal restart-safe consumer cursors. It preserves existing record receipts during v1/v2→v3 migration and does not claim native compression checkpoint support.

The [daily task review](docs/40-daily-task-review.md) combines exact overdue/today/upcoming/undated counts with budgeted title summaries through existing local entry points. It preserves current read admission and adds no schedule or automatic priority decision.

[Local memory metadata checkpoints](docs/39-local-memory-checkpoints.md): Explicit native commands create durable metadata-only markers with event/record consistency checks, watermark fencing and stale-status inspection. These do not back up payload or satisfy native compression checkpoints.

[Optional native memory recall](docs/41-native-memory-recall.md): An explicitly selected real MemoryProvider can supply fresh bounded local-record context to supported native primary sessions. It performs no ingestion or canonical writes; strict native checkpoints remain unavailable.

The [local task progress guide](docs/42-local-task-progress.md) adds explicit working/waiting/blocker notes, revision-safe writes and filtered daily reviews. Task schema v4 upgrades owned older stores atomically while preserving historical receipts; recorded progress is not native execution evidence.

[Native checkpoint evidence boundaries](docs/43-native-checkpoint-boundary.md) add bounded I/O-free candidate preparation and pinned-host contracts. Stable UIDs, pending input and revision limits are verified; automatic ingestion and checkpoint-v2 remain disabled.

The [readable task workbench](docs/44-readable-task-workbench.md) makes existing native task commands usable as concise text views, with exact IDs, revision/retry guidance and bounded continuation. Use `/personal-tasks --json ...` for structured native output; CLI and model-tool JSON remain unchanged.

[Explicit memory expiry](docs/45-explicit-memory-expiry.md) adds explicit UTC deadlines, default expiry filtering, deliberate inspection and schema-v5 migration. Expiry affects fresh recall eligibility, not stored status or deletion; native read-only recall never migrates storage.

[Native task focus](docs/46-native-task-focus.md) connects one explicitly selected task to subsequent main-agent turns. After task-tool activation, `/personal-tools focus <task-id>` supplies a fresh bounded snapshot each turn; `clear-focus`, disable, expiry and restart stop future snapshots. This does not dispatch work or erase prior model/history context.

[Atomic project plans](docs/47-atomic-project-plans.md) save 1–20 explicitly requested tasks under one label with one all-or-none transaction and durable retry key. Native commands, CLI and activated model tools share the same receipt; the tasks then work with project review, progress and focus. This does not dispatch workers.

[Session automatic memory recall](docs/49-session-memory-recall.md) now brings fresh relevant records into supported primary turns after a separate `/personal-memory-tools recall-on` opt-in. It keeps the selected native provider, adds no model request or memory writes, and stops with activation expiry/reload. Historical model context is not erased.

[Reviewed memory candidates](docs/50-reviewed-memory-candidates.md) add separately opted-in drafting from current native input, exact source quotes and native acceptance with an explicit retention choice. Candidates stay out of recall until accepted; expiry cleanup is lazy, and no extra model request or automatic canonical write is introduced.

[Project task dependencies](docs/51-project-task-dependencies.md) now enforce explicit same-project prerequisites before starting or completing work, with a ready queue and fresh dependency snapshots in review/focus. Cancelled prerequisites remain blockers; no worker is launched and no native Kanban state is modified.

## Development checks

`compatibility.json` records the Hermes baseline commit. The current runtime target is Python 3.14. A single tested SHA does not justify a broad `requires_hermes` version range.

Prepare the official Hermes checkout and test environment in separate directories. Do not use a production `HERMES_HOME` or copy account credentials:

```bash
git clone https://github.com/NousResearch/hermes-agent.git ../hermes-agent
git -C ../hermes-agent checkout --detach 2281116525106e3c109993ccb5dc74d02bfc1427
cd ../hermes-agent
export HERMES_HOME="$(mktemp -d)"
export HERMES_RUNTIME_DIR="$(mktemp -d)"
python -m pm.build_env --source . --out ../hermes-test-venv --group dev --group test
cd ../hermes-superagent
../hermes-test-venv/bin/python scripts/check.py \
  --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

Environment preparation downloads dependencies from official sources. Tests use synthetic inputs, temporary homes, and a Python socket connection guard; they do not access real personal accounts. The checker verifies the upstream HEAD and clean tracked sources, records Python and lock/package fingerprints, and invokes the official Hermes `scripts/run_tests.sh`. Missing checkouts or dependencies fail rather than silently skipping compatibility checks. The recorded package inventory is evidence of the interpreter used, not proof that an arbitrary supplied environment exactly matches the lock.

The checker forwards both source roots through pytest configuration after the host runner clears environment variables. This preserves imports for external plugin checkouts, including paths containing spaces, without passing credentials into the test environment. No manual `PYTHONPATH` override is required.

`python scripts/check.py` alone runs repository unit tests, Ruff, ty, and bilingual document structure/link and JSON-example syntax checks, and explicitly reports Hermes compatibility **NOT RUN**. Test-tool versions come from the pinned Hermes dev group, not plugin runtime dependencies.

Successful push builds now attach a [verified offline runtime package](docs/runtime-distribution.md#downloadable-push-build-package): deterministic archive, full official static-scan findings and cold actual-package CLI/reload acceptance. This is a downloadable development artifact, not a release or permission to retry installation.

## Try it in an isolated Hermes profile

The latest official full-repository installation attempt stopped at the unchanged security scanner (CAUTION, 50 findings); the plugin was not installed or enabled. Do not override that refusal. The [offline runtime distribution builder](docs/runtime-distribution.md) produces a byte-preserving package with source provenance, but does not scan, install or authorize another attempt. The instructions below describe a future separately reviewed installation, not a passed acceptance test.

This is not a production installation recommendation. Use the pinned, tested Hermes checkout and a temporary profile. Consult that version's `hermes plugins install --help` and install a reviewed **full 40-character commit SHA**. `--ref` does not accept branch names, and a GitHub tree URL is not a replacement for the pin. Explicitly enable the plugin afterward. Its ID is `hermes-personal-agent`.

Current runtime contract tests cover the default `plugins.isolation: in_process`. Under `plugins.isolation: host`, Hermes skips `ctx.register_cli_command`, so this CLI is unavailable. Full isolated-host tool execution has not been tested. Do not disable an existing isolation setting just to expose this CLI.

The host's `config.yaml` uses:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
```

Preserve existing entries when combining this with your configuration; do not replace the entire `plugins` section. Enabling the plugin does not change `delegation.backend`, the main model, credentials, tool overrides, or other permissions. Whether `personal_agent_status` appears in the model's tool surface also depends on the session's toolset selection. CLI status does not require an LLM call.

To try the local inbox, explicitly change only this plugin’s mode to `local_tasks` and follow [the command examples](docs/16-local-task-inbox.md#2-enable-and-use). It uses POSIX private-file checks and is tested on Linux; Windows task storage is unsupported. It does not bind a Bot, dispatch native work or need an API Key. Task text is plaintext local data, not a secret store.

## License

[MIT](LICENSE). The review-only voice and command-context experiments include limited upstream-derived patches and their licenses; the Hermes host itself is not vendored or modified by plugin installation. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and licensing.

The [task-to-worker proposal](docs/48-task-worker-proposal.md) adds a review-only host patch and concrete experimental consumer for an explicitly authorized one-task planning draft. The isolated proposal now includes a dedicated no-redirect client, conservative durable draft/retry receipts and a readable native request workbench (list/status/saved draft/stop before submission). It does not enable production dispatch, tool execution, automatic recovery of uncertain provider outcomes or real-model acceptance.

## Parked native Kanban handoff

[Explicit preview/commit handoff](docs/52-parked-kanban-handoff.md) can park a local task on an explicitly named shared native board. It is default-off, creates no assignee or dispatch, and preserves uncertain outcomes without retry. Registration/status do not probe native storage; operation-time compatibility checks and live acceptance remain separate.

[Advisory native progress sync](docs/53-native-progress-observation.md) explicitly observes an identity-bound parked card into the local task. Native done is not local completion; no automatic sync or dispatch.

Added [saved native attention review](docs/54-saved-native-attention.md): local snapshots only, overlapping buckets with unique counts, no live-board read or completion change.

[Gated task planning worker](docs/55-gated-plan-worker.md): Production-package integration is default-off and requires the exact reviewed host contract plus current consent; not installed or live-accepted.

[Explicit atomic plan dependencies](docs/56-atomic-plan-dependencies.md): Explicit one-based batch references save tasks and edges together, without automatic execution.

[Explicit task breakdown](docs/57-task-breakdown.md): Atomically captures steps, inherits prerequisites and makes the parent depend on every new step; no automatic execution or completion.

[Native result review and explicit local acceptance](docs/58-native-result-review.md): Review untrusted card text directly, then explicitly complete the local task with a rechecked digest and human note; no automatic completion or native mutation.
