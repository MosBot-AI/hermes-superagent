# Profile-first Local Task Conversations

English | [简体中文](28-profile-first-local-conversations-zh.md)

Status: implemented opt-in deterministic command slice, not a complete conversational personal assistant. This is the user-approved first product path. Primary Bot selection, verified remote owner enrollment, mobile APIs and voice remain separate future capabilities.

## 1. Product decision and trust boundary

Use an existing Hermes native local session to manage the selected profile's local tasks. Do not require selecting a Bot, discovering a canonical Bot Chat, or activating the unfinished remote-owner protocol first. One main Hermes agent remains in charge; this plugin adds no agent loop, gateway, login, listener or second scheduler.

The deployment contract is **one trusted user controlling a local Hermes installation and the selected profile**. `mode: local_tasks` plus `local_conversation: true` explicitly opts into exposing that profile's plugin-owned task store through registered commands. Profile is a configuration/storage partition, **not an authenticated person**. Pending enrollment and fenced read-admission cores remain unwired for the future verified-owner lane; these commands do not fabricate enrollment, issue grants or claim those gates have passed.

In the pinned host, normal CLI/TUI/native session commands run through the existing gateway's native `LOCAL` session authority. Before plugin dispatch, the host checks session read/control permission, owner or operator access, the registered live local source and open admission. The plugin then filters supported source shapes and checks its bound profile/configuration. Public `platform`, `user_id`, `session_id` and profile strings are routing information, not credentials.

**`LOCAL` does not prove physical locality.** Already-authorized host owner/operator controllers of the session share this access, including controllers the host has authenticated over its existing transport. The public plugin callback cannot independently distinguish them from the native terminal. Do not enable this feature on an exposed/shared/multi-user gateway or assume it blocks every authorized automation/controller. This feature neither creates nor expands the host's remote authentication surface. Non-LOCAL messaging callbacks, bots, relays, threads and ambiguous source shapes are rejected. Hostile same-process/same-UID code is outside this trust boundary.

## 2. Enable the existing session entry

Use the pinned tested Hermes checkout from the [development setup](../README.md#development-checks), a disposable profile and a reviewed full plugin commit pin. Preserve all existing configuration entries. The additional plugin settings are:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
```

Both settings are required; the new flag defaults to `false` and accepts an exact boolean only. It is invalid with `read_only`. Load/reload the plugin under that profile, then open an existing Hermes native local CLI/TUI session. No Bot binding or API Key is required for the command itself. If the host separately needs a configured model to start its normal UI, that prerequisite is not provided by this plugin and is not evidence of a model call by the command.

Use `/personal-tasks help` in the session. The registered command returns one JSON result directly, rather than starting an agent turn. Task contents are not automatically appended to model context. Read the host UI's own history/logging policy before putting sensitive text in command arguments or results; this plugin cannot guarantee that the surrounding UI never records what it displays.

Current runtime verification targets `plugins.isolation: in_process`. Hosted-plugin/desktop transport end-to-end execution is not certified by the in-process tests. Do not disable an existing isolation setting or expose a server just to try this feature. The legacy direct CLI callback is supported as a compatibility fallback, not the normal pinned CLI/TUI path.

## 3. A useful task and project cycle

Within the selected profile's native local conversation:

```text
/personal-tasks add "Prepare demo" --project "Personal Agent" --due-date 2026-11-10 --request-id demo-add-1
/personal-tasks list --project "Personal Agent"
/personal-tasks projects
/personal-tasks search "demo"
/personal-tasks agenda --on 2026-11-10
```

The add/list response includes `id` and `revision`. Substitute those returned values, not the placeholders below:

```text
/personal-tasks show TASK_ID
/personal-tasks update TASK_ID --expected-revision 1 --details "Use the local conversation demo" --request-id demo-edit-1
/personal-tasks done TASK_ID --expected-revision 2 --note "Demo prepared" --request-id demo-done-1
/personal-tasks projects
/personal-tasks list --state all --project "Personal Agent"
```

`add` aliases `capture`; `done` aliases `complete`. `cancel` uses the same ID/revision/note shape as completion. Project names are exact case-sensitive **task labels**, not native Hermes Project entities or permission scopes. Existing [project grouping](24-local-project-groups.md), [search](22-local-task-search.md), [agenda](17-local-task-agenda.md) and [task storage](16-local-task-inbox.md) semantics apply. Dates are explicit date-only values, not inferred from natural language or a clock.

Arguments use POSIX-style quotes on every supported platform. For titles starting with a dash, use `capture --title=-draft`. `help` documents the complete options. Inputs are bounded to 32,768 characters and 256 tokens; read pages retain their existing size limits. JSON escapes terminal controls and non-ASCII characters; a client may decode those escapes for display.

## 4. Mutation, retry and configuration semantics

All mutations reuse the existing schema-v3 task transaction, request digest and receipt. Edits and terminal transitions require `--expected-revision`; completion/cancellation also require an explicit note. Stale revisions fail rather than silently overwriting another command. Completed/cancelled tasks cannot be edited.

Writes accept `--request-id`. If omitted, a fresh key is generated and returned as `request_id`, including after a storage failure once parsing succeeded. Reusing the same key and same payload returns the saved receipt; changing the payload conflicts. A new key can create a duplicate task. For an uncertain result, retry manually with the returned key and identical command, not with a fresh key. No automatic retry is performed. If the response was lost before its generated key was observed, inspect the task list before deciding to submit again; explicit keys avoid that ambiguity.

The command rechecks the currently visible mode/flag and the bound profile home before opening task storage. Config disable observed by the callback denies subsequent calls. This is not a cross-process immediate-revocation protocol: native workers may hold configuration snapshots, and an already-admitted transaction can finish. Reload/restart the affected runtime to apply settings consistently. Plugin disable/unload removes registration; it does not erase tasks or receipts.

Reusing schema v3 preserves the historical task `source: local_cli` label. It identifies the explicit local-operator path, not authenticated session/Bot provenance audit. No new source-authorization field is added.

The store stays at the existing profile-local plugin data directory with POSIX private-file checks. Loading, status and help create no task database. Windows storage, encryption, native Project synchronization, reminder delivery and retention/forget workflows are still unavailable. These commands do not restrict other Hermes tools.

## 5. API and failure contract

Success and failure use `personal.local-conversation-tasks.v1`, with `scope: trusted_local_conversation`, `request_id`, `status`, `data`, `replayed` and `error`. This is a slash-command result schema, **not a new HTTP API**.

```json
{
  "schema_version": "personal.local-conversation-tasks.v1",
  "scope": "trusted_local_conversation",
  "request_id": null,
  "status": "error",
  "data": null,
  "replayed": false,
  "error": {"code": "unsupported_origin", "retryable": false}
}
```

Unsupported origin is checked before configuration, parsing or storage. Supported calls can still return `profile_context_changed`, `invalid_configuration`, `local_conversation_disabled`, normal task validation/conflict errors or a redacted `local_tasks_unavailable`. Exceptions do not echo private arguments, database paths or stack traces. A denied command is not a successful write or owner-authentication event.

## 6. Verification and remaining gates

The implementation is tested with synthetic tasks in temporary profiles: parsing, command lifecycle, project counts, durable replay/conflict, revision rejection, profile/config changes, default-off registration, unsupported origins and bounded/redacted errors. Real pinned-host contracts exercise the actual plugin loader and native command-dispatch components in process, authorized operator access and two-profile separation under opposite ambient scopes. They are not socket/TUI/desktop live acceptance, verified remote-owner issuance or full hosted-plugin integration. Historical denied identity socket cases remain unresolved and are not retried by this slice.

No real account, API credential, microphone, model provider or external delivery is used. The normal existing host dispatch and authorization contracts are preserved, not replaced by a forged source in production. The full repository check records its exact test counts separately; a source audit or passing synthetic case does not certify a deployed service.

Next: finish E6.8's native command acceptance, then evaluate E6.9 session-scoped natural-language task tools with explicit opt-in, actual host session provenance and no external effects. Do not globally register private-data tools based only on a caller-supplied profile, and do not silently attach all stored tasks to model context. Remote/multi-user authority and Primary Bot binding remain conditional future lanes; see the [roadmap](08-roadmap-and-acceptance.md).

## 7. Pinned host evidence

All references below use Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`:

- [Native CLI gateway command routing](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/gateway_plugin_commands.py): the normal CLI path, not the legacy direct callback.
- [Native command admission](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_commands.py): read/control checks, live-source admission and profile-scoped dispatch.
- [Session authority](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_authority.py) and [local source registration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_local.py): owner/operator permission and live-source identity checks; LOCAL is also used for authenticated native transport sessions.
- [Plugin handler invocation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/run_inbound_hooks.py): public source/session fields, live source context and context-preserving executor.
