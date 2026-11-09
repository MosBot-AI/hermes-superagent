# 75. Native Plugin and Scheduling Lifecycle Contracts

English | [简体中文](75-native-lifecycle-contracts-zh.md)

## Scope and baseline

This test-only E0.2–E0.3 slice addresses [Issue #11](https://github.com/MosBot-AI/hermes-superagent/issues/11). It exercises actual native operator consumers for Project, Kanban and cron, alongside the existing plugin contracts, and records missing supported plugin seams. It adds no production import, configuration option, storage migration, execution authority or installed schedule. GitHub Projects tracks engineering delivery; native Hermes Projects and Kanban are runtime objects, not that delivery ledger.

The exact target remains [Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427), recorded in [compatibility.json](../compatibility.json), with its separate Python 3.14 test environment. Evidence applies to this clean pinned checkout, not a broad support range. The scenario matrix below identifies assertions, not a claim that a particular run passed; exact revisions, results and CI links belong to the Issue and linked PR.

## Operator consumers are not a plugin CRUD SDK

| Surface | Pinned native entry point | Boundary |
| --- | --- | --- |
| Plugin registration and context | `hermes_cli/plugins.py`, `hermes_cli/plugins_context.py`, `plugins/plugin_storage.py` | Actual discovery, configuration rejection, registry/CLI dispatch, reload/unload and profile storage contracts already exist. `plugin_data_dir` creates directories and is not a `ctx` method. |
| Hooks and middleware | `hermes_cli/plugins_dispatch.py`, `hermes_cli/middleware.py`, `model_tools.py` | Existing counterexamples cover callback denial, timeout, outer-dispatcher failure and direct registry bypass. These are not universal write enforcement. |
| Project operations | `tools/project_tools.py`, `hermes_cli/projects_cmd.py` | Operator tool/CLI consumers use native storage. Their existence does not export a stable plugin Project CRUD interface or map local project labels to native Projects. |
| Kanban operations | `hermes_cli/kanban.py`, `hermes_cli/kanban_db.py` | Tests exercise the CLI consumer and native state/event/run helpers for creation, inspection and archive. Tests use only synthetic parked work without workers; archive is not generally a harmless metadata operation. |
| Cron operations | `tools/cronjob_tools.py`, `hermes_cli/cron.py`, `cron/executions.py` | Tests exercise the tool consumer for job operations, `cron_runs` for operator history output and native ledger helpers for independent observations. Jobs, execution attempts and delivery outcomes are distinct objects. |
| Declared plugin API | `hermes_cli/data/plugin_api.json`, `hermes_cli/plugins_context.py` | The manifest exports `cron.execution_identity`, and context can expose the current cron execution. It does not export Project/Kanban CRUD or `cron.jobs`, `cron.executions` and scheduler internals as supported plugin CRUD APIs. Execution identity is not scheduling authority. |

Imports of native operator implementations and lifecycle helpers in these tests are exact-pin probes. They are not new production plugin dependencies. Missing supported seams stay explicit; this slice does not work around them with direct host database writes. Existing default-off [parked Kanban handoff](52-parked-kanban-handoff.md) and its narrower source/identity guards retain their own boundary.

## Project semantics and limits

Native Project creation and listing return host object identity, not a personal-agent effect receipt. The CLI rejects a duplicate primary path; the Project tool instead reuses the existing Project by that path. That is weaker than an exact request key bound to the whole payload: a changed name does not make this path lookup a transactional content-binding contract. Pathless creation can create distinct objects. Query and reopen evidence must identify the actual returned object rather than infer exactly-once creation from a success sentence.

Project archive changes Project metadata and visibility. It is not proof that associated sessions, Kanban work, scripts or cron executions stopped. Native Project storage is profile-scoped, but this is not verified owner identity or protection against arbitrary code with access to the same profile. Local TaskStore project names remain labels; no automatic native Project mapping is added.

## Kanban semantics and limits

The lifecycle tests use explicit temporary boards and parked synthetic cards. Creation/query/archive observations and native event history are evidence about those cards, not a launched worker, completed task or accepted external effect. Sequential creation with the same native idempotency key can return the original card despite a changed title/body. After archival, reusing that key can create a new card. This is not exact payload binding or indefinite deduplication; the suite makes no concurrency guarantee for the native consumer.

Native archive can also stop workers and promote dependent work. Only the no-worker synthetic path is exercised here; the test setup must not be copied into a production board or presented as generic cancellation acceptance. Archiving a card does not establish that an already-started external effect was undone. Existing [result review](58-native-result-review.md) continues to require explicit local acceptance; native terminal status does not automatically complete a local task.

## Cron definitions, attempts and receipts

- **Create is not execution.** An operator create response identifies a saved job definition. With no running scheduler, a stored job does not fire. Repeating creation has no general native request-key deduplication guarantee and can create another job.
- **Persistence and scheduler registration can diverge.** Registration failure may occur after a job was saved. The saved job ID and partial result must be reconciled. A failed or lost response is not permission to call create again.
- **Query is not necessarily pure.** Native job loading can repair persisted malformed/legacy data. A tool named `list` or a read wrapper does not remove those host effects. This is not an admissible production personal-data read merely because it appears observational.
- **Cancel requests an attempt to stop.** The response can contain `cancelled: true` while the attempt is still claimed/running. This acknowledges the per-execution cancellation request, not a verified terminal outcome. It does not pause the schedule; a later occurrence can still run. With no in-flight attempt, cancel is a successful no-op.
- **Pause, remove and cancel are different.** Pause changes future scheduling. Remove deletes a job definition. Neither a definition receipt nor the disappearance of that definition by itself proves that an in-flight effect stopped or that historical delivery was reversed.
- **History can remain unknown.** Recovery of an abandoned attempt records `unknown` when side effects cannot be established. It does not schedule a retry merely because the receipt is absent. A persisted attempt ID is not proof of successful work or delivery.

The one-off `no_agent=True` test runs a temporary script whose only action is printing a fixed synthetic string. The actual `cronjob` run consumer first refuses execution while paused, then, after explicit resume, runs the script exactly once through the native manual path and pauses the job again. It checks the real `completed` ledger row, start/finish times, saved local output, `delivery_outcome: suppressed` and persistence after reopening. It does not import `run_agent` or create `state.db`. This is an actual local completion receipt, not a scheduled-occurrence receipt (`scheduled_instant` is null), external delivery, owner notification, live cancellation or real-model acceptance. Reopened history is also checked through the actual `cron_runs` consumer. The job exists only in the disposable test profile; no ticker or installed user schedule is started.

## Evidence map and test isolation

The lifecycle suites are [Project](../tests/contracts/test_native_project_lifecycle.py), [Kanban](../tests/contracts/test_native_kanban_lifecycle.py) and [cron](../tests/contracts/test_native_cron_lifecycle.py). They complement, rather than replace, the existing suites below. The first matrix uses test names from those three lifecycle files.

| Scenario | Concrete test | Evidence boundary |
| --- | --- | --- |
| Project operator lifecycle | `test_cli_create_list_show_archive_restore` | Actual CLI parser/command create, list, show, archive and restore; archived visibility is distinct from task cancellation. |
| Project invalid input | `test_empty_names_rejected_by_real_consumers`; `test_invalid_slug_and_unknown_project_return_errors` | CLI/tool rejection leaves no new object; malformed slugs and unknown targets fail. |
| Project weak retry identity | `test_cli_rejects_duplicate_primary_but_tool_reuses_existing`; `test_pathless_retry_creates_distinct_ids_without_operation_key` | CLI path conflict, tool path reuse despite a changed name, distinct pathless retries and no durable operation-key/receipt table contract. |
| Project persistence and scope | `test_restart_persistence_and_profile_isolation`; `test_archive_does_not_cancel_linked_native_task` | Fresh interpreter reads and profile separation; linked parked Kanban state/events remain unchanged across Project archive/restore, without a worker. |
| Kanban creation and observations | `test_native_consumer_create_show_list_and_real_receipts` | CLI-created card, real created/blocked events and an empty run history; no execution receipt is invented. |
| Kanban weak native deduplication | `test_native_same_key_changed_payload_returns_original_after_restart`; `test_native_archive_replay_missing_and_archived_key_reuse` | Changed-payload replay returns the original; repeated/missing archive changes no events; an archived key can create a distinct replacement. |
| Kanban scope and archive history | `test_native_board_separation_and_explicit_scratch_override`; `test_native_consumer_archive_keeps_queryable_history` | Named boards remain separate; explicit scratch does not inherit a Project; CLI archive retains queryable events without a worker or workspace. |
| Cron definition lifecycle | `test_real_paused_cron_lifecycle_survives_restarts`; `test_cron_profiles_have_independent_jobs_and_receipts` | Actual create/list/resume/pause/remove, reopened definitions, empty pre-run history and separation of definitions/synthetic claim history between temporary profiles; no ticker. |
| Cron unsafe replay and validation | `test_duplicate_creates_are_not_idempotent_and_names_can_be_ambiguous`; `test_missing_job_is_a_failure_without_new_jobs`; `test_invalid_create_has_no_persisted_effect` | Duplicate creates produce distinct IDs; ambiguous names, unknown IDs and invalid create inputs fail without an extra effect. |
| Saved-but-unregistered creation | `test_registration_partial_failure_keeps_job_and_warns_against_recreate`; `test_actual_registration_exception_exposes_partial_commit_contract` | Injected registration-provider failure, real persistence and real partial exception: `job_saved: true`, `scheduler_registered: false`, `retry_create: false`. No retry create is issued. |
| Cancel request versus terminal outcome | `test_cancel_without_attempt_is_noop_and_preserves_schedule`; `test_cancel_claim_fixture_is_request_not_terminal_cancellation` | Real cancel consumer with an explicitly synthetic claim; the marker preserves the first reason, while the claim remains nonterminal and the enabled schedule/next run are unchanged. |
| Abandoned attempt recovery | `test_dead_process_claim_recovers_unknown_without_job_retry` | A real child process exits after creating a synthetic claim; another process recovers it as unknown, without a new run. History survives definition removal and the actual `cron_runs` consumer reports the unknown attempt. |
| Native query side effects | `test_queries_repair_only_explicit_disposable_corruption_fixture` | A deliberately rewritten temporary `jobs.json` bare-list shape is repaired by native get/list. This corruption fixture is not a fabricated successful receipt. |
| Actual local completion | `test_real_constant_script_has_local_completion_receipt_not_delivery` | One allowed constant-output script process, a completed native ledger row, saved local output and suppressed delivery; paused-run refusal, reopen persistence and `cron_runs` output are checked; no scheduled occurrence is claimed. |
| Declared API limits | `test_project_crud_is_not_exported_plugin_api`; `test_exact_pin_public_plugin_api_does_not_offer_native_crud_sdk` | Reads the actual plugin API manifest and checks the exact host pin; absence of CRUD exports remains a documented seam. |

| Existing evidence | Concrete suite | Scope retained |
| --- | --- | --- |
| Registration, configuration, scoped dispatch and data paths | [Native plugin contracts](../tests/contracts/test_native_plugin.py) | Real manager load/reload/unload, invalid configuration refusal, CLI/tool results and profile-scoped storage helper. |
| Hooks and failure counterexamples | [Enforcement boundaries](../tests/contracts/test_enforcement_boundaries.py) | Callback denial and timeout do not prove the outer dispatcher, direct registry path or all worker contexts fail closed. |
| Planning-template lifecycle | [Planning blueprint contracts](../tests/contracts/test_planning_blueprint.py) | Catalog/form/slash/dashboard integration includes a substituted create call. Those older tests alone do not create or execute a cron job. |
| Existing guarded parked handoff | [Native Kanban contracts](../tests/contracts/test_native_kanban.py) | Exact board/source/identity fencing, uncertain outcomes and no blind retry; distinct from the native operator API's weaker deduplication semantics. |
| Local result acceptance | [Native result review](../tests/contracts/test_native_result_review.py) | Untrusted native evidence requires an explicit rechecked local completion decision. |

Use disposable synthetic homes/profiles and actual native consumers for mutations, not hand-written host database SQL. Internal ledger helpers may establish explicitly labelled synthetic attempts for cancellation/recovery tests; that does not mean those attempts executed. No real account, credentials, model request, network listener, active ticker, worker dispatch or installed user schedule is needed. The cron child permits narrowly matched read-only `systemctl list-units` gateway-liveness probes as well as the constant script, not service start/stop or worker/ticker launch. Its temporary `cache/scratch/.last_prune` freshness stamp suppresses unrelated detached scratch maintenance; it is fixture setup, not execution evidence. Python socket guards are test safeguards, not a malicious-code sandbox or a proof of subprocess network containment.

## Reproduction and interpretation

Follow the [development checks](../README.md#development-checks) with the exact clean host and its prepared interpreter:

```bash
python scripts/check.py
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

The first command runs repository unit, lint, type and bilingual-document checks and explicitly does not run Hermes contracts. The second adds the complete pinned-host contract suite. A passing focused lifecycle suite is not a full aggregate pass; collection, source inspection and a clean diff are not execution evidence. Keep failure, skip, blocked and not-run outcomes separate. No new numerical run totals are asserted in this document.

## Remaining acceptance gates

The bounded E0.2–E0.3 contract work does not complete E0/M0, E1 authority, E3 runtime orchestration, E4 controlled reminders, E5 connectors or a production release. It does not implement a supported plugin scheduling adapter, durable cross-system admission/outbox, exact effect-level idempotency, live worker cancellation, real-account delivery reconciliation or general native ownership isolation. Source gaps can satisfy the requirement to document unavailable seams; they cannot be relabelled as available features.

Issue completion still requires the applicable test evidence, independent review, merged change and verified merged-main CI. Broader parent work and [live acceptance](65-live-task-acceptance.md) retain their own gates. The production readiness report, default-off capabilities and authorization boundaries are unchanged.
