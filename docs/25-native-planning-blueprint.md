# 25. Native Personal Planning Blueprint

English | [简体中文](25-native-planning-blueprint-zh.md)

**Implemented native template integration, not controlled reminder delivery or Primary Bot authorization.** An explicitly enabled planning template appears in Hermes's existing Automation Blueprint catalog. Users configure it through native `/blueprint`, Desktop Cron or dashboard flows. No extra personal-agent CLI command, scheduler or agent loop is added.

The plugin only registers a static template. It does not create a cron job, read the local inbox, access accounts, select a model, obtain credentials or call a provider during registration. Tests use synthetic profiles and do not start a live schedule. Hermes remains pinned to `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.

## 1. Explicit Opt-in

Add this setting to the existing plugin entry, preserving other settings and plugins:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
        planning_blueprint: true
```

`planning_blueprint` defaults to `false` and must be an actual boolean, not a string, integer or null. Invalid values refuse plugin registration. It is independent of `mode`: the template can be registered without enabling local task storage. Existing `local_tasks` users can retain that mode. Reload the plugin/profile through the supported native lifecycle after changing template configuration; a config-file edit alone is not an immediate revocation mechanism.

Registration adds catalog key `hermes-personal-agent:planning-check-in`, titled **Personal planning check-in**. It does not replace a built-in or another plugin's blueprint. Disabling this option and reloading, disabling the plugin, or uninstalling removes the template from discovery. **Already-created jobs remain active until separately paused or removed in Hermes.** This plugin does not enumerate, cancel or manage those jobs.

## 2. What the User Configures

| Slot | Contract | Default |
|---|---|---|
| `time` | Native `HH:MM` schedule input | `09:00` |
| `recurrence` | Strict enum: `everyday`, `weekdays`, `weekends` | `weekdays` |
| `focus` | Strict enum: `priorities`, `commitments`, `weekly-review` | `priorities` |
| `language` | Strict enum: `English`, `Simplified Chinese` | `English` |
| `deliver` | Native delivery target, with local/origin suggestions; native UI may offer configured targets | `local` |

The template asks three short reflection questions about the selected focus. It asks the user to provide current facts instead of pretending to inspect tasks, messages or calendars. It requests no browsing, account access, tools or external actions. Those sentences are **prompt instructions, not a sandbox or enforced tool restriction**. The blueprint API does not provide a per-job tool allowlist, spend cap or domain authorization gate.

The selected focus does not determine cadence: `weekly-review` with `weekdays` still schedules every weekday. Choose the actual desired recurrence and review the native schedule. This template does not add date/timezone/DST semantics of its own. Verify the host scheduler's effective timezone and next run before relying on a local clock time; no user-location timezone is inferred.

`local` saves the native cron result without sending a message. It is a default, not a restriction on Hermes. The delivery slot deliberately follows native target selection; choosing `origin` or a configured channel changes the recipient. Check the destination before scheduling. Local delivery still runs an agent/model and can transmit the prompt to its configured provider and incur charges. It does not mean offline computation.

## 3. Use Native Scheduling Deliberately

Open the native Blueprints catalog and select the namespaced template. Review its fields and submit only when ready to create an ordinary cron job. Desktop/dashboard submission is an action, not a dry run.

The chat command is likewise not uniformly a preview:

- `/blueprint` lists the catalog.
- `/blueprint hermes-personal-agent:planning-check-in` selects a conversational setup flow that can start an agent turn. The model may ask for choices; do not assume this is a cost-free inert form.
- Selecting the key with inline `slot=value` arguments can create a job directly through Hermes's deterministic shortcut. It is not a preview and is intentionally not presented here as a copy-and-run setup command.

Actual execution needs a working native scheduler and an already configured model/provider. Native transport setup is additionally needed for non-local delivery. A recurring job can continue making paid model calls until stopped. We have not configured any of these services or credentials for the user. Use the authorized secure credential flow if live testing needs a key; never paste keys into chat or the blueprint fields.

Use Hermes's normal cron interface to inspect, pause or remove the created job and verify the outcome. Plugin removal does not revoke an ordinary native job's access. The host owns the job's prompt, schedule, execution and delivery state after creation; this plugin does not claim durable domain receipts or exactly-once delivery.

## 4. Safety and Product Boundaries

- No local task/project data is attached to the template or read by a plugin tool. It does not synchronize the [local inbox](16-local-task-inbox.md) or [project groups](24-local-project-groups.md).
- No owner is enrolled, receiving Bot verified, Primary Bot selected, private read granted or controlled action admitted. The [identity gates](23-host-command-context-experiment.md) remain open.
- A native user scheduling flow is not evidence that all existing Hermes tools are secured by this plugin. Native jobs retain the host's model, tool, permission, delivery and retention behavior.
- No policy for quiet hours, escalation, recurring costs, cross-channel consent, hard cancellation, outbox reconciliation or unknown delivery outcomes is implemented here. Prompt instructions do not fill these gaps.
- This blueprint has no bundled skill dependency. Its filled prompt is copied into native job state; future plugin updates do not automatically update existing jobs.

This is a narrow native-template precursor to E0.3/E4.2. E4 controlled reminders, E1 authorization and the M1 acceptance gates are not complete. The status report continues to mark reminders and external delivery unavailable as **plugin-managed controlled capabilities**, while separately declaring the template implementation. It does not inspect whether a job has been scheduled.

## 5. Verification and Sources

Tests cover exact boolean configuration, default absence, native registration/discovery, template filling and strict choices, default local delivery, cleanup/reload and native scheduling handoff with synthetic test doubles. Registration must not create tasks or cron storage. Test assertions distinguish a generated schedule specification from an executed job. Actual provider calls, scheduler firing, mobile delivery and device UI acceptance remain unverified.

The host supports plain-data blueprint registration under plugin-host isolation. Any tested pipe registration is narrower than production isolation or an owner boundary; it does not remove the [existing local CLI isolation limit](../README.md#try-it-in-an-isolated-hermes-profile).

- [Public blueprint API and lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#L1965-L1996).
- [Registration and cleanup tracking](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_content.py).
- [Native catalog and filling](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/blueprint_catalog.py).
- [Chat selection versus direct creation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/blueprint_cmd.py).
- [Dashboard instantiation and dynamic delivery choices](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/cron.py#L901-L966).
