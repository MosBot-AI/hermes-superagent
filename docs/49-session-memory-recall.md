# 49. Session-Scoped Automatic Memory Recall

English | [简体中文](49-session-memory-recall-zh.md)

The production plugin can now retrieve relevant local records automatically at the
start of a supported native primary turn, after a separate session opt-in. This
uses the existing host `pre_llm_call` hook, not the review-only worker patch. It
requires no extra provider package, does not replace the selected MemoryProvider,
and makes no extra model request. It is automatic **reading**, not extraction,
canonical memory writing, a conversation archive or checkpoint-v2.

## 1. Enable Only for a Permitted Session

Keep the existing [memory-tool configuration](32-session-scoped-memory-tools.md):
`mode: local_tasks`, `local_conversation: true`, `local_memory: true` and
`memory_model_tools: true`. Nothing changes these settings automatically.
In the trusted native LOCAL session, use:

```text
/personal-memory-tools enable-read
/personal-memory-tools recall-on
/personal-memory-tools status
/personal-memory-tools recall-off
```

`enable-write` can replace `enable-read` when separately desired; automatic recall
never needs write access. `recall-on` requires an already active memory grant and
adds no time to its 30-minute lifetime. Ordinary activation alone does not select
automatic recall. `recall-off` stops new recall without disabling memory tools;
`disable` stops both. Renewing or changing activation requires another explicit
`recall-on`, so an expired or downgraded session cannot silently restore it.
Reload, unload and restart clear all selection and activation state.

The session `status` command reports `recall_enabled`. Global
`personal_agent_status` cannot inspect this session activation: when memory tools
are configured, its `automatic_recall` value is `null`, not a claim that recall is
active. Use the session command to check. No command or status read creates a
missing memory database.

Enabling recall approves sending matching stored records into the session's
configured main model and normal host history on subsequent eligible turns.
Ordinary model input costs and retention apply. All admitted session controllers
share this authority; LOCAL does not prove physical locality or a fresh human
instruction. Task-tool activation is independent and cannot grant memory recall.

## 2. What Each Turn Reads

Only the host's current original plain-text `user_message` becomes the retrieval
query. Conversation history, tool outputs, multimodal payloads, claimed sender
fields and old assistant text are not used to construct queries. Slash commands,
empty/invalid inputs, oversized text and trivial acknowledgements produce no
lookup. Retrieval is bounded literal matching, not embeddings or semantic search.

At most eight distinct literal terms are used. Matching is case-sensitive;
Chinese punctuation and whitespace delimit chunks, not a language model. For
example, a question containing a separate literal term for breakfast can match
a record containing that exact term. A long unsegmented Chinese sentence may not match its relevant substring.
No-match is not proof that a preference or fact is absent.

Recall returns at most six complete current records. The entire escaped JSON
context, including its notice and metadata, is limited to 6,000 characters, not
6,000 tokens. Whole records are omitted instead of cutting text mid-record.
IDs, revisions, editing-route labels, expiry evaluation and omission counts stay
with the records. Stored text is explicitly untrusted evidence, never instructions,
authorization or verified truth. The plugin creates no task, changes no record,
contacts nobody and performs no inferred action from this text.

## 3. Freshness, Revocation and History

Every eligible turn uses a fresh read-only connection to the existing private
store. There is no recalled-payload cache or background queue. A correction changes
the next eligible snapshot; forgetting and expiry exclude the record from new
recall. A write after the SQLite read snapshot may make an already admitted pack
historical. No claim of simultaneous database/model-provider transactions is made.

Admission requires the actual current native turn, exact profile/session/route,
primary CLI/TUI/Desktop context, current configuration, unexpired memory activation
and the explicit recall selection. Child, cron, remote, unbound or hosted-context
calls cannot borrow a parent selection. Configuration or activation changes
observed during reading discard the new pack before it is returned. An observed
revocation clears selection; an unobserved cross-process disable/enable transition
cannot be detected without a host revision fence.

**New recall is not history erasure.** The host can persist returned context in
`api_content` and replay it later. Disabling recall, correcting or forgetting a
record does not remove already supplied text from prior messages, native history,
provider retention, exports or backups. Starting a new session does not delete old
sessions. Do not report that a forgotten record has vanished from every prompt.

## 4. Storage and Provider Boundaries

The recall hook uses the existing canonical-read-only reader. It never creates,
upgrades, repairs or adopts a database, nor advances a memory cursor/checkpoint.
Missing, old, unsafe or unavailable stores produce no memory payload. Initialize
or upgrade an owned store deliberately through the existing operator commands
when authorized; do not copy a foreign database or change permissions to force it.

The selected native provider and its configuration remain untouched. If a user
also selects the separate `personal-records` provider, both independently enabled
recall routes can supply overlapping context; choose one automatic route if that
is undesirable. There is no hidden provider replacement or deduplication claim.
Other providers and tools retain their own behavior and permissions.

The current reader's documented SQLite/WAL race limitation still applies: this
is canonical read-only access, not an OS/VFS sandbox against other same-UID code.
The plugin does not secure unrelated host tools. Unsupported isolated or managed
execution must stay refused; do not disable existing isolation to expose recall.

## 5. Verification and Remaining Gates

Offline tests exercise actual clean pinned host command admission, turn hooks,
context assembly and historical API sidecars with synthetic records. They cover
separate activation, no-read defaults, reload/expiry/revocation, correction and
forget freshness, bounded data, profile/route/child/cron refusals and unchanged
native configuration. Unit tests cover malformed queries and race boundaries.
No live model, provider credentials, installer or Gateway listener is used.

This makes the existing standalone plugin's memory usable without relying on the
model to voluntarily call a search tool. Real-model usefulness, Chinese semantic
recall quality, automatic extraction/review candidates, durable conversation
coverage and native checkpoint-v2 remain separate work. The original denied
installation is not retried or waived by these tests.
