# 90. Original Local M1 Acceptance

English | [简体中文](90-local-m1-acceptance-zh.md)

## Decision and fixed checkpoint

Status: **accepted original local M1 scope** at the fixed checkpoint below. Final independent review and merge of this acceptance record remain required before its publication. Issue [#115](https://github.com/MosBot-AI/hermes-superagent/issues/115) reconciles the original profile-first deterministic local M1 scope; it does not complete the Hermes Super Agent goal.

- Source: `ed6bcdc15d883dc429f2dbb0559a62204965ab04`.
- Source tree: `24bae909c2caf97e11620a1d9a660cba22272670`.
- Hermes: `2281116525106e3c109993ccb5dc74d02bfc1427`.
- Exact-source [Foundation run 42859787656](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656): completed successfully. This covers the offline checks, pinned-host contracts and production runtime verification, not live transport.
- Exact-source [manual Gateway run 42862192600](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42862192600): completed successfully. The run API confirms the exact source SHA and result; job logs confirm 3 upstream lifecycle tests and 5 packaged-plugin tests passed. The two hard kills occur within one packaged test, not two additional tests.

The acceptance source remains this fixed checkpoint, not an unspecified future main or this documentation commit. The machine-readable [ledger](local-m1-acceptance-ledger.json) records source, host, evidence links and exact test functions. Its static [test](../tests/unit/test_local_m1_acceptance.py) checks structure and references only; passing it does not rerun scenarios or verify GitHub outcomes.

## Original criteria, not new requirements

The sources are [product scope §5](01-product-and-scope.md#5-end-to-end-flows-required-in-the-first-version) and the [M1 milestone](08-roadmap-and-acceptance.md#2-milestones). They specify trusted single-user LOCAL commands, durable tasks/project labels, restart/duplicate/revision/invalid-input/host-admission checks, explicit limitations and no newly enabled remote/outbound capability. E6.9 follows this deterministic slice. The implementation does not turn a profile or LOCAL label into verified human identity.

| Ledger criterion | Evidence mapping |
|---|---|
| M1-1: opt-in native LOCAL entry without a Bot | Native owner-command lifecycle, default-off registration and packaged Gateway installation/dispatch |
| M1-2: add/list/search/projects/show/update/done/cancel/agenda | Conversation workflow, native cancellation/reload and Chinese project-plan chain |
| M1-3: durable receipts, duplicate/CAS/input refusal and restart | Conflict/invalid-input tests, native manager replay and actual Gateway restart/readback |
| M1-4: existing host admission before private access | Native authority/source refusal, non-LOCAL rejection, producer-event refusal and admitted owner/operator scope |
| M1-5: configuration and profile boundaries | Absent opt-in, reload/unload, current configuration and two-profile isolation |
| M1-6: private storage and truthful failures | Unsafe file/sidecar and foreign-database refusal; uncertain outcome retains the retry key without automatic retry |
| M1-7: bounded local scope | Supported source contract, non-LOCAL refusal and existing authenticated native transport, not a new plugin listener |

The ledger gives exact executable references for every row, including which evidence run applies. A native in-process authority test is not a real login test. A real Gateway test does not replace all adverse native-context tests. They contribute distinct observations on the same source checkpoint.

## Applicable entry prerequisites

The roadmap also requires applicable E0.1/E0.2/E0.4/E0.5 evidence. The ledger's `entry_prerequisites` maps these separately to exact tests and the same Foundation run:

- **E0.1:** exact host imports and agreement among the runtime pin, compatibility record and workflow. No broad version range is inferred.
- **E0.2:** actual plugin discovery/dispatch, enable/disable, invalid configuration, unload/reload and profile-scoped storage helper contracts used by local tasks. No imaginary host API is assumed.
- **E0.4:** the [finite enforcement ledger](enforcement-evidence-ledger.json) and production exposure tests cover defaults, frozen configuration, safe bootstrap, unsupported workers and blueprint consumers. These establish applicable project non-exposure/default-denial boundaries, **not host-wide read-only behavior**. Explicit local task opt-in retains its own admission. Independently configured host tools remain outside this guarantee. The optional planning blueprint can schedule ordinary host delivery and incur provider costs even in `read_only` mode; local M1 acceptance does not enable it or certify general controlled writes.
- **E0.5:** synthetic connector tests exercise bounded provenance/account-separated fixtures, refusal to treat source prose or fixture bindings as authority, and exclusion of fixture code from the runtime. These require no real account and do not establish actual connector authentication or delivery.

These are the local milestone's applicable prerequisites, not a blanket acceptance or closure of all E0/E1 work. The separate ledger rows prevent task lifecycle success from silently standing in for those prerequisites.

## Three different recovery claims

1. **Normal Gateway restart:** planned shutdown, a fresh instance and ticket, explicit session resume and canonical SQLite readback. The packaged task, Chinese plan, priority and follow-up chains exercise this. Priority/follow-up workbenches are useful additional scenarios, not retroactively added original exit criteria.
2. **TaskStore process crash:** 88 parameterized cases in `test_task_process_recovery.py` terminate real child processes at SQL/commit boundaries and verify rollback or durable receipt replay in temporary DELETE/WAL databases. This is neither Gateway crash nor power-loss evidence.
3. **Additional live Gateway crash (#113):** the packaged unobserved create/update scenario kills its own Gateway twice, restarts and reconciles durable state and exact request keys. The client did not consume a reply; that does not prove when the server emitted it. This additional E8.2 evidence does not redefine the original M1 criteria or establish external exactly-once delivery.

The exact-checkpoint manual live run has now succeeded. The scenario boundaries above remain unchanged: success does not turn normal restart into crash evidence, or local recovery into external delivery. No unit mock or static ledger check substitutes for that live run.

## Separate pending work and honest delivery

E6.9 real natural-language acceptance requires an approved OpenCode Go `deepseek-v4.1-flash` connection and remains separate. Full [#21](https://github.com/MosBot-AI/hermes-superagent/issues/21) identity/revocation/external-delivery matrices and [#19](https://github.com/MosBot-AI/hermes-superagent/issues/19) reminders/delivery remain open. Shared authenticated REST, remote-owner/mobile/Bot admission, general worker execution and the broader memory adapter/lifecycle/migration goals are not accepted here. Follow-up dates do not send notifications; local task completion does not perform an external task.

These are **outside this local acceptance scope or separately pending**, never “passed by being not applicable.” Completing this ledger must not automatically close those issues, enable providers or outbound operations, claim TUI/model/device certification, or claim the whole personal agent is finished. Final acceptance requires the exact-source evidence and independent scope review; the deliverable is a bounded local MVP, with the above limitations visible to its user.

## Obtain and try this exact local checkpoint

The [verified runtime artifact](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656/artifacts/13785725174) is named `hermes-personal-agent-runtime-ed6bcdc15d883dc429f2dbb0559a62204965ab04` and expires **2026-12-10 17:04:08 UTC**. It is a CI development artifact, not a release or permanent download channel. Independent read-only verification matched its ZIP digest, inner checksums, all 83 shipped source files and exact source/tree provenance. Its scan report says safe with six medium findings; retain and review that full report, and do not assume later packages have the same result. Foundation validation itself reports no installation and no model calls.

Use the [fixed-checkpoint operator guide](runtime-distribution.md#fixed-checkpoint-operator-entry) for the actual order: verify downloaded bytes against this source **before** adding `.git`, create a local staging Git commit, then use the unchanged official `file://` installer on that commit in a fresh isolated trusted profile. The staging commit is not the original source SHA. A plain extracted folder is not the Git source the installer expects. Preserve all scan/catalog/consent gates; stop on refusal. Do not install the previously refused full-repository tree or lower an existing isolation policy.

The pinned host and prepared interpreter are prerequisites, not supplied inside this plugin archive. Deterministic CLI and admitted LOCAL slash commands need no provider credentials; host UI prerequisites remain separate. Enable only `mode: local_tasks` and `local_conversation: true` for this narrow entry. Follow-up dates do not deliver reminders, and this package does not supply shared authenticated REST, a natural-language acceptance result or full Super Agent completion. See the evidence status above before claiming acceptance of the exact checkpoint.
