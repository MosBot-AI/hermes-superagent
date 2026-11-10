# 89. Packaged Gateway Crash-Recovery Acceptance

English | [简体中文](89-packaged-gateway-crash-zh.md)

## Exact scope

[#113](https://github.com/MosBot-AI/hermes-superagent/issues/113) adds a manual real-runtime candidate for a narrow E8.2 failure window: a task mutation has committed, but the client has not consumed its RPC reply when the test Gateway is abruptly terminated. This extends [packaged lifecycle acceptance](84-packaged-gateway-live.md); it does not replace the existing TaskStore subprocess transaction-fault matrix.

The synthetic client deliberately does not receive the write reply. The independent test controller observes a durable receipt through read-only SQLite, then terminates only its own Gateway subprocess. The reply might already have reached the client's transport buffer. Therefore the evidence is **client-unobserved result after a durable commit**, not proof that a network packet was lost, a pre-commit crash, power-loss durability, or every possible crash point.

## Runtime chain

The current production package is built and verified, then scanned and installed through the unchanged pinned official installer in an isolated private profile. The test uses the real control ticket and authenticated WebSocket protocol, not a fabricated runner. It never submits a model prompt and does not receive provider credentials.

1. Create a native local session and send a synthetic capture with an explicit durable request ID without consuming its response.
2. Observe the committed receipt read-only, force termination of that test Gateway and verify process exit.
3. Start the unchanged official runtime again without manually deleting control files or repairing databases. Resume the original session with a newly minted ticket.
4. Reconcile canonical task state and retry the exact original request. Require the original historical receipt, one task, and no duplicate event or receipt. A changed intent under the same key must refuse.
5. Exercise the analogous window for a revision-checked update, restart and reconcile again. Stale writes cannot overwrite the durable revision.
6. Stop the final instance normally and verify control/port cleanup. Independently inspect database integrity and canonical records read-only.

Only synthetic data is used. Failure cleanup is not counted as successful recovery; a failure to restart or reconcile fails acceptance. No security refusal is bypassed, and there is no alternative unauthenticated transport, forged identity, direct database write or manual state repair.

## Operator reconciliation

When a connection closes or the process disappears during a write, do not interpret silence as failure or resend with a fresh request ID. Save the original explicit key and exact arguments. After the official runtime recovers, inspect the canonical task when its ID is known and retry the same intent with the same key to recover its receipt. A receipt is historical evidence; `show` reads current state. A conflict requires inspection, not a blind overwrite or automatic new-key retry.

This is a local receipt workflow, not an exactly-once external-delivery guarantee. It cannot retract external effects or resolve a different provider's unknown outcome.

## Verification boundary

The test remains outside the default unit suite and runs only in the explicit manual `Native Gateway acceptance` workflow. Preparation tests can check its structure but cannot establish live recovery. Accept it only with successful exact-source-head manual evidence, independent review and normal CI; a later revision requires its own evidence.

The local cloud executor's socket restriction is unchanged; this test is not started there. The permitted GitHub-hosted runner is the live execution target. No MacBook or other personal device is used.

This bounded acceptance does not complete #21's identity/revocation/delivery matrix, E6.9 natural-language acceptance, remote-owner authority, shared REST availability, reminders or the overall Super Agent goal. It is additional failure evidence, not a retroactive new prerequisite for the original deterministic local M1 definition.
