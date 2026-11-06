# 22. Local Task Search

English | [简体中文](22-local-task-search-zh.md)

[Project grouping](24-local-project-groups.md) now adds optional exact project/unassigned filters. The current store is schema v3; the search behavior below remains unchanged, and historical receipts are not rewritten.

## 1. Implemented Scope

A trusted local operator can search the existing opt-in task inbox by literal text in its title or details. This is a narrow local retrieval precursor to E2.2, not agent memory, semantic retrieval, owner authentication or the full personal-agent MVP. The [inbox](16-local-task-inbox.md) and [agenda](17-local-task-agenda.md) boundaries continue to apply.

No credentials, model, network, listener, new provider, native Projects/Kanban access or external action is required. No task-data model tool, conversational slash command or HTTP route is added. The official Hermes baseline and database schema remain unchanged.

## 2. Command and Matching

Use an isolated tested profile with this plugin explicitly set to `local_tasks`, as described in [16](16-local-task-inbox.md). Do not disable host isolation merely to expose the CLI.

```bash
hermes personal-agent tasks search --query "weekly review"
hermes personal-agent tasks search --query "review" --state all --limit 10
```

The query is a nonblank single-line string of at most 240 characters. It preserves exact spacing and rejects unsafe control/format characters. Matching is **case-sensitive literal substring search**, with no Unicode normalization, stemming, fuzzy matching or SQL operators. Chinese and other Unicode text can match literally. `%`, `_`, quotes and SQL-looking strings are ordinary characters, not wildcards or executable statements. SQL parameters carry the query.

Only title and details are searched. Resolution notes, request receipts, native memory, other profiles and external systems are excluded. Default state is `captured`; explicitly choose `done`, `cancelled` or `all` to inspect terminal records. Limit defaults to 20 and must be an exact integer from 1 to 100.

## 3. Results and Pagination

Results use `personal.local-tasks.v1`, `status: ok`, `scope: trusted_local_cli_only` and `replayed: false`. The `data` contains `items`, `next_cursor` and `has_more`; items are current task records, including nullable due dates, not old replay receipts. The query is not repeated in the response.

Tasks are ordered by immutable creation sequence, newest first. Pass the returned UUID as `--after` while keeping the same query and state:

```bash
hermes personal-agent tasks search --query "review" --state all \
  --limit 10 --after "UUID returned as next_cursor"
```

The cursor is a task-ID anchor in the current store, not a signed token bound to the query, state or cross-page snapshot. A missing or foreign-store ID is rejected. Changing the query or state means starting a new search without an old cursor. Edits between pages can change membership; this is a live view, not a durable change feed or export.

The page size is bounded. Literal substring matching can scan stored records; this is not an indexed full-text search or a proven latency bound for a large database.

## 4. Safety and Compatibility

Validation occurs before task storage is opened. Default `read_only` mode refuses the operation; existing profile/mode, POSIX file/directory ownership, permission, link and SQLite sidecar checks remain in force. Errors do not echo query text, SQL or private paths. Query arguments and output can still appear in local shell history, process listings or terminal logs; do not use secrets as queries.

Search creates no task event or request receipt and does not change task state or revision. Like list/agenda, opening the opt-in store may initialize it or migrate an exact supported older schema. Therefore search is not a promise of zero filesystem writes. Existing historical receipt bytes and mutation digests remain unchanged.

No backup, restore, export, forgetting policy, encryption, ranking or automatic task execution is added. Local OS access is not verified channel owner identity, and this CLI must not be exposed through an untrusted executor.

## 5. Verification

Tests cover title/details matching, Unicode/case semantics, literal special characters, malformed inputs, states, current due dates, empty pages, ordering, pagination, invalid cursors, legacy migration/replay compatibility and absence of task mutations. Real pinned-host CLI tests exercise the existing mode/profile/storage gates and guarded top-level subprocess path.

Passing these checks establishes a local inbox feature only. E1, full E2.2, native task integration and M1 release gates remain incomplete.
