# 50. Reviewed Memory Candidates

English | [简体中文](50-reviewed-memory-candidates-zh.md)

The standalone plugin now offers optional model-assisted drafting from the current
native user input, with a separate local review step before canonical memory is
created. This uses supported `pre_llm_call`, model-tool and `post_llm_call` hooks,
not the experimental worker patch. It does not start an extraction model, replace
the configured provider, ingest history or claim checkpoint-v2 coverage.

## 1. Explicit Opt-In and Review

Keep the existing [memory tool prerequisites](32-session-scoped-memory-tools.md):
`mode: local_tasks`, `local_conversation: true`, `local_memory: true` and
`memory_model_tools: true`. Add `memory_candidates: true` deliberately; its default
is false. Configuration alone does not permit capture. In an admitted trusted
native LOCAL session:

```text
/personal-memory-tools enable-read
/personal-memory-tools candidate-on
/personal-memory-tools status
```

Candidate mode requires **read-only** memory activation. A write activation is
refused: explicitly select `enable-read` first. This prevents the same activated
memory writer from bypassing candidate review. Existing write tools outside this
mode retain their own permissions; the plugin does not sandbox unrelated tools.
Candidate selection does not extend the existing 30-minute grant. Renewal,
`enable-write`, disable, expiry, observed configuration revocation, unload or
restart clear the selection and captured source. `candidate-off` stops future
proposals without disabling recall or ordinary memory reads. It does not erase
previous drafts; use review commands below. Task activation cannot grant capture.

On a subsequent eligible turn, the existing main model may propose useful drafts
through `personal_memory_candidate`. Normal tool continuations can incur ordinary
model costs. There is no additional background/provider request, and no guarantee
that the model will propose anything. Review the resulting ID in the native UI:

```text
/personal-memory candidate-list --limit 20
/personal-memory candidate-show CANDIDATE_ID
/personal-memory candidate-accept CANDIDATE_ID --expected-revision 1 --keep
/personal-memory candidate-discard OTHER_CANDIDATE_ID --expected-revision 1
/personal-memory candidate-purge-expired
```

Replace IDs with actual returned UUIDs. Acceptance requires an explicit retention
choice: `--keep` means no canonical expiry; alternatively use
`--expires-at 2030-01-01T00:00:00Z` with the desired UTC deadline. Neither is
inferred. Inspect content, topic and exact quote before accepting. A wrong draft
must be discarded and, if useful, replaced through explicit `remember`; this
slice has no candidate-edit command. Candidate commands return readable Unicode
JSON. List pages expose metadata only; show exposes the draft and quote. Model
tools cannot list, inspect, accept or discard candidates. Native review stays
available under `local_memory` even after new candidate capture is disabled.

## 2. What Is Captured, and What It Does Not Prove

Only the current original plain-text `user_message`, at most 8,192 characters,
is eligible. History, assistant/tool output, multipart payloads and claimed
sender/UID fields are not source authority. The full input is process-local and is not persisted wholesale. Cleanup is best
effort: a missing post hook can leave plaintext until subsequent pruning or
unload. Proposal quotes must match an exact
substring using zero-based Python-character offsets, not bytes. No fuzzy match,
normalization or search for an alternative offset is performed.

Admission binds the actual current primary turn object, profile, route, session,
task, activation generation and selection. A per-object nonce prevents reused
string turn IDs from replaying another turn's proposals. First-source digest and
closure latches survive selection toggles without retaining full input. Missing
or stale hook state fails closed. Post-turn cleanup is best effort, not proof of
a durable native commit; proposal admission always rechecks the actual turn.
Remote, child, cron, managed and unbound contexts remain refused.

A matching quote proves substring membership only. It does not prove authorship,
truth, endorsement, faithful summarization or permission. Quoted third-party
instructions are not authorization. Drafts never become actions or grants.
Secret avoidance in model guidance is **not a secret detector**: enabling this
mode permits plaintext draft/quote storage from subsequent eligible inputs.
Do not enable it for material you do not want retained. LOCAL is a trusted
single-user deployment boundary, not proof of physical locality or fresh human
identity. All admitted session controllers share that authority.

## 3. Persistence, Retention and Retries

Candidates share the private `records.sqlite3` store but a separate schema-v6
table. Pending candidates are excluded from canonical list/search/recall and
memory-change checkpoints. At most three proposals per actual turn and 1,000
candidate rows per store are retained, including terminal metadata. There is no
silent eviction or automatic capacity reset. Limits are rejection boundaries,
not an indefinitely sustainable archive.

A proposal contains at most 2,048 content characters, 128 topic characters and a
1,024-character quote, plus scoped metadata and source digest. It expires seven
days after creation and cannot then be accepted. **Expiry is not a deletion
deadline.** Payload cleanup commits on a later successful candidate operation or
explicit `candidate-purge-expired`; a failed operation rolls that cleanup back.
An offline store can retain expired plaintext longer. There is no background
purger, secure physical erasure, backup deletion or native-history retraction.
Accepting or discarding also clears candidate payload, source digest and session
reference. Minimal IDs, hashes, timestamps and retry receipts remain bounded.

Acceptance inserts canonical memory and closes the candidate in one SQLite
transaction. It changes canonical progress once. Exact retries return the
historical metadata receipt; a later correction or forgetting is not undone and
no record is recreated. A changed retention choice conflicts rather than silently
changing the earlier acceptance. Canonical provenance describes the latest local
operator editing route, not verified authorship of the source text. Accepted
records have the usual correction, expiry, forgetting and recall behavior.

Opening an owned store through an authorized normal memory command upgrades
schema v1–v5 transactionally to v6, preserving records, receipts, tombstones and
progress. Native read-only recall never migrates a store: old-schema automatic
recall remains unavailable until that deliberate writable opening. Candidate
list/show also use a writable connection because they can purge expired drafts.
Authorized candidate commands can initialize a missing owned store. Unsafe or
foreign stores are not adopted to force access.

## 4. Verification and Remaining Work

Offline tests use the actual pinned host command admission, primary turn hooks,
relay and model-tool registry, with synthetic inputs and no model request.
They verify read-only capture, exact source/Unicode offsets, scope refusals,
revocation, reused turn IDs, post closure, acceptance/forget/reload replay,
transaction rollback, concurrent acceptance, corruption, quotas and migrations.

The host-free `tests/unit/test_memory_crash_recovery.py` matrix terminates a
separate Python process with `os._exit` after record/event/receipt writes, after
candidate closure, and immediately before/after transaction COMMIT. Eleven
cases verify full rollback before COMMIT, durable replay after COMMIT, database
integrity, single canonical creation and no resurrection after forgetting and
reopening. This exercises SQLite process-crash recovery with synthetic data and
DELETE journaling, not power-loss durability, physical erasure, real Gateway,
provider, filesystem/device failure or full E8 release certification. Reproduce
with `python -m pytest tests/unit/test_memory_crash_recovery.py -q` using the
project's Python 3.14 environment. Refs #21.

This is a practical opt-in draft-and-review workflow, not automatic canonical
extraction. Real configured-model usefulness, source-coverage checkpoints,
background retention enforcement, semantic/Chinese recall quality and remote
owner identity remain open. Existing selected providers are unchanged. No
installer, denied Gateway, live credentials or host patch is required for these
offline contracts, and prior installation restrictions remain in force.

See [exact source suppression](80-exact-memory-source-suppression.md) for schema-11 operator suppression and correction/forgetting of newly linked accepted sources; historical receipts are not current state.
