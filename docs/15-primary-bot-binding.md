# 15. Primary Bot Binding and Continuity

English | [简体中文](15-primary-bot-binding-zh.md)

**Status: optional future design, not implemented; not a prerequisite for the profile-first local MVP.** If this capability is chosen, the user selects an existing Hermes **Bot Mode Bot** to act as the personal super agent. This does not create another agent loop, change Hermes's global/default Bot, or grant new permissions. All binding records, service methods, roles, events and capability flags below belong to this proposed plugin design. The current CLI task inbox is a separate local feature, not proof of Bot binding or owner authentication.

The design source baseline is Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. Compatibility checks cover the [roster](#current-pin-canonical-bot-chat-roster), [Desktop routing](#current-pin-desktop-profile-routing), [native profile lifecycle](#current-pin-native-profile-lifecycle), [native backup and restore](#current-pin-native-backup-and-restore), [same-install Bot messaging](#current-pin-same-install-bot-messaging), [deferred Bot Chat delivery](#current-pin-deferred-bot-chat-delivery) and [local Bot transport and restart](#current-pin-local-bot-transport-and-restart) at the current pin. Read [03](03-native-architecture.md), [06](06-plugins-mcp-and-security.md), [11](11-worker-model-routing.md) and [14](14-client-api-contracts.md) alongside this contract.

Preparatory code and contract evidence are in [18](18-owner-entry-and-read-authorization.md): the read evaluator exists, but missing public receiving-Bot identity keeps production owner contexts and private reads in this remote/Bot lane disabled. The binding flows below remain a design.

The current default route is E6.8/E6.9 in [08](08-roadmap-and-acceptance.md): native LOCAL sessions in a trusted single-user local gateway/profile, without Bot enrollment. A profile is not identity; LOCAL is not proof of physical locality. Host SessionAuthority owner/operator read/control, exact registered live-source and admission checks still apply, and all already host-authorized controllers share local data. Local commands do not pass the remote-owner/binding gates in this document; the unwired pending-enrollment/read-admission cores are not prerequisites for explicit local commands.

## 1. Decision and User Experience

In this optional Bot-bound lane, the personal main agent is the user's selected native Bot: its profile owns personal domain state, and its **canonical Bot Chat** is the preferred coordination conversation. Hermes still owns inference, sessions, compression, worker execution, cron, credentials and transport. The plugin contributes personal-domain context, tasks, policy and evidence.

The intended setup is: select an existing Bot and its machine, review the exact target and data scope, confirm the binding, then see **Primary Bot: <display label> · <verified connection/profile>** with a separate capability/health indicator. Binding an existing Bot preserves its model, SOUL, memory provider, credentials, ordinary conversations and routines. No automatic copying, destructive reset, model change, or retitling of another conversation occurs.

The designation is a plugin responsibility, not Hermes's reserved `@hermes` alias or the desktop's active/default profile. Opening another Bot does not switch the personal primary. Other Bots remain available for their own work.

## 2. Native Facts and Boundaries

| Verified at the pin | Consequence for this design |
|---|---|
| A Bot Mode Bot is a profile with roster metadata and a canonical Bot Chat [B1] | Bind the native profile and canonical registry, not a new persona or platform token |
| Plugin managers and durable plugin state are scoped to Hermes home/profile [B2] | Enable the backend in the selected profile; installing UI code does not bind every Bot |
| Desktop exposes `host.profileRoutes()` and route-aware `host.requestProfile()` [B3] | Use the complete verified route descriptor; never choose by display name alone |
| `profiles.list` supplies `canonical_session.id` and its compression `resolved_id` [B4] | Resolve the authoritative canonical conversation, not `last_session`, a worker, or cached UI metadata |
| The install has an opaque `install_id`; profile names/paths can change and no immutable profile incarnation is exposed here [B5] | Install ID and slug are useful locators, not authentication or sufficient recovery proof |
| `ctx.inject_message` is profile-scoped, capability-gated and returns only a boolean host acceptance [B6] | It is not a durable exactly-once delivery API or proof that a Bot answered |
| Platform routes distinguish receiving `bot_profile` from executing `profile`; session keys include platform/chat/thread/user [B7] | Same profile is not automatically the same conversation or transport account |
| Hermes exposes `message_agent` in protocol-enabled Bot Chat sessions on managed installs [B8] | Eligible Bots can collaborate through a native route. Owner grants and worker routing have independent gates. |
| Cron can target `bot-chat[:profile]` through native authority admission [B9] | Reuse native receipts and scheduling; never run a second writer against a Bot Chat |

These are reference contracts, not permission to import private modules as a supported plugin API. In particular, the canonical registry implementation, profile-rename internals and Bot delivery mailbox are **source evidence**, not new `ctx` methods. E0.7 must prove supported adapters or report a generic upstream seam. Do not manufacture `ctx.bind_main_bot`, `ctx.current_owner`, or a native immutable `bot_uuid`.

### Supported Adapter Status

The following map applies to Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. Each row lists the observed mode and the proof required before extending it to a Primary Bot capability.

| Reuse point | Tested adapter and mode | Remaining gate |
| --- | --- | --- |
| Canonical discovery and lineage | Native `profiles.list` over ASGI with scoped synthetic tickets covers the hidden Bot Chat root, compression tip, and unavailable or ambiguous roster rows. [Roster evidence](#current-pin-canonical-bot-chat-roster) | Require authorized lookup of the exact root and current lineage for every enabled route. Treat missing or uncertain identity as unavailable. The exact-title `session.list` fallback can adopt a legacy row. Additional discovery modes, compressed UI attach and canonical handoff require independent evidence. |
| Desktop source selection | Real Linux source-built Electron exercises `host.profileRoutes()` and `host.requestProfile()` with private local tickets and a saved loopback Webapp token connection. [Electron evidence](#current-pin-electron-profile-routing) | Verify installed Desktop and any enabled SSH or OAuth routes independently. |
| Bot Mode canonical chat opening | The Linux source-built roster refuses a typed lookup error and an empty result whose native pointer probe confirms the existing chat. Retrying opens that same local, uncompressed chat. [Local Bot Mode evidence](#current-pin-bot-mode-canonical-chat-refusal-and-retry) | Packaged Desktop, compressed UI attach, SSH and OAuth UI routes and authenticated owner binding require separate evidence. |
| Saved Webapp token fallback | The clean Linux Electron build probes the remote launch authority on an empty named-profile lookup. A second lookup in the same click opens the original chat. A separately built candidate probes the named authority, refuses the uncertain open and opens the original on explicit retry. [Saved Webapp evidence](#current-pin-saved-webapp-bot-mode-routing) | The clean pin retains the fallback scope gap. Supported use requires a corrected host revision and mode-specific acceptance. |
| Profile and installation continuity | The stopped native profile CLI and backup/import paths cover rename, clone, delete, same-name recreation, held-profile refusal and the restored destination epoch floor. [Profile lifecycle](#current-pin-native-profile-lifecycle) · [Backup and restore](#current-pin-native-backup-and-restore) | Live transitions and authenticated continuity require current target, enrollment, canonical lineage and conflict evidence. Copied markers and names cannot resolve an ambiguous installation. |
| Local caller and receiving Bot | A Linux same-UID control ticket proves local operator admission. The clean-host owner-entry fixtures refuse when supported receiving-adapter context is missing. [Local Gateway](#current-pin-local-bot-transport-and-restart) · [Owner-entry contracts](../tests/contracts/test_owner_entry_contracts.py) | Protected native commands and channel entries need supported host proof of original caller, receiver and session, followed by current owner and grant checks. The [command-context experiment](23-host-command-context-experiment.md) remains review-only. |
| Plugin state and subagent roles | Public `ctx.subagent_lifecycle` covers process-local parent/child correlation in `in_process` and `host` isolation. `ctx.state` is exercised in both modes, including two named profiles in hosted mode. [Subagent evidence](#current-pin-subagent-correlation) | Managed WorkerChannel and Kanban adoption need their own provenance, grant and revocation checks. [E0.4](13-enforcement-contracts.md) covers separate frozen-config and troubleshooting-safe worker paths. |
| Native Bot and cron delivery | Same-install `message_agent` and `bot_relay.deliver` cover notify-only attribution and local terminal receipt recovery. The native cron path reuses the exact delivery ID after a dropped response and reports `transferred` with a `queued` receipt. [Bot messaging](#current-pin-same-install-bot-messaging) · [Restart](#current-pin-local-bot-transport-and-restart) · [Deferred delivery](#current-pin-deferred-bot-chat-delivery) | Require separate receipt and author reconciliation for reply-enabled, remote and other producer modes. Keep uncertain sends on the same delivery ID. |
| Plugin injection | The native scheduler evidence shows `ctx.inject_message` can return `True` before a later dispatch failure. [Injection evidence](#8-messages-routines-and-receipts) | Durable plugin-owned delivery needs supported idempotent admission and receipt lookup. Keep durable proactive activation unavailable on the boolean path. |
| Optional HTTP | The [client contract](14-client-api-contracts.md#3-authentication-is-not-domain-authorization) records native credential shapes and the E0.6 transport boundary. | Enable Primary Bot HTTP operations only after supported trusted-principal and profile propagation, domain authorization, and capability-specific transport and recovery checks. |

### Current-Pin Canonical Bot Chat Roster

The roster fixture drives the native gateway `/api/ws` ASGI boundary and the OpenRPC `profiles.list` method at clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. It uses synthetic local tickets and temporary profile and session stores without a real listener, Desktop client, model or account. The exchange negotiates `hermes-gateway-v1` and receives `gateway.ready` with `session_authority: true`. [Roster contract tests](../tests/contracts/test_native_bot_roster_asgi.py) · [Gateway OpenRPC](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/shared/src/gateway-contract.openrpc.json)

| Fixture case | Observed result |
| --- | --- |
| Host-scoped ticket explicitly selects a served sibling | Both profiles share a display label and return distinct canonical IDs. The selected profile appears first. Its hidden exact `Bot Chat` supplies `canonical_session.id`. `resolved_id` and preview come from the compression tip. `last_session` and `worker_session` refer to the separate numbered chat and worker. |
| Profile-scoped interactive ticket | The ticket profile exposes its session fields, including a canonical chat whose stored owner differs from the ticket subject. The sibling exposes discovery metadata without `canonical_session`, `last_session` or `worker_session`. An explicit request for that sibling returns `profile_mismatch`. |
| `worker-adoption` ticket | `profiles.list` returns `permission_denied`. |
| Host-scoped roster after a sibling begins retiring | The retiring sibling becomes metadata-only. The serving profile still returns its canonical chat. |
| Unbound legacy or recoverably auto-archived exact-title chat | The authorized roster returns `canonical_session: null`. The numbered chat remains recent and no row is created, adopted or restored. |
| Two isolated ASGI endpoints with distinct runtime instance IDs and the same seeded `install_id`, profile slug and display label | Each endpoint's own ticket returns its own profile path, canonical root, compression tip and preview. The repeated install observation does not identify which endpoint owns a session. |
| Unreadable install ID | The fixture supplies an unreadable marker as a directory. The roster returns an empty `install_id` and still reports the authorized canonical chat. |

The fixture fences execution, socket connections and listeners, and unrelated gateway background activity. It compares session, message, admission and state metadata rows before and after requests and checks that the native authority has no remaining connections or attached sessions. The preseeded install marker is unchanged and no new install lock file appears. The unreadable marker remains an empty directory. [Roster contract tests](../tests/contracts/test_native_bot_roster_asgi.py)

The native admission path grants operator access to a redeemed local `interactive` ticket. The ticket's `profile` or `host` scope independently determines whether a request can reach sibling authorities. This verifies the local operator contract only. Verified human ownership, remote authentication and public plugin caller context require their own proof. [Native gateway admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/run_api.py#L452-L490) · [Current-pin owner evidence limits](78-enrollment-ceremony.md)

The authority roster reads the existing session stores with `reopen=False`. The exact-title `session.list` path can adopt an eligible legacy row and needs separate verification before use as discovery. The roster's `install_id` is an observation from the serving Hermes root. The resolver can mint it on a writable root when it is absent or malformed. An ID can survive a filesystem copy, so host continuity requires separate evidence. [Roster implementation](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_group_controls.py#L389-L450) · [Legacy adoption fixture](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_bot_roster_fleet.py#L94-L102) · [Install identity resolver](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/install_identity.py)

### Current-Pin Desktop Profile Routing

Five [Desktop route composition tests](../tests/desktop/test_profile_route_composition.mjs) passed with Node.js `26.12.1`. They ran the roster, route projection, SDK request and Bot Mode routing modules from clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` with synthetic inputs and substitute store and transport boundaries. The composition tests leave Electron IPC, the renderer gateway pool, backend reachability and owner continuity unexercised.

| Fixture case | Observed result |
| --- | --- |
| Two connections expose the same Desktop profile name and different backend profiles | The inventory keeps both source-qualified routes without exposing credentials. Bot Mode sends each request through its own `connectionId` and Desktop `profile`, with the RPC's `profile` operand rewritten to the corresponding `targetProfile`. A direct SDK request preserves its supplied RPC parameters. |
| Remembered offline SSH profile and cold SSH inventory | The cached profile and cold `default` route each produce one request for their own connection and backend profile. Both substitute gateways reject. The request log contains only those two scoped attempts. |
| Incomplete descriptor or ambiguous bare profile | The SDK refuses before calling the substitute gateway. |
| Registered route, replacement target and removed source | The exact registration helper accepts the unchanged descriptor and rejects both the changed `targetProfile` and removal. An explicit SDK request using the removed descriptor reaches only the original substitute gateway, which rejects it. |
| Missing or copied install marker | Two missing install observations leave two route rows. A shared nonempty marker for the same profile collapses the rows to the configured primary connection. |

The pinned Desktop preload exposes `getProfileRoutes` and the scoped dial bridge. Its main process builds the inventory from the connection registry and roster. The SDK's initial explicit request validates the three descriptor fields and sends the call to the gateway store. The SDK checks the exact registered triple before its one explicit-route hydration retry. A saved connection can be repointed under the same ID, so that comparison alone cannot establish backend continuity. [Preload bridge](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/preload.ts#L53-L64) · [Registry inventory](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14284-L14358) · [SDK request and registration check](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-request.ts) · [Hydration retry](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/index.ts#L1098-L1116) · [Connection edits](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L8568-L8589)

The renderer can reuse the exact primary connection or a shared primary backend for another profile on the same source. A failed scope probe can also keep a remote primary on that same source. Inventory can include cached local profiles or an SSH seed awaiting a dial. The copied-marker result means the Desktop inventory can conceal distinct endpoints, even when each endpoint answers for its own canonical chat in a separate test. [Primary sharing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway.ts#L348-L409) · [Inventory projection](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14294-L14351) · [Native endpoint fixture](#current-pin-canonical-bot-chat-roster)

The optional [renderer gateway pool test](../tests/desktop/desktop_profile_route_pool.test.ts) passed its single Vitest case. It runs the pinned registry, route projection, Bot Mode route logic, SDK request helper and renderer store. A test SDK facade forwards to the real request helper. The Desktop bridge and gateway transport are substitutes. Two same-name non-primary routes open distinct pooled entries, use their respective fresh WebSocket URLs from the substitute bridge and send the corresponding backend profile operands. The fixture removes one source from the substitute registry and invokes the renderer's disposal entry point. That entry closes. A later request for it fails at scoped connection resolution, before the WebSocket URL lookup or RPC. The other entry stays open, and the primary, ambient and legacy request paths remain unused.

To reproduce this optional test, use a disposable checkout at the exact Hermes pin with clean tracked files. Set an isolated `HOME` and `HERMES_RUNTIME_DIR` and use Node.js `26.12.1` and pnpm `12.15.0`. From the Hermes root, run `pnpm install --frozen-lockfile --ignore-scripts --filter . --filter '{./apps/desktop}...'`. Copy this repository's `tests/desktop/desktop_profile_route_pool.test.ts` into `apps/desktop/src/store/`, run `pnpm --dir apps/desktop run test:ui src/store/desktop_profile_route_pool.test.ts`, and remove the copied test file after the run. The dependency-free Node composition check runs separately in CI.

The same pin passed 261 distinct upstream cases under Vitest `4.1.12` with Node.js `26.12.1` and pnpm `12.15.0`. The UI project passed 157 upstream cases. The four Bot Mode suites `routing.test.ts`, `data.identity.test.ts`, `data.roster.test.tsx` and `canonical-chat-registry.test.ts` accounted for 81. The SDK `profile-routing.test.ts` and renderer `gateway-profile-request.test.ts` accounted for 49 and 27, respectively, and ran alongside this project's separate pool fixture. The Node-based `electron` project passed 104 cases in `connection-registry.test.ts`. These focused runs used synthetic inputs and did not launch Electron or connect to a live gateway. [Bot Mode suites](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots) · [SDK routing suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-routing.test.ts) · [Renderer request suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway-profile-request.test.ts) · [Registry suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/connection-registry.test.ts)

### Current-Pin Electron Profile Routing

One [Electron profile routing case](../tests/desktop/desktop_profile_route_ipc.spec.ts) passed on Linux with clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, its Desktop and Webapp source builds, Electron `44.9.3`, Node.js `26.12.1` and Python `3.14`. A local disk plugin in the temporary application home exposes the real Desktop SDK to the test. Two native `gateway.run` processes use separate homes and different fixture install markers. Each home has a named `scout` profile and a default profile. Each profile starts with its own hidden `Bot Chat` and synthetic transcript marker. Desktop attaches to the local gateway using a native ticket from the private Unix control socket. A saved URL connection uses a generated fixture token for the second gateway's loopback Webapp listener.

| Fixture step | Observed result |
| --- | --- |
| Enumerate the same profile name across two connections | The real SDK and preload return the same two credential-free `scout` descriptors. The local primary and the saved URL connection have different `connectionId` values. The scoped main-process dial resolves each descriptor to its own native listener. |
| Read each hidden Bot Chat | Each `host.requestProfile()` call sends one exact-title `session.list` request with backend `profile: scout` on the expected WebSocket port and returns that installation's seeded named-profile session ID and resolved ID. The WebSocket URL for the saved connection is also scoped to `scout`. Unique request limits distinguish these calls from background traffic. Neither call selects the default-profile chat. |
| Remove the saved URL connection | The real registry IPC removes its descriptor and closes its retained socket. Native discovery still returns the same instance and listener, and a token-authenticated status read confirms that the removed gateway remains reachable. |
| Reuse the removed descriptor | The SDK rejects with `No connection with id "spare".` and the stale preload URL lookup returns no URL. The preload also rejects an empty connection ID. No matching stale SDK request appears on any recorded WebSocket. The remaining local descriptor still reads its own chat. |

Read-only SQLite checks confirm that the four seeded Bot Chat records and their messages match the fixture and stay unchanged across removal and replay. The scripted loopback provider records zero completion calls. Both owned gateway processes stop cleanly.

The Desktop SDK's `host.profileRoutes()` invokes the preload bridge to obtain descriptors from the main process. `host.requestProfile()` dispatches an explicit descriptor through the renderer gateway pool. For a saved URL connection, the native registry uses the same `profile` and `targetProfile`. The SSH registry can set a different target. Removing a saved connection persists the registry change, evicts its cached metadata and broadcasts the removal to renderer windows. [SDK host methods](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/index.ts#L1346-L1390) · [Profile route projection](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/plugin-profile-routes.ts#L255-L303) · [Registry removal](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14415-L14436)

The fixture checks exact hidden chats that already exist. The separate [canonical roster fixture](#current-pin-canonical-bot-chat-roster) covers missing, inaccessible and degraded roster cases. Authenticated owner binding, trusted caller and worker provenance, and continuity across copied or restored installations require separate host proof. Packaged Desktop installations, the Bot Mode UI, SSH and OAuth remain outside this Electron routing case. [Identity limits](#33-identity-limits-must-remain-visible)

The [acceptance runner](../acceptance/live/run_desktop_profile_routing.py) requires a disposable checkout prepared at the exact pin with the Desktop and Webapp builds, the pinned Python and Node.js runtimes, workspace dependencies and Electron. The runner stages the fixture temporarily in the upstream Playwright harness and runs it under Xvfb with private Linux namespaces and a loopback-only network. It mounts a private `/tmp`. Place the prepared checkout, runtimes and scratch directory outside `/tmp`. Scratch defaults to `/var/tmp`. Run from this repository's root.

```sh
python -m acceptance.live.run_desktop_profile_routing \
  --hermes /path/to/prepared/hermes-agent \
  --hermes-python /path/to/pinned/python \
  --node /path/to/pinned/node
```

### Current-Pin Bot Mode Canonical Chat Refusal and Retry

One [Bot Mode UI case](../tests/desktop/desktop_bot_canonical_refusal.spec.ts) passed on Linux with the exact Hermes source build and one owned native Gateway serving `scout` from a temporary installation. Electron uses the native local private-ticket path and a loopback WebSocket. The fixture clicks the built-in roster's `local::scout` row. A small fixture plugin reads public SDK focus state. The test seeds the hidden named-profile Bot Chat, a visible side thread in `scout` and a hidden default-profile decoy. A native client reads the canonical row before the initial snapshot, allowing the Gateway to adopt the CLI-shaped seed. [Gateway fixture](../tests/desktop/desktop_bot_canonical_fixture.py)

| Roster click | Observed result |
| --- | --- |
| Exact-title lookup returns a typed error | The fixture lets the real named authority find the seeded chat, then raises one `permission_denied` error at the lookup boundary. The renderer receives code `4001` with reason `permission_denied`. It shows the retry notification and sends no `session.info` probe for that chat. |
| Exact-title lookup returns a successful empty list | The same native lookup finds the seeded chat before the fixture replaces the returned rows with an empty list. The renderer probes the roster's existing session ID through `session.info`. The RPC omits the `profile` operand. The authority audit and response confirm `scout` and the live, unarchived `Bot Chat` on the same listener. The UI again shows the retry notification. |
| User retries the same row | The unmodified native lookup returns the seeded `id` and `resolved_id`. The renderer and Gateway observe open requests only for that ID on the `scout` route. The UI focuses that chat and displays its stored marker. The same-profile side thread and default-profile decoy remain unopened. |

The two failed clicks preserve the prior focus and show none of the fixture chat markers. Neither emits `session.create`, `prompt.submit`, `session.resume` or `session.activate`. The test dismisses each retry notification through the UI. Across all three clicks, the read-only SQLite snapshots of session IDs, titles, hidden flags, parent links, messages and admissions stay equal, and the provider records zero completions.

Both faults occur after an authorized native lookup. The case covers Desktop's response to uncertain results for a local, uncompressed chat in a source-built application. The [saved Webapp case](#current-pin-saved-webapp-bot-mode-routing) exercises a separate credential mode. Compressed UI attach, SSH and OAuth UI routes, packaged Desktop, authenticated owner binding and canonical handoff need separate evidence.

Add `--case bot-canonical` to the [acceptance runner command](#current-pin-electron-profile-routing) to reproduce this case.

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, clicking a Bot Mode roster row prepares that row's source and requests `session.list` for the exact `Bot Chat` title with `include_hidden: true`. A lookup error ends that open attempt before the chat creation path, and the roster shows an error notification. When lookup returns the existing canonical row, the UI opens its `resolved_id` when present and otherwise uses `id`. A successful empty lookup with a roster pointer has a separate `session.info` check. [Roster click](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/bot-row.tsx#L217-L247) · [Open and error path](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/roster-actions.ts#L308-L372) · [Registry lookup](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L314-L405) · [Existing chat open](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L680-L721)

### Current-Pin Saved Webapp Bot Mode Routing

On Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, a saved Webapp token connection authenticates at the native Webapp listener and starts on the launch authority with host scope. A browser ticket naming a profile follows a separate admission path that binds its authority. The host-scoped dispatcher routes canonical RPCs to a served sibling when the request carries a `profile` operand. [Webapp socket admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/web_routers/chat_ws.py#L650-L706) · [Profile dispatch](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_controls.py#L287-L324)

The Bot Mode exact-title `session.list` includes the selected backend profile. If the list is empty and the roster has a canonical ID, its `session.info` fallback sends only the ID. Bot Mode's route helper rewrites an existing `profile` operand. The fallback interprets `not_found` as absence and may then enter the create-or-open path, which checks the registry again before requesting creation. These are source-level paths. [Lookup and fallback](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L314-L405) · [Scoped request parameters](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/routing.ts#L151-L161) · [Creation recheck](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L523-L558)

The [Linux Electron fixture](../tests/desktop/desktop_bot_saved_token_refusal.spec.ts) clicks the built-in `spare::scout` roster row with the saved Webapp token connection selected as the primary. Two isolated native Gateways use separate installations and supply the named remote chat and a same-named local decoy. The fixture lets the native remote `session.list` find the original hidden Bot Chat and suppresses that response's rows once. Renderer frames, native authority observations, SDK focus state and read-only SQLite snapshots record the result.

#### Clean-Pin Observation

The clean build sends `session.info` with the roster session ID and omits the `profile` operand. Native audit identifies the saved-token, host-scoped connection and the remote `default` handler. Its `4001 not_found` response leads to a second `profile: scout` exact-title lookup during the same click. The second lookup finds and opens the original `spare::scout` chat without a retry notification. The fixture observes no `session.create`, `prompt.submit`, local fallback or alternate open. The four SQLite snapshots of sessions, messages and admissions remain unchanged, and the provider records zero completions.

#### Review-Only Scope Proposal

The candidate carries the same backend profile in the fallback `session.info` as in the exact-title lookup. The current-pin dispatcher selects the served authority and consumes the `profile` operand before validating that session method's closed parameter set. This is a proposed client-side scope change. [Scoped dispatch](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_controls.py#L310-L334)

The separately built proposal sends `profile: scout` in the fallback probe. Native audit confirms the same saved-token credential class and the named `scout` handler. The successful reply identifies the existing unarchived Bot Chat. The faulted click displays the retry notification, retains prior focus and sends no open, create or prompt RPC. A later explicit click uses the normal lookup and opens the original `spare::scout` chat. The SQLite snapshots remain unchanged and the provider records zero completions. [Review-only patch, build and evidence](../experiments/bot-webapp-canonical/README.md)

The [acceptance runner](../acceptance/live/run_desktop_profile_routing.py) uses `--case bot-canonical-saved-token` for the clean reproduction and adds `--review-proposal` for the separate source tree. Both runs check fresh Desktop and Webapp builds. The clean compatibility pin stays unchanged. Upstream adoption, packaging, compressed UI attach, other credential modes and authenticated owner binding remain separate gates.

### Current-Pin Native Profile Lifecycle

The lifecycle tests use clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` and synthetic profiles. The CLI fixtures run the native profile parser and dispatcher against stopped homes, with service management, shell aliases and skill-sync subprocesses substituted. Network connections, listeners and SDK installation are fenced. The separate refusal case substitutes a live multiplexer response at the control-call boundary. [Native profile lifecycle tests](../tests/contracts/test_native_profile_lifecycle.py) · [Identity settlement test](../tests/contracts/test_native_profile_identity_settlement.py)

For a named profile, native rename moves the home and then rekeys session and routing identity. It records `previous_names` as best-effort metadata. The move can succeed while rekeying remains incomplete. The native `profile migrate-identity <old> <new>` command retries the durable migration independently. The default profile's rename changes only its display name. [Native profile lifecycle](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py#L2213-L2310) · [Profile identity migration](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L29-L85)

Deletion tombstones the named home before removal. Identity purge is a separate operation over name-keyed routing, heartbeats and delivery bookkeeping. It refuses a name that is live again. Creating a new profile under the same name can reuse its locator within the installation. Native `--clone-all` can copy presentation metadata while excluding session history, checkpoints and cron data. [Native creation and deletion](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py) · [Identity purge](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L55-L138)

| Stopped CLI fixture case | Observed result |
| --- | --- |
| Rename an existing Bot profile | The old slug stops resolving and the active profile follows the move. The hidden exact `Bot Chat` keeps its root, compression tip and message. Both session rows' `profile_name` values and the shared route use the new slug. An unrelated shared route stays intact. |
| `--clone-all` into the old slug | The clone shares the renamed profile's display label and `previous_names` and copies a synthetic plugin-data marker. It excludes the source `state.db` and its seeded `cron/jobs.json`. Both profiles are separately listed. |
| Delete the renamed profile with its populated local database | The CLI exits `1` and reports pending settlement because the tombstone prevents the purge from opening the named database. The directory is removed, the active profile resets to `default`, and the shared route has already been purged while the unrelated route remains. `profile purge-identity` succeeds after removal. |
| Recreate that slug after settlement | The new profile uses the same path and install marker and clears the tombstone. Its `previous_names` list is empty. The synthetic plugin-data marker and original canonical root and tip are absent. |

When the substituted live multiplexer declines identity purge, the native delete reports `ProfileIdentitySettlementPending` after removing the tombstoned profile. The shared root's routing, heartbeat and historical session rows remain intact at that point. Two stopped `profile purge-identity` calls settle the exact deleted name idempotently and preserve a similarly named route and heartbeat and the shared session history. A later purge of the now-live recreated slug exits `1` and preserves the new route under the same key. [Identity settlement tests](../tests/contracts/test_native_profile_identity_settlement.py)

A destination routing-key collision in the moved database demonstrates partial rename settlement. The directory moves and the shared root database rekeys, while the CLI warns and leaves the moved database unchanged. An explicit `profile migrate-identity` retry exits `1` while the collision remains. After the fixture removes the synthetic conflicting row, the same native command rekeys the profile's session fields and route, preserves the canonical lineage and message, and is idempotent on another retry. [Identity settlement tests](../tests/contracts/test_native_profile_identity_settlement.py)

The stopped-install fixture closes its authority and session databases before copying the synthetic root. The original and the copy run independently and sequentially with fresh local tickets. `profiles.list` returns matching install markers, profile labels and canonical summaries, including the same root and compression tip. The fixture's authorized `runtime.describe` calls return different runtime instance IDs and profile paths. The roster reads preserve the database snapshots taken after each start. A match on install marker and canonical lineage still leaves the choice of authority unresolved. [Stopped-install roster fixture](../tests/contracts/test_native_bot_roster_asgi.py) · [Identity limits](#33-identity-limits-must-remain-visible)

### Current-Pin Native Backup and Restore

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, a full native backup can archive a regular `install_id` file alongside the SQLite session store. Native import reserves all affected destination homes for exclusive maintenance before publishing archive members. A runtime ownership reservation on a destination blocks import. Import skips volatile files such as `gateway.lock` and `gateway_state.json`. [Full archive selection](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/backup.py#L318-L360) · [Import reservations](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/backup.py#L916-L936) · [Native maintenance fence](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/runtime_ownership.py#L330-L351) · [Import exclusions](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/backup.py#L1007-L1037)

An in-place `state.db` restore preserves the higher of the archived epoch and the readable destination epoch. When the destination epoch is higher, Hermes stages that epoch and the instance marker `offline-restore` before publishing the database. A fresh authority advances the epoch and reconciles started admissions from older epochs before serving. Those interactive admissions become `unknown` under their existing admission IDs. [Epoch staging](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/backup_restore.py#L196-L238) · [Authority startup](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_authority.py#L1441-L1464) · [Admission recovery](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_state_runtime.py#L453-L464)

The fixture runs the native `backup` and `import` subcommand parsers and backend callbacks in process on disposable local homes. It uses a real full ZIP archive, native profile ownership locks and native authority startup. It calls the native roster reader directly and supplies a synthetic profile-scoped actor and instance IDs. The fixture substitutes service revival and fences subprocess, network and turn execution. [Native backup and restore contract test](../tests/contracts/test_native_bot_backup_restore.py)

| Fixture case | Observed result |
| --- | --- |
| Full archive of the synthetic installation | The archive includes `install_id` and both the default and named profile session databases. It also contains the source `gateway_state.json` and named `gateway.lock`, which import excludes from publication. |
| A runtime reservation holds the named destination | `import --force` exits `1` before publishing archive members. The compared root config, marker, runtime state and both database files remain byte-for-byte unchanged. The root lock becomes available again while the named reservation remains held. |
| Stopped import into the original root | The archived config, data marker and transcript return. The existing `gateway_state.json` and named lock inode stay in place. The named database keeps its later destination epoch with instance marker `offline-restore`. |
| Stopped import into a separate root | The restored root carries the same install marker and the named database starts from the archived epoch. The named lock records the new home, the source `gateway_state.json` is absent and the archive bytes stay unchanged. |
| Startup on the two restored roots | The authorities start sequentially with distinct fixture instance IDs and advance their own epoch floors. Both expose the same hidden Bot Chat root and compression tip to the scoped roster reader. The authorized logical root still resolves to that physical tip. The previously started admission becomes `unknown` under its original ID and the follower stays `queued`. An old-epoch claim returns `stale_epoch`. A current-epoch claim returns `unknown_execution` while the unresolved row blocks the FIFO. |

Each native maintenance lock covers its own destination home. The epoch protects claims in that destination database. Automatic continuity across restored roots requires independent authentication and a fence outside the copied data. The proposed binding policy sends ambiguous restores to owner-reviewed recovery. [Identity limits](#33-identity-limits-must-remain-visible)

Live Desktop routes and profile transitions, authenticated continuity across restores, supported caller and worker provenance, and broader delivery receipt reconciliation remain open under E0.7. Optional HTTP still depends on E0.6. Owner-authorized enrollment, active binding and reconciliation remain separate work under E1.6 and E3.6. [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)

## 3. Identity, Storage and Scope

### 3.1 Three distinct identities

1. **Human authority:** the verified owner/principal and current grant/policy from E1. A local CLI operator, profile name, Bot label, `is_bot` flag or client JSON is not this identity.
2. **Native target:** an authenticated host route, install observation, backend profile and canonical session lineage. Client-side `connectionId + profile` addresses a registry route; `targetProfile` may differ. Connection IDs are client-local, not portable server IDs [B3].
3. **Plugin enrollment:** a random plugin-owned `enrollment_id` and `binding_id`, stored in the selected profile's plugin database. These identify the enrollment, not a host-issued identity, secret or permission token.

The backend derives its profile scope from verified host context. It must not accept an arbitrary filesystem home from a request. `ctx.profile_name` is a convenience label, not sufficient authentication; in this pin its error fallback can be `default` [B2]. Missing trusted identity/scope blocks protected binding work.

### 3.2 Proposed records

```json
{
  "schema_version":"personal.primary_binding.v1",
  "binding_id":"bind_example",
  "enrollment_id":"enroll_example",
  "owner_id":"owner_verified",
  "authority_id":"authority_example",
  "binding_epoch":1,
  "revision":1,
  "state":"active",
  "target":{
    "observed_install_id":"opaque-host-install-id",
    "backend_profile":"personal",
    "canonical_root_id":"session_example",
    "resolved_session_id":"session_tip_example"
  },
  "continuity_mode":"shared_domain_separate_transcripts",
  "policy_revision":31,
  "confirmed_by":"verified-principal-ref",
  "confirmed_at":"2026-11-06T10:00:00Z"
}
```

This illustrates a future active record, not current readiness. `authority_id` identifies this plugin-owned policy/domain store, not a second runtime or global registry. The authenticated local server associates the record with its own storage home; paths and credentials are absent from client DTOs. A client stores its route descriptor separately and resolves it again when connecting.

Use one active binding per owner in this authoritative store, enforced by a database uniqueness constraint. Never claim installation-wide or cross-machine singleton enforcement from a profile-local database. V1 supports one explicitly designated authoritative store, not active-active copies. Enabling the package in another profile does not enroll it or copy grants.

Additional proposed records are `binding_proposals`, `binding_audit`, `session_roles`, `worker_handoffs` and `delivery_correlations`. References include binding epoch, policy revision, native session/run IDs and immutable operation IDs. Reuse the domain/outbox/audit mechanisms in [04](04-domain-data-and-memory.md) and [05](05-automation-and-delivery.md), not a second transcript store or scheduler.

### 3.3 Identity limits must remain visible

An install ID file or plugin enrollment can be copied with a backup. Verifying a restored or cloned host requires independent continuity evidence. `previous_names`, paths and matching labels are locator metadata. A fresh profile with an old name must not inherit an enrollment merely by name. [Native backup and restore evidence](#current-pin-native-backup-and-restore)

Automatic recovery requires current authenticated target evidence, a readable expected install identity, the expected enrollment, canonical lineage and no conflicting authority observation. A changed profile locator, lost enrollment, install mismatch, duplicate identity or unexplained lineage requires owner-reviewed recovery. If the host cannot distinguish a clone from the original, report `identity_ambiguous`; do not invent certainty. Protecting against malicious same-user code or concurrently running cloned disks needs an external fencing authority and OS isolation, outside v1.

## 4. Enrollment and Control Contracts

### 4.1 Initial binding

1. Discover accessible native Bot/profile routes. Show friendly label, machine/connection, backend profile, availability and whether an existing canonical Bot Chat can be verified. Metadata-only discovery is not permission to read its history.
2. Verify the selected route, current owner authorization and plugin presence in that profile. Missing installation/consent is an explicit setup step. Never silently enable a plugin across all profiles or copy provider credentials.
3. Resolve the existing canonical Bot Chat through an adapter proven at E0.7, preferring the verified native canonical registry/roster's root ID and lineage. The native wire path also supports authorized `session.list` title lookup; exact `root_title == "Bot Chat"` (or exact `title` on a verified older shape) is a compatibility filter, not an identity or owner-authorization proof. Reject generic numbered-title matches. Record root and current lineage tip separately. If trustworthy registry/provenance is unavailable, keep the capability unavailable; a matching title cannot replace it. An RPC error, missing access, or an empty result following prior positive evidence is **unknown**, not permission to create a new chat [B10].
4. Prepare a short-lived binding proposal with exact target, enrollment, expected revisions, data/role scope and evidence. It performs no external send and does not change the active binding.
5. Show the verified owner a nonce-bound preview. Confirmation is one transaction: check current identity, expiry and revisions; consume the proposal; establish the unique binding; increment the binding/policy fence as appropriate; persist audit/change rows. Duplicate confirmation returns its original receipt.
6. Advertise only capabilities whose independent gates pass. An active binding may still have controlled writes, worker launch and proactive delivery disabled. Selection alone never enables them.

V1 selects an **existing Bot and canonical chat**. If no verified Bot Chat exists, direct the owner to native Bot Mode setup and retry. This plugin does not silently create/retitle a session or write `ui_meta.hermes-bots` to fake membership. Headless enrollment is supported only after the same native identity/session contracts are proven; a configured `bot_mode_protocol: true` alone is insufficient [B8].

### 4.2 Proposed service methods

These are internal domain-service contracts shared by future CLI, native UI and optional HTTP adapters, **not existing Hermes RPC names**. UI selection may use native read APIs, but mutation still enters the owner-verified binding service. The current local task CLI does not expose these methods.

| Proposed method | Input and output |
|---|---|
| `primary_binding.inspect` | Authorized current binding, health, release gates and ETag; no tokens or home paths |
| `primary_binding.propose` | Server-resolved target candidate and requested scope; returns proposal ID, exact preview, expiry and one-use presentation |
| `primary_binding.confirm` | Proposal ID, presentation nonce, expected revision and idempotency key; returns binding receipt |
| `primary_binding.pause` | Current binding If-Match and reason; commits a new fence and stops new binding-dependent admissions |
| `primary_binding.resume` | Current revision plus fresh owner confirmation after target/policy checks; not a worker/model command |
| `primary_binding.recover` | A prepared recovery proposal for the same enrollment; returns confirmed mapping or an explicit blocker |
| `primary_binding.retire` | Current revision and owner decision; leaves a durable tombstone, invalidates binding grants/presentations and reports in-flight work |

Preparing a proposal requires current owner access and `personal.primary_binding.manage`, but no prior confirmation of that still-uncommitted proposal. Committing enrollment, recovery, pause/resume or retirement requires that scope **and verified owner confirmation** of the exact preview. Scope is necessary, not sufficient. Presentations reuse [14](14-client-api-contracts.md)'s 256-bit nonce, five-minute default expiry, principal/payload/revision binding and single-decision rules. Automatic protective suspension/fencing may remove authority without waiting for confirmation; it may never grant authority or resume a binding. Models/workers cannot mint proposals that confirm themselves. Server-side resolution rejects client-supplied principal, authority, epoch, grant or filesystem path fields. Apply [14](14-client-api-contracts.md)'s idempotency, authorization, ETag and error conventions; internal binding commands use a stable owner/authority/method/key namespace with one decision per proposal, while an HTTP facade retains [14](14-client-api-contracts.md)'s owner/profile/method/route/key transport namespace. Binding changes never renew an expired approval.

An optional HTTP/UI facade remains gated by E0.6/E6.5 and trusted principal propagation. The isolated hosted HTTP admission boolean is not enough. A native channel/CLI binding adapter still needs its own E0.7/E1 identity proof; local process access is not a substitute.

## 5. Lifecycle, Recovery and Rebinding

The persisted binding states are `unbound → active ↔ suspended → retired`; `active` or `suspended` may enter `recovery_required`. Proposals are separate records (`pending | confirmed | expired | cancelled`), so opening a picker never removes a working binding. `retired` is terminal for that binding ID. Health is separate (`verified | offline | incompatible | identity_ambiguous | storage_unavailable`) and never grants authority.

Owner-confirmed recovery returns `recovery_required → suspended` after identity and reconciliation pass. It may commit `active` in the same decision only when the exact preview explicitly included resumption and every relevant gate now passes; otherwise a later owner-confirmed resume is required. Retirement first commits the protective fence, then the terminal binding state; unresolved in-flight effects remain in the ledger rather than disappearing with the binding.

| Change or failure | Required behavior |
|---|---|
| Connection alias/URL changes, same authenticated host and profile | Re-resolve the registry route and verify enrollment; update client routing only; do not increment authority for a cosmetic label |
| Bot display title/avatar changes | Display refresh only; do not rewrite permissions or select a different Bot |
| Compression advances the canonical tip | Follow host-proven lineage from the same canonical root; keep binding ID/epoch and logical operation IDs |
| Profile slug/path rename | Enter recovery until host migration, same enrollment and owner-reviewed new mapping are verified; aliases alone are insufficient |
| Canonical chat archived, deleted, renamed or displaced by handoff | Stop canonical-target delivery, retain domain work; require explicit recovery confirmation for the replacement root; increment epoch |
| Gateway restarts or connection drops | Mark offline; preserve receipts; reconnect to the verified authority and reconcile before resubmission |
| Profile deleted/recreated, enrollment lost, wrong install, duplicate clone | `recovery_required`; no name-based inheritance, auto-create or cross-profile fallback |
| Plugin disabled/unloaded or worker skips hooks | No new plugin-controlled admission; write paths without independent enforcement remain disabled; do not claim other host tools stopped |
| Older/incompatible host loses a required capability | Mark incompatible and disable the affected feature; never downgrade into raw DB edits or a second agent loop |

The target resolver runs before each admission/delivery, not only at enrollment. On a mismatch it atomically fences new plugin-owned admissions. Executors check current binding epoch and policy at each controlled effect, including ordinary workers with frozen startup config. Revocation/admission ordering follows [06](06-plugins-mcp-and-security.md); already admitted remote work may remain in flight and must be reported truthfully.

### 5.1 Rebinding within the same authority

Repairing the same profile's canonical chat is a reviewed recovery operation, not an ordinary session switch. Pause admissions; inspect pending approvals, queued deliveries and workers; verify the replacement canonical root and source evidence; confirm the exact preview; atomically increment epoch, invalidate stale presentations and update mapping. Old results remain queryable as historical evidence. Pending work is re-evaluated, never silently forwarded to the new chat. Resume only after reconciliation.

Changing the profile or host changes the storage/authority boundary. It must not be implemented as editing `backend_profile` on a live record.

### 5.2 Replacing the Bot or migrating hosts

V1 has **no automatic cross-profile/cross-host takeover**. Use a separately tested, owner-directed export/import migration under E8.3:

1. Freeze the source binding and persist its new fence. Stop new domain admissions and scheduled delivery mappings; reconcile/cancel workers and queued effects. Refuse migration while uncertain effects cannot be safely accounted for.
2. Export only explicitly selected plugin-domain data, immutable IDs and receipts with a versioned manifest/checksum. Do not copy host credentials, owner grants, approval nonces, transcript DBs, plugin enrollment or native runtime ownership. Authorization to change the primary Bot is not blanket permission to copy all private data.
3. Prepare the destination under its verified owner and fresh enrollment/authority. Import with an idempotent migration ID; preserve historical object/effect identity and source authority, while unresolved native references remain disabled until mapped. Imported approvals/grants cannot execute.
4. Verify source retirement/fencing and destination reconciliation, then obtain explicit destination activation confirmation. Only the destination becomes active; preserve the source tombstone. If a step fails, remain suspended and offer a verified rollback/recovery plan, never automatically activate both.

This is a stop-before-start protocol, not an atomic distributed transaction. If the source is unreachable or retirement cannot be proved, takeover is blocked pending operator recovery. Restoring a backup requires an explicit recovery procedure that fences old policies before enabling writes; a database restored with its old epoch cannot detect its own rollback. Forked concurrent restores are unsupported without an external authority. No broad host/worker isolation is implied.

## 6. Roles, Delegation and Context

| Server-derived role | Allowed responsibility | Not implied |
|---|---|---|
| `primary` | Verified canonical Bot Chat coordinates domain work and reports results | Permission to approve itself or bypass action gates |
| `owner_entry` | An owner-verified ordinary/Desktop/mobile session may inspect or submit within its grants and link domain tasks | Becoming canonical, inheriting all transcripts, or changing the primary binding |
| `worker` | Native child/run with a recorded task handoff, minimal data and a specific result contract | Full owner memory, binding management or delegation beyond its grant |
| `specialist_bot` | Explicitly authorized separate profile/connection receives a scoped collaboration request | Owner identity, universal access, or automatic membership in E9 routing |
| `observer` / `untrusted` | Only permitted public/source-scoped observation or evidence ingestion | Personal-domain mutation, owner approval or private context |

Roles come from verified runtime/session/worker provenance plus the binding record, never a prompt, tool argument, chat title alone or `role:"primary"` in JSON. A message in the canonical chat may still be bot-authored, scheduled or third-party. **Conversation role and message author are independent.** Each action must retain the true author, source, grant and current policy.

The proposed handoff carries `binding_id`, `binding_epoch`, `task_id`, `attempt_id`, authoritative parent/native refs, scope, budget/deadline, expected result and grant references. A worker result is evidence, not a user instruction or task acceptance. The primary/domain acceptance service verifies it. Delayed results from old epochs may be retained for reconciliation but cannot reopen authorization or automatically reach a new target.

Use native delegation/lifecycle for short work and Kanban for durable work. Persistent specialist Bots can use native `message_agent` when supported and authorized. Its response reports handoff or admission for the route used. Turn completion requires a later outcome. Apply native loop guards plus plugin budgets and sender/destination policy. E9 chooses permitted worker model/effort routes. Primary Bot selection and model configuration remain separate, as do Bot, cron and Kanban paths outside the worker routes.

Plugin loading can affect every session in a profile. The initial integration chooses minimal tools at supported creation/rebuild boundaries and rechecks roles in domain handlers. Hooks that fail open or workers that skip plugin hooks cannot be the sole role/authorization boundary. Unknown provenance blocks protected operations. E0.7 must expose any missing normalized session/author/worker context as a tested adapter or upstream gap.

### Current-Pin Subagent Correlation

Two [native plugin contract cases](../tests/contracts/test_native_plugin_subagent_provenance.py) passed on clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` with Python `3.14`. The fixture discovers a synthetic plugin in temporary named profiles. Two actual `AIAgent.run_conversation` turns call its registered model-facing tool. The first launches one native child through public `ctx.subagent_lifecycle`. The `in_process` plugin runs in the agent process. The `host` plugin runs in a separate native process over stdio, and the child runs in the agent process. A scripted nonstreaming inference boundary returns synthetic responses. [Fixture code](../tests/fixtures/native_plugin_subagent_probe.py)

| Exercised surface | Observed result |
| --- | --- |
| Launch within the active parent turn | In both isolation modes the handle carries the active parent session ID, the requested correlation ID and a native `leaf` role at depth `1`. The child's tool catalog includes the requested no-op and excludes the parent launcher. The bounded wait returns `SUCCEEDED`, repeated result reads agree on the hash, and `reconnect` succeeds in the same active parent turn. SQLite contains one child with the expected parent ID and synthetic reply. |
| Wrong parent, altered handle or call outside a turn | Launch refuses an explicit parent that differs from the active parent. `status` returns `UNKNOWN_HANDLE` for an altered handle capability. Outside a native turn, registry dispatch can pass the same `session_id` to the tool, but launch still refuses because no active parent exists. |
| A different active parent reuses the genuine handle | `status` returns `UNKNOWN_HANDLE`, `result` yields no ready result and `reconnect` returns `RECONNECT_UNAVAILABLE`. Across both parent turns, only the expected child is created. |
| Profile-scoped plugin state | `scout` writes and reads back a synthetic marker through `ctx.state` in both modes. In hosted mode, a fresh agent process and plugin host for `reviewer` write a different value with the same plugin namespace and key under the same synthetic installation. Both profiles retain their own JSON values, and the installation root has no plugin state file. |

A managed-sandbox run stalled in native Relay startup and timed out. The isolated Linux run retained native Relay and verified that only the inactive test configuration applied. Per-process Python audit fences restrict sockets, DNS and unrelated process launches. Before launching the native plugin host, the fixture checks that its environment preserves the isolated profile and audit startup paths.

The pinned source exposes session, conversation, task, turn, tool-call and API-request identifiers in tool hooks when available. `pre_llm_call` obtains `parent_session_id` and `sender_id` from the current agent, with an empty string when absent. `subagent_start` exposes the native child ID and effective role. `subagent_stop` reports the child session and outcome. These hook payloads are source evidence. [Tool hook fields](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/model_tools.py#L664-L676) · [Turn hook fields](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/turn_context.py#L903-L928) · [Delegation observers](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/website/docs/user-guide/features/hooks.md#L1181-L1275)

The public `ctx.state` facade stores plugin-owned JSON under the active profile's home. In hosted isolation, state methods run through the Hermes-side facade. `ctx.profile_name` reflects the home-derived profile, with a `default` fallback, and the hosted context receives that value at load time. Profile-scoped storage establishes where the plugin reads and writes its state. Protected reads, writes and role grants require independent caller and owner proof. [Public plugin state](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/website/docs/developer-guide/plugins/index.md#L978-L994) · [State scope](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_state.py#L134-L195) · [In-process profile](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_context.py#L207-L216) · [Hosted context](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugin_host.py#L230-L246)

The native `ctx.subagent_lifecycle` service checks its handle against the active parent session and process registry. Children run in process, including when a hosted plugin accesses the Hermes-side facade. Durable restart recovery, an authenticated caller, an owner-bound worker grant and current revocation require separate evidence. The [existing E0.4 worker checks](13-enforcement-contracts.md) cover frozen configuration and troubleshooting-safe plugin suppression. Gateway-managed worker adoption and Kanban worker provenance are separate runtime paths. [Lifecycle service](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/subagent_lifecycle.py#L269-L290) · [Handle checks](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/subagent_lifecycle.py#L389-L400) · [Hosted facades](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugin_isolation.py#L58-L61)

### Current-Pin Same-Install Bot Messaging

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, tool injection checks the Bot Mode protocol setting, the exact `Bot Chat` title and the managed-install marker. The tool handler rechecks the title and marker. When the caller has a session database, its home supplies the sender profile. The profile slug determines the structured author ID `bot:<profile>`, and the roster supplies the handle and display metadata used in the message prefix. These values come from the host's calling context and roster. [Tool eligibility](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L127-L168) · [Sender attribution and local routing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L239-L364) · [Calling agent context](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L1008-L1025)

The receiving authority normalizes the author supplied in `bot_relay.deliver` as attribution. It derives the mailbox `principal_id` independently from the authenticated RPC caller. For a canonical LOCAL recipient, the target FIFO uses an `automation:<session_key>` producer and carries the author under `local_automation_v1.turn_author`. For a same-install notify-only send, the tool can return the authority's queued status after durable admission and remove its temporary payload and intent without starting a reply waiter. [RPC author parsing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L805-L828) · [Mailbox admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L955-L1000) · [Automation snapshot](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L549-L565) · [FIFO admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L605-L636) · [Notify-only result](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L762-L799)

The fixture uses a synthetic named sender backed by a real session database and a separate default-profile Bot Chat on the same temporary installation. It exercises tool injection and the native sequential route selector and inline executor, then `GatewayClient`, private control ticket issuance, `/api/ws` redemption and the receiving authority. The fixture supplies endpoint discovery and a synthetic local peer subject and bridges control and WebSocket traffic in memory. [Notify-only contract test](../tests/contracts/test_native_bot_notify_only.py) · [Sequential route selector](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tool_executor.py#L1674-L1685) · [Native inline executor](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/inline_tool_executors.py#L296-L303)

| Fixture case | Observed result |
| --- | --- |
| Ordinary session in the sender profile | Tool injection is refused. Direct invocation through the inline executor returns an error before endpoint discovery, ticket issuance or admission. |
| Named Bot Chat sends to `@hermes` | The default profile's canonical Bot Chat receives one queued admission. The message starts with `Message from 🤖 Scout Fixture (@scout): [no reply needed]` and its structured author is `bot:scout`, name `scout`, `is_bot: true`. The local ticket subject and FIFO producer remain separately recorded. |
| Durable receipt and event reconstruction | The tool reports `queued` and `expects_reply: false`. Its delivery ID matches the pinned intent, mailbox receipt and FIFO request `bot:<delivery_id>`. The native reconstruction helper returns the same author and internal event marker from that queued row. The sender's temporary payload and intent are removed. The compared sender database rows stay unchanged, the recipient transcript stays empty and the authority records one scheduling request. |

The fixture holds the recipient turn queued and fences reply waiters. The evidence covers same-install Bot attribution and local operator admission. A separate fixture exercises the local process transport and terminal receipt. Verified human ownership, supported plugin caller and worker provenance, real-provider execution, reply delivery, installed distribution and cross-machine messaging require separate verification. [Local Bot transport and restart](#current-pin-local-bot-transport-and-restart)

## 7. Cross-Device and Platform Continuity

Default: **shared domain, separate transcripts**. Desktop Bot Chat, Telegram DM, Discord thread and CLI scratch sessions can refer to the same authorized tasks/projects without copying their conversations or pretending they share a prompt. Context is rebuilt from bounded, permission-filtered domain facts and explicit task links. User text from one route is not silently replayed as a fresh command on another.

If the user explicitly wants the same native conversation, use a supported canonical attach/handoff path and test ownership, ordering and recovery separately. `gateway.profile_routes` does not provide a target canonical session ID. Do not implement transcript merging, direct SessionDB writes or an API-server shadow conversation to approximate continuity.

For a messaging entry, prefer one unique platform credential owned by the selected Bot's profile. A shared bot can route selected chats to another runtime profile, but authorization/replies still depend on the receiving transport. Store both verified transport and runtime references in channel bindings. `SessionSource.is_bot` describes the **sender**, not which Bot received it. Do not claim bot-level separation when two bots are deliberately routed to the same runtime profile and otherwise identical session key [B7].

Group/shared channels never receive private canonical summaries by default. Delivery selects a verified authorized route for that specific content. Returning a status to the owner in the originating session is distinct from starting a new canonical Bot turn; neither happens twice merely to keep screens synchronized.

## 8. Messages, Routines and Receipts

Use one owner for each delivery. A domain notification stores its intended binding/epoch, destination, content revision, policy scope and stable effect ID before admission. At dispatch, resolve the current canonical/transport target and recheck permission. Target changes pause/review the old effect rather than retargeting it silently. Native cron's delivery and the plugin outbox must not both send the same result.

Native `bot-chat[:profile]` delivery is machine-local and enters the existing Bot authority. The scheduler can durably defer a delivery that has yet to be admitted when the owner is unavailable, then retry with the same delivery ID on a later tick. If an admission response is lost, the scheduler's pending record can still be `queued` after the authority has committed admission. Preserve both native references and distinguish transfer and admission from queued, running, waiting, completed, failed and unknown execution outcomes. Reconcile uncertain claimed work under its existing identity [B9]. Cross-machine Bot delivery requires a separately verified authorized transport. A fallback CLI writer against the same transcript is forbidden. [Current-pin receipt evidence](#current-pin-deferred-bot-chat-delivery)

`ctx.inject_message(..., session_key=...)` returns a boolean and exposes neither a caller-supplied delivery ID nor a durable receipt lookup. At the current pin, the upstream gateway scheduler test returns `True` before its asynchronous dispatch raises. An uncertain submission needs a stable receipt-bearing adapter before it can be reconciled safely. Durable proactive activation remains blocked without that supported adapter. [Plugin API](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_context.py#L395-L402) · [Upstream scheduler test](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_plugin_message_injection.py#L341-L368)

Scheduled and specialist output keeps source attribution. A routine cannot label its own content as a direct owner request to obtain authority. Reminders to the owner and actions on third-party services remain separate effects with separate grants. A Bot binding does not automatically authorize proactive contact, cross-Bot sharing, new costs or external writes.

### Current-Pin Deferred Bot Chat Delivery

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, the cron drain leaves a pending file `queued` when delivery raises an error. On a successful response it records `transferred` and copies the returned status to `receipt_status`. Before returning an existing receipt for that delivery ID, the authority checks the message, submitting principal, author and notification category. `transferred` records the scheduler's handoff. The receipt carries the authority's disposition, and turn execution and completion have their own outcomes. [Native cron drain](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/cron/bot_chat_legacy.py#L64-L123) · [Native receipt handling](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L795-L876)

The contract fixture sends a synthetic cron result to the same local profile. It exercises the native cron delivery helper and drain, `GatewayClient`, the private `session-ticket` handler and ticket redemption at `/api/ws`, and `bot_relay.deliver` on the native authority. The fixture supplies endpoint discovery and the local peer subject, bridges the control and WebSocket traffic in memory, and runs both event loops with the bounded test driver. [Deferred receipt contract test](../tests/contracts/test_native_bot_deferred_receipt.py) · [Native authority client](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_live_delivery.py#L71-L119) · [Private control handler](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/control_socket.py#L333-L410)

| Fixture step | Observed state |
| --- | --- |
| Endpoint reported stopped | Cron persists one `queued` record under the delivery ID derived from the execution and target. The authority mailbox and canonical admission queue are empty. |
| Endpoint reported ready, then first successful response dropped | The gateway emits a `queued` receipt before the bridge drops the response. The mailbox and canonical FIFO row `bot:<delivery_id>` agree on one admission ID. The client observes a disconnect and the cron record remains byte-for-byte unchanged at `queued`. |
| Later drain replays the delivery | With a fresh `interactive` ticket, the client sends the same delivery ID, profile, canonical session and message. The authority returns the existing receipt and the cron record becomes `transferred` with `receipt_status: queued`. |
| Drain runs again | The transferred record triggers no further handoff. The fixture still has one canonical session, one receipt, one queued FIFO admission and one scheduling request. The admission has no terminal outcome, and the transcript stays empty. |

The fixture holds the admitted turn queued and exercises synthetic local operator admission and receipt handling for cron. The public plugin API exposes the boolean injection path described above.

### Current-Pin Local Bot Transport and Restart

On Linux at Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, the native private Unix control connection checks the listening process's user. The gateway checks the caller's kernel-reported UID and mints an `interactive` ticket for the current runtime instance and profile. The native loopback `/api/ws` connection redeems that ticket for local operator access. The mailbox principal comes from that grant. The delivery envelope carries Bot authorship as attribution. [Private client peer check](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/gateway_runtime_discovery.py#L106-L140) · [Control ticket and caller UID](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/control_socket.py#L381-L436) · [Native ticket redemption](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/run_api.py#L450-L490)

The mailbox projects a committed completed admission as `settled` and obtains the reply from that admission's saved result. Native startup can reconstruct that projection from the same admission, and an exact `bot_relay.deliver` replay reads the existing receipt. The replay checks the message, submitting principal, author and notification category. [Terminal result projection](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L408-L442) · [Startup mailbox recovery](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L728-L751) · [Replay identity and receipt](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L795-L861)

The Linux acceptance fixture starts the native `gateway.run` entry point twice in a temporary standalone home. The synthetic named sender runs in the fixture process, using a real session database and the native inline `message_agent` path. The client uses native discovery, the private Unix socket and an actual loopback WebSocket. A scripted loopback model returns a fixed synthetic reply. The recorder counts `/v1/chat/completions` and handles bounded model metadata probes separately. The fixture supplies a fabricated model credential. A Python socket audit fence limits the gateway children's outbound connections to fixture Unix sockets and that model endpoint. [Local Bot receipt acceptance test](../acceptance/live/test_native_bot_receipt.py)

| Fixture step | Observed result |
| --- | --- |
| Open the local gateway | Private discovery identifies the owned gateway process. A WebSocket upgrade without a ticket is refused. A native interactive ticket opens `/api/ws` and can create the hidden default-profile Bot Chat. |
| Notify-only send to the default profile | A named Bot Chat sends to `@hermes`. The tool returns a delivery ID and `expects_reply: false`. The receiver stores `bot:scout` separately from the local UID principal and keeps it in the FIFO's turn-author metadata. The SQLite admission reaches `terminal` with `outcome: completed`. The mailbox becomes `settled` with the same admission ID and the exact saved reply. |
| Stop the gateway and make its mailbox projection stale | Both planned stops exit successfully, remove the PID marker and leave discovery absent and the listener closed. Between the two processes, the fixture sets the mailbox status to `queued` and clears its projected reply. The committed SQLite result still holds the original reply. |
| Restart on the same home | Native discovery reports a different runtime instance and a higher epoch. By readiness, startup has restored the exact original `settled` receipt before the fixture requests another ticket or replays the delivery. The private control socket refuses a ticket request for the prior instance. |
| Replay with the original delivery ID | A fresh local ticket and an exact replay return the repaired receipt. The same delivery ID with a changed message returns `admission_conflict`. The read-only SQLite check still reports the same single admission. The recorder counts one synthetic completion request carrying the Bot message across both processes. |

The fixture observes a local operator credential, one synthetic recipient turn and receipt recovery across a clean restart on the same home. This credential mode supplies current runtime access. Authenticated human ownership, cross-install continuity, installed-package Bot receipt behavior, delivery from Electron, other OS control transports, remote token, OAuth and SSH delivery modes, worker provenance and reply delivery to a user require separate evidence. [Restore identity limits](#33-identity-limits-must-remain-visible)

The manual workflow runs this case as its own step on the exact pin. It stages a clean `bot-receipt.xml` only after a passing, nonempty result with no skips. Routine pull request and push checks cover the in-memory Bot contracts. Installed-package task, memory and handoff checks have separate workflow steps. [Native Gateway acceptance workflow](../.github/workflows/native-gateway.yml)

## 9. Events, Errors and Client Recovery

Proposed durable invalidations are `primary_binding.changed`, `primary_binding.suspended`, `primary_binding.recovery_required`, `primary_binding.retired` and `primary_delivery.updated`. Use the same committed domain sequence/outbox as [14](14-client-api-contracts.md); do not create a parallel event bus as the authority. The snapshot includes the authorized binding summary. Optional live hints only request a refetch.

Payloads carry IDs, revision, epoch and reason codes, not transcripts, nonces, credential values or filesystem paths. A client receiving an epoch change discards stale binding-specific approval presentations and re-reads current grants; an event cannot supply a grant. Offline selection remains a draft, never a queued binding confirmation.

| Code | Meaning and recovery |
|---|---|
| `primary_unbound` | No confirmed primary; use authorized setup, not the default Bot |
| `primary_target_unavailable` | Known target offline; show last verified state as stale and reconcile |
| `primary_identity_ambiguous` | Conflicting host/profile/enrollment evidence; require owner recovery |
| `primary_canonical_unverified` | Canonical registry/lineage cannot be proved; no fallback creation |
| `primary_epoch_conflict` | Stale command/handoff; reload and re-evaluate, do not reuse old approval |
| `primary_role_forbidden` | Current verified role/author lacks this operation |
| `primary_capability_unavailable` | Required host adapter missing; keep the feature disabled |
| `primary_recovery_required` | Retirement/rename/restore interrupted continuity; run reviewed recovery |
| `primary_migration_blocked` | Source fencing, unknown effects or destination identity not settled |

Map missing authentication to 401, denied authority to 403, hidden foreign objects to 404, revision/epoch conflicts to 409/412, missing If-Match to 428 and unavailable trusted adapters/storage to 503 as appropriate. Local CLI surfaces use the same stable domain codes without pretending to be HTTP. Never interpret a transient network failure as successful cancellation or absence of a Bot.

## 10. Compatibility and Release Tests

Record native/plugin SHA, host mode, route/connection type, credential class, profile setup, session root/tip, worker mode and every skipped capability. The existing unit/host foundation tests do **not** certify these new contracts. Static document/JSON checks prove only syntax/structure.

| Required synthetic or authorized integration scenario | Assertion |
|---|---|
| Two same-named Bots on different connections; changed route alias | Explicit target identity wins; no active-chat/default/recency fallback |
| Discovery exposes metadata but no session access | Do not read or enroll beyond permission |
| Initial confirm double click, lost ACK, crash during commit | One binding/proposal decision; receipt query recovers; no second enrollment |
| Ordinary session, spoofed title/JSON, bot-authored canonical input, local CLI operator | Role and owner evidence remain independent; no self-approval |
| Concurrent owner/bot/worker work across two profiles | Correct profile policy/storage; no context or permission leakage |
| Compression, restart, failed/empty roster read | Follow proven lineage; unresolved absence cannot mint another chat |
| Profile rename partially migrates; delete/recreate same name | Fail closed until verified recovery; no alias-based inheritance |
| Canonical archive/rename/handoff replacement | Old delivery stops; owner confirms new root; new epoch fences stale work |
| Revocation races dispatch; old worker resumes after binding change | Order by committed fence; old grants denied; report already admitted effects truthfully |
| Bot-to-Bot messages, routine result, forwarded approval | Authorship survives; no owner impersonation or uncontrolled reply loops |
| Same profile across mobile/Desktop; two transport bots routed to it | Explicit task continuity only; no assumed transcript merge or bot-account isolation |
| Lost delivery ACK; native defer; target offline; duplicated cron result | Stable receipt reconciliation and one delivery owner; no competing session writer |
| Snapshot restore, cloned enrollment/install ID, old backup resumes | Recovery required under supported restore procedure; unsupported concurrent clone is not called safe |
| Migration crash before/after source fence and destination import | At most one activated authority in the supported protocol; no automatic failover/dual resume |
| Safe worker, hosted HTTP boolean, missing canonical/profile API | Protected capability disabled; no private import, prompt-only guard or default-owner fallback |

Older hosts may lack route descriptors, canonical fields or normalized provenance. Feature-detect and test supported modes; do not silently fall back to `last_session`, undocumented params or profile-only remote routing. Source examples of gateway topology and offline cron behavior can disagree with older prose: use the pinned implementation and contracts, then revalidate on upgrade. Merely installing a newer Hermes version is not evidence that this binding still works.

## 11. Implementation Work Packages

| ID | Status and dependencies | Deliverable |
|---|---|---|
| E0.7 Verify Primary Bot Contracts | M0, In Progress. Depends on E0.1/E0.2 and uses E0.4 findings. | The [adapter status](#supported-adapter-status) records current-pin evidence and remaining gates. Installed-package and additional remote transports, live profile transitions, authenticated restore continuity, trusted caller and receiver context, managed worker provenance and grants, and broader author and receipt reconciliation remain open. Optional HTTP also needs E0.6. |
| E1.6 Bind Primary Bot | Optional future; Backlog; E0.7, E1.1–E1.5, E2.1 | Owner-confirmed enrollment and recovery, unique active binding, revision/epoch fence, audit and role policy; no unconditional write enablement |
| E3.6 Reconcile Primary Bot Sessions | M1 gate for enabled Bot-bound paths, extended in M2; Backlog; E1.6, E3.2/E3.5, E4.3/E4.4 | Canonical resolution, worker handoff correlation, delivery/recovery and native receipt reconciliation |

Extend E6.1/E6.2 with the selected Bot's verified channel bindings and separate-transcript continuity. Extend E8.2/E8.3 with this failure matrix and reviewed migration/restore; E8.5 documents selection, pause, recovery and limitations. These are additions to the plan, not remote Project item creation or Done status.

E0.7/E1.6/E3.6 are release gates **when Primary Bot capability is enabled**. They do not block the profile-first local MVP or its explicit, no-dispatch task commands. A Bot-bound M1 must pass them for its enabled paths; custom HTTP/PWA/native-phone E0.6/E6.5–E6.7 remain separate optional lanes. Start with one existing Bot, one authoritative profile and one verified owner; defer automatic multi-host migration and broad multi-Bot orchestration.

## 12. Pinned Evidence

- B1: [Profiles, agents and Bots](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/profiles.md#L19-L43) and [Bot Mode lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/bot-mode.md#L8-L45).
- B2: [Plugin context/state/profile and manager scoping](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py).
- B3: [Desktop profile route descriptors and connection identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md#L1446-L1514).
- B4: [Authorized canonical roster and compression resolution](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_group_controls.py#L330-L490).
- B5: [Install ID](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/install_identity.py), [profile metadata](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profiles.py#L646-L678), and [rename/delete identity migration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profile_identity.py).
- B6: [Plugin injection scope, consent and boolean return](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_injection.py).
- B7: [Receiving-bot route discriminator](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/profile_routing.py#L62-L108), [session keys](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session.py#L691-L734), and [transport/runtime identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_identity.py#L43-L83).
- B8: [message_agent eligibility](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_dm.py#L127-L168) and [managed-install marker](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_probe.py#L131-L143).
- B9: [Cron Bot Chat delivery implementation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler_delivery.py#L714-L805), [deferred same-ID admission](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/bot_chat_legacy.py#L24-L100), and [single-authority Bot admission](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_bot.py).
- B10: [Authorized native title lookup](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_controls.py#L567-L596), [canonical UI resolution](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L88-L107), and [uncertain absence handling](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L330-L339).
