# 43. Native Checkpoint Evidence Boundary

English | [简体中文](43-native-checkpoint-boundary-zh.md)

Current E0.9 update: [76](76-native-memory-contracts.md) places these existing checkpoint contracts in the current Hermes `22811165` verification matrix. The original evidence and source links below retain their historical pin. A verified limitation can satisfy a verification criterion without implementing the missing E2.8 durable guarantee.

Status: pinned-host compatibility tests and an internal, I/O-free evidence preparer are implemented. **No native checkpoint-v2, automatic ingestion or runtime configuration is enabled.** A subsequent internal read-only source resolver is documented in [91](91-native-source-resolution.md); it is not wired into the provider and does not supply durable checkpoint guarantees. The optional [native recall provider](41-native-memory-recall.md) remains API v1. This is a capability-boundary result, not an end-to-end memory checkpoint implementation.

## 1. What the Pinned Host Actually Provides

The tested Hermes commit is `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.

- Native messages have durable `message_uid` values. Reopening the store preserves them; equal text in distinct occurrences has distinct identities. Physical row IDs are not substitutes for those logical identities.
- Native merge bookkeeping retains the first constituent's UID and `_absorbed_message_uids` for other identified constituents. Resume can merge two adjacent user rows into one callback candidate.
- The public `SessionDB` API supports read-only access and `conversation_revision()`. Rewriting content retains its UID but changes the revision; compaction also changes the revision.
- Native pre-compression normalization selects direct user/assistant prose, removes derived summaries and tool-only messages, and strips assistant tool calls. Other dictionary fields, including UIDs, merge lineage, `api_content` and display metadata, can survive. The manager removes withheld-prompt metadata and applies its normal scrubbing.
- A provider can explicitly advertise checkpoint API v2. The required gate propagates its failure. Any normal callback return, including an empty string from a no-op test provider, counts as success; the host does not validate a returned durable receipt.

These are real facilities, not missing-host-API claims. The problem is the relationship between those facilities and the evidence supplied to this callback.

## 2. Why the Existing Handoff Is Insufficient Here

The callback receives normalized message dictionaries and `require_checkpoint`. It does not receive a bound source snapshot, source revision, persistence/resolution interface or checkpoint receipt tied to the compression commit fence. Session/profile initialization does not authenticate every later message dictionary.

Ordinary preflight can contain a current user message that has not yet been persisted. The parent-adoption path flushes pending input only when the durable parent has outgrown the live history. A provider cannot assume that every callback already has complete durable coverage. More subtly, native merge bookkeeping ignores a constituent with no UID: a merged message can carry a valid stored UID while containing additional unpersisted text. Valid UID syntax alone must never pass source verification.

A provider could independently read `SessionDB`, resolve exact content and refuse missing or mismatched candidates. This is feasible groundwork for a narrower durable-only subset. It does not persist pending input, bind that read atomically to the later native commit, guarantee source retention, or recover excluded tool/effect/approval evidence. Two revision reads do not create that binding. Conversely, a provider that explicitly and durably archives the received text can implement the host's narrower v2 promise; this project does not silently introduce a second raw conversation archive to obtain it.

Other boundaries are tested: the hook can run for non-primary contexts; manager session switching does not independently validate the supplied messages' source session; a drained asynchronous sync queue can include failed provider writes. Strict checkpointing remains unavailable for native `codex_app_server` mode. None of these results authorizes bypassing isolation or changing the selected model.

## 3. Implemented Bounded Preparation

`personal_agent.checkpoint_evidence.prepare_checkpoint_evidence()` accepts already-normalized direct-message candidates. It performs no I/O, registers no callback/tool, and is not called by the shipping provider. It produces immutable in-memory candidates for future source reconciliation, not memory facts or durable receipts.

Preparation requires nonempty plain text, user/assistant role, a 32-character lowercase hexadecimal UID and unambiguous ordered merge lineage. It rejects summaries, tool calls, invalid Unicode, missing identities, duplicates and overlapping identities. Limits are 256 candidates, 16,384 characters per message, 65,536 characters total and 1,024 source identities. Oversized or unsupported evidence fails rather than silently truncating coverage.

Only direct content, role, logical identities and a SHA-256 content digest are retained. Display fields, API prompt sidecars, reasoning, claimed authors, sessions and permissions are not copied. The digest identifies candidate text for later comparison; it proves neither authorship nor persistence. Candidate objects contain private text and must not be logged or sent to a model as trusted instructions. Their separate metadata diagnostic exposes counts only and explicitly reports `source_verification: not_performed`, `durable_checkpoint: false` and `automatic_ingestion: false`.

This deliberately accepts the *shape* of some valid-UID merged pending candidates while still marking them unverified. A future resolver must reject their source-content mismatch. Preparation alone must never advance a cursor, publish a memory, authorize a write or satisfy the native v2 gate. No source data or content digest is persisted by this slice.

## 4. Smallest Next Integration Contract

A general source-reference checkpoint needs a host-owned handoff that:

1. Persists or explicitly classifies each eligible pending source before claiming durable coverage.
2. Supplies scoped immutable source references, complete merge coverage, source revision and clear pending-source disposition. Separately identifies any tool/effect/approval references needed by the broader project contract.
3. Binds coverage validation and source retention to the compression commit fence, with a detectable abort/retry outcome. A provider return string or an unrelated local metadata marker is insufficient.

This can build on the existing UID, revision and compression transaction machinery; it need not duplicate the host transcript store. It remains a proposal, not a patched or tested host API. Provider-side work still includes explicit capture/retention opt-in, profile/session/context admission, exact source reconciliation, bounded transactional receipts, idempotency, revoke/forget races and recovery after an uncertain commit. Read-only recall opt-in is not permission for automatic capture or extra model-provider data sharing.

Until those contracts are implemented and tested, leave the provider at API v1 and keep strict checkpoint requirements failing closed. Do not add a flag that reports v2 support without its durable guarantees. This historical slice did not complete E0.9 or E2.8; current E0.9 verification is tracked separately in [76](76-native-memory-contracts.md), while E2.8 durable integration remains open.

## 5. Verification and Evidence

Unit tests exercise immutable preparation, Unicode, field exclusion, digest behavior, metadata-only diagnostics, ambiguity and all bounds. Native contracts exercise actual manager/normalizer/SessionDB behavior: stable identities, merged resume lineage, ordinary unflushed tail, merged unidentified tail, rewrite/compaction revisions, no-op v2 acceptance, error propagation, context/session scope, asynchronous sync failure and app-server refusal. The gate-error test proves callback failure propagation with unchanged input, not a full compression transaction rollback.

All inputs are synthetic and all stores temporary. Tests make no model call, use no personal account or production profile, open no Gateway listener, and change no host source or remote repository. This slice changes neither existing memory schemas nor runtime capabilities.

Pinned sources: [identity and merge bookkeeping](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/message_metadata.py), [public transcript reads and revision](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_state_messages.py), [compression and pending-tail ordering](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/conversation_compression.py), [manager checkpoint handling](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py), and [provider API documentation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/memory-provider-plugin.md).
