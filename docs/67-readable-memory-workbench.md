# Readable native memory workbench

English | [简体中文](67-readable-memory-workbench-zh.md)

## Human output and stable structured output

The native `/personal-memory` command now defaults to readable text for help, list, search, search-terms, recall, show and ordinary remember/correct/forget receipts. Chinese text stays legible. Each result includes relevant IDs/revisions and state; full record text is preserved, with newlines, control characters and bidirectional/format controls escaped inside quoted fields. Stored prose cannot become an extra generated status line or command. It remains untrusted data, not permission or verified original authorship.

```text
/personal-memory list
/personal-memory search-terms project deadline
/personal-memory show RECORD_ID
/personal-memory --json list
```

**Output-format compatibility change:** scripts parsing native command output must explicitly put `--json` before the operation. It retains the original `personal.local-memory.v1` envelope, including admission/configuration/unload and invalid-command errors. `--json` changes presentation only; it does not change access, validation, storage or retries. A misplaced/repeated flag is not accepted as a new command. The existing model read/write tools remain JSON and their schemas are unchanged. Internal `LocalMemoryCommands` callers retain the JSON constructor default; only the native plugin registration selects text.

Candidate review/acceptance, export, changes and checkpoints deliberately retain their complete structured output. No source quote, retention choice or checkpoint field is removed to simplify a security-relevant review. Unknown future result shapes also fall back to the original envelope rather than changing an already completed operation into an error. Rendering never reopens storage, reads another page, retries a write or sends an external message.

## What the views mean

- List/search/search-terms show whole returned records, status, topic and expiry. A forgotten record has cleared canonical payload, but this does not erase prior history, exports or backups. An expired record remains stored and is excluded from ordinary fresh recall.
- Show additionally displays creation/update times and the latest editing route/session reference. These identify recorded metadata, not verified human intent.
- Pagination preserves the current query/terms, limit and explicit expiry inspection in a quoted next-page command. This is a suggested **read**, not execution. Pages are live and can change between reads; no-match does not prove a fact is absent.
- Recall displays the backend's omitted-record count and ASCII-JSON-character budget. This is not a token budget or a guarantee that every relevant fact was retrieved.
- Fresh mutation receipts show the saved ID, revision, request ID and event sequence without repeating stored content. Exact retries are labelled as an earlier recorded result, not current state. Forgetting cannot be reversed by receipt replay.
- Errors retain their exact code and retryability. An unknown write outcome is not called successful or failed-with-no-effect; inspect current state or reuse the same request ID and identical arguments. Format failure preserves the real receipt.

No new operation, memory schema, authority, automatic recall, generated projection file, provider selection or deployment is introduced. This workbench is not the separate persistent Markdown projection planned in E2.7.

## Verification

Unit and pinned-Hermes native command tests cover human/JSON output, non-ASCII/control text, pagination replay, expiry/forgotten state, mutation receipts and stale retries, structured fallback, invalid input, storage errors, disabled configuration, unsupported origins and retained callbacks after unload. Storage/backend and model-tool contracts are unchanged. Synthetic profiles and offline fixtures are not live user or production acceptance.
