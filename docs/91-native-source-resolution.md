# 91. Bounded Native Source Resolution

English | [简体中文](91-native-source-resolution-zh.md)

## Scope and status

[Issue #123](https://github.com/MosBot-AI/hermes-superagent/issues/123) adds an internal read-only resolver for the candidates prepared in [43](43-native-checkpoint-boundary.md). It reconciles a conservative durable-only subset against the caller-bound native session. This is development groundwork, not automatic ingestion, deployed acceptance, a new provider capability or an E2.8 durable checkpoint. The shipping provider remains API v1; no callback, tool or provider configuration changes.

The target is [Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427). The local pinned checkout supplies the source evidence. The historical pin in [43](43-native-checkpoint-boundary.md) and E0.9 verification in [76](76-native-memory-contracts.md) retain their separate scopes.

## Caller-owned binding

`personal_agent.native_source_resolution.NativeSourceBinding(store, session_id)` binds a native `SessionDB` opened with `read_only=True` and the current session. `resolve_checkpoint_sources(evidence, *, binding, expected_revision=None)` uses that explicit binding. Candidate fields cannot select a database path, another profile, another session, or SQL routing. The binding is not remote authentication or an authorization grant; the caller must already be permitted to read the selected session.

Resolution revalidates exact candidate types, immutable tuple structures, counts and content digests rather than trusting that a prepared object was constructed safely. The public native snapshot consistency operation is required. On the pinned read-only handle, this validates generations rather than opening a pinned read transaction. The observed `conversation_revision` is retained privately in immutable ephemeral references. An optional exact `expected_revision` fence refuses a changed revision even if candidate text is unchanged. Neither check binds the read to a future compression commit.

## Conservative coverage and limits

The resolver scans the full active current-session transcript, at most 256 rows plus one overflow sentinel. Partial scans, scan overflow and a revision row-count mismatch fail closed. Admission limits are 16,384 content characters per row, 65,536 total characters and 1,024 logical source identities. No partial success or truncation is treated as complete coverage.

All active rows are scanned, including tool, summary and display rows. Every primary and absorbed logical UID is validated globally; duplicate or overlapping identities anywhere in the scanned session are rejected. Every scanned content value must be a string or `None`; strings must satisfy the post-read per-row and total content limits. Unknown nontext payloads make the scope unsupported.

Only supported direct user/assistant prose can be selected. Current/legacy summary header markers and the merged-summary delimiter are conservatively rejected anywhere in selected text, even without a persisted summary flag; literal quotations of these markers can therefore be refused. Tool, summary, display and other ineligible rows remain positional barriers: candidates and split merges cannot select or cross them. Unrelated ineligible rows before or after the selected contiguous direct subset do not by themselves reject resolution. Candidate coverage must be an ordered contiguous subset of source rows with no gaps; the subset need not cover the entire active transcript.

An exact persisted single-row lineage is supported. A candidate may also reconcile adjacent plain **user** rows using the exact native `\n\n` join, provided those split rows carry no absorbed lineage. Split user merging also rejects the native reserved `\0json:` content prefix; an exact single stored row with that literal prefix is still eligible. Assistant merging strips content and joins with `\n`, so split assistant reconstruction is unsupported. Pending or unidentified merged text, cross-session identities, missing rows, ordering differences and content mismatches are rejected rather than guessed. Logical UIDs, not physical row IDs or matching text alone, identify source occurrences.

Native `get_messages` bounds the number of returned rows, not the allocation for an individual row. Finite post-read admission cannot hard-bound preallocation or metadata bytes. These are admission and scan limits, not a claim of an allocation-safe native storage interface.

## Output and security boundary

The resolver assumes valid native stored state and consumes the public decoded projection. Native `get_messages` can normalize malformed stored `tool_calls` JSON to `[]`; this resolver is not a raw corruption detector or an adversarial database audit. Rows with `tool_call_uid` or `tool_call_uids` markers are ineligible even when decoded tool calls are empty. The trusted caller and store boundary is not isolation against malicious in-process Python callers.

Results do not duplicate raw candidate or transcript text. Immutable references are private ephemeral evidence, not memory facts, trusted instructions, retained archives or durable receipts. The public diagnostic contains only counts and status; fixed safe failures do not disclose backend exceptions, paths, session identifiers or text. Caller-bound scope, exact content and revision agreement establish only the supported source reconciliation result.

There is no automatic capture permission, source-retention guarantee, cursor advancement, memory write, compression commit fence or durable checkpoint receipt. Rewrites, compaction and later revocation still require the separate lifecycle and commit contracts. Do not promote the provider to v2 or use successful resolution to satisfy a strict checkpoint gate. The host-owned durable guarantees described in [43](43-native-checkpoint-boundary.md) remain open.

## Verification boundary

Unit coverage and real pinned-host contracts must distinguish malformed preparation, scope/identity/content failures, scan and content bounds, exact persisted and user-split success, mixed-session positional barriers and global identity validation, revision fences, read consistency and metadata-only results. Use synthetic content and disposable stores only. Exact execution results belong to the tested change revision; this document does not infer passing tests from test presence or claim production/model acceptance.
