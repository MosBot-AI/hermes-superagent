# Session-scoped Local Task Tools

English | [简体中文](29-session-scoped-task-tools-zh.md)

Status: opt-in E6.9 implementation for ordinary native in-process sessions at the pinned Hermes SHA. It adds model-facing task tools to the [deterministic conversation commands](28-profile-first-local-conversations.md). A real-provider natural-language acceptance run has not yet been performed. No credential or account is configured by installation.

## 1. Supported deployment and explicit activation

This supports the already-approved trusted single-user local profile deployment, not a new remote identity service. The host continues to authorize native LOCAL session controllers. All admitted owner/operator controllers and **all model activity in an activated session** share the selected access, including a turn caused by material other than a fresh human message. Activation is not proof that each model-proposed change was explicitly requested. Untrusted content and other enabled Hermes tools remain outside this plugin's sandbox guarantees.

Use the tested Hermes pin and reviewed plugin commit in a disposable profile. Preserve other configuration entries and explicitly add:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_model_tools: true
```

`local_model_tools` defaults to `false`, accepts only a boolean, and requires the other two settings. Loading this configuration registers two tool schemas under the existing `personal_agent` toolset, but does not open task storage or activate any session. Choose that toolset through the host's normal tool-selection controls and start/reload the session as required by the host. Schemas remain profile-wide and stable; their presence is not permission to execute.

In the existing native local session, use one of:

```text
/personal-tools enable-read
/personal-tools enable-write
/personal-tools status
/personal-tools disable
```

`enable-read` permits bounded task reads. `enable-write` includes reads and local edits. Either grants **30 minutes** from that explicit command, with at most 64 active sessions per loaded plugin. Status does not extend the period. Activations are in memory, keyed to the registration's profile plus the exact native session ID and route key; plugin reload/unload or process restart discards them. A new/rotated session needs fresh activation. Turning read access on after write access downgrades it.

**Privacy and costs:** returned titles/details/notes enter the activated session's configured model context and can therefore reach that model's provider and normal host history/logging. Only activate with data you permit that configured model to receive. This is not a new provider connection. Ordinary model usage can cost money under the user's existing configuration; these tools do not add a second LLM call or route to another provider.

## 2. Natural-language workflow and tool contract

After `enable-write`, example requests to the existing main model are “Add a task to prepare the demo in project Personal Agent,” “Show that project's tasks,” and “Mark the demo task complete.” The model must call the registered tools and use the returned IDs/revisions rather than merely promise to remember the task. Natural-language interpretation and tool selection depend on the configured model and still require live acceptance testing.

- `personal_tasks_read`: `list`, `show`, literal `search`, project-label counts via `projects`, explicit-date `agenda`, and metadata-only task `history` with an integer `after_revision` cursor. See [operation history](34-local-task-history.md).
- `personal_tasks_write`: `capture`, `update`, `complete`, `cancel`. Every mutation requires a stable `request_id`; updates and terminal transitions also require a previously read `task_id` and `expected_revision`. Completion/cancellation require a note.
- Unknown, irrelevant, identity/approval fields and wrong types are rejected by the same TaskStore validator. `show` maps to the store's `get`; there are no other hidden action aliases.
- Dates must be explicit. Project names remain labels, not native Projects, worker dispatch or permission scopes. Completing a record does not carry out the underlying real-world task. No reminder or external effect is sent.
- Read results remain bounded by existing page/detail limits. Data is returned only for the requested operation, not automatically loaded as all-profile memory.

A synthetic tool call might be:

```json
{
  "action": "capture",
  "title": "Prepare demo",
  "project": "Personal Agent",
  "request_id": "demo-capture-1"
}
```

Results use `personal.session-task-tools.v1`, with `scope: activated_trusted_local_session`, `status`, `data`, `error`, `request_id` and `replayed`. The task store is unchanged schema v3, including historical `source: local_cli`; that field identifies the explicit local-operator feature family, not verified session/Bot provenance. Stable receipts, conflicting-key rejection and revision rules match the deterministic commands. After an uncertain outcome, retry the same payload/key or inspect the task first; a new key may duplicate a capture. The plugin never retries automatically.

## 3. Admission and revocation boundary

Activation is a real registered slash command under existing native session admission. It accepts only a supported LOCAL source shape and an exact contextual `bound_session_key()` match, without environment fallback. A copied source/session string alone does not activate it through ordinary tool arguments.

Every tool handler, including direct registry dispatch, requires the pinned `agent.relay_runtime.active_turn(dispatcher_session_id)` adapter. It validates a current, non-closed/non-released, profile/session-matched turn; matching task ID; a supported lease platform (`cli`, `tui`, `desktop`); no parent/delegated or cron context; the no-fallback route binding; current profile/config; and an unexpired activation of the requested read/write level. Tool arguments cannot supply an owner, profile, session, approval or lease. No-context registry dispatch with a copied session ID fails before task storage.

The adapter holds the real turn's finalization lock and the plugin activation lock while admitting and completing the bounded store operation. If disable acquires the activation lock first, the next operation is denied; if an operation is already admitted, disable waits for it to finish. Expiry stops future admission, not a transaction already admitted. This is not cancellation of already committed edits. Config changes observed by a callback clear activations when disabled/invalid; reload the runtime to apply configuration consistently. Unload closes retained handlers permanently as well as clearing activations.

This is **pinned in-process routing enforcement**, not an official generic owner-authentication API or per-instruction intent verifier. The live-turn adapter depends on tested host implementation details, including the finalization lock. A host upgrade must pass compatibility tests before enabling it. Arbitrary malicious code in the same process/UID can mutate runtime objects and is outside the trusted-local contract. Other Hermes tools can still access resources according to their own permissions.

## 4. Unsupported modes stay closed

Ordinary native LOCAL sessions and Python plugins default to in-process operation at this pin. Managed execution is separate: safe/config-only and Kanban sessions use workers, and ordinary sessions can explicitly opt into managed workers under the host's restrictions. Those workers have a fresh plugin module and do not inherit these in-memory activations. Hosted Python plugins likewise do not see the parent's imported current-turn context.

Therefore managed workers, hosted-plugin execution, ACP, messaging, delegated children, cron, nested `execute_code` RPC without matching contextual IDs, and absent/unknown turn context are unsupported. A slash activation response is not proof that an independently configured worker can use the tools. **Do not turn off an existing isolation/managed-worker policy to make this feature work.** Keep `/personal-tasks` where independently supported, or wait for a reviewed cross-process activation/revocation adapter. None is implemented here.

## 5. Verification and next acceptance

Automated tests use synthetic data and temporary profiles, actual pinned plugin loading, authorized native slash dispatch, native conversation/turn lifecycle and `model_tools.handle_function_call`, plus lifecycle, scope, TTL, replay, CAS, revoke/unload and denial cases. The native runtime supplies its real context objects; unit fixtures alone do not establish authenticity. No provider API, credential, listener, microphone or live model request is used. Historical denied identity socket cases are untouched.

Remaining: install the reviewed pin in an eligible test session with its chosen toolset/model, then verify natural-language capture → project lookup → edit/complete, refusal after disable, and useful error reporting. Use an already-configured provider if authorized. If a new key is required, request the specific provider/purpose and secure setup first; never put keys in chat, commits or fixtures. In-process tests do not certify full GUI/transport, multi-process isolation or production deployment.

## 6. Pinned host evidence

Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`:

- [Plugin registration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py): profile-scoped tools, commands and unload lifecycle.
- [Native turn façade](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_facade.py) and [turn/lease runtime](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/relay_runtime.py): actual contextual turn, profile/session binding and finalization.
- [Model-tool dispatch](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py) and [session context](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_context.py): dispatcher IDs and the no-environment-fallback route getter.
- [Managed execution selection](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_managed_worker.py): ordinary defaults versus explicit/safe/worker modes.
