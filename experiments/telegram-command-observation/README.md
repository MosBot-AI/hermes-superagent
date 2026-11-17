# Telegram command observation on the pinned Hermes host

English | [简体中文](README-zh.md)

This review artifact adds an optional in-process command observation to a disposable Hermes checkout at `2281116525106e3c109993ccb5dc74d02bfc1427`. The protocol is exercised by a synthetic consumer registered through the real plugin loader. The clean host remains the project compatibility target. See [manifest.json](manifest.json) for the exact staged tree, patch and test inputs, and [LICENSE.hermes-agent](LICENSE.hermes-agent) for the upstream license.

## Observation contract

After the adapter admits an immediate command, it stamps the original Telegram SDK `Update.message` on the original event. The original update and message must both belong to the receiving adapter's initialized SDK Bot object. The stamp is limited to direct, unedited human private messages outside topics and excludes forwarded, bot-mediated and business messages. Delayed split commands take the existing buffering path and get no stamp.

The stamp also captures the active adapter connection and, in polling mode, Hermes's native polling generation. Before binding the optional callback input and again after allowlist validation, the adapter must still match that capture. A connection teardown, fatal transition, replacement connection, fenced poller or new polling generation invalidates the old observation even if the same adapter and SDK Bot objects remain registered. A fresh input processed on the successor can receive a fresh observation. Normal command handling is independent of the observation.

The actual registered Gateway callback can declare the optional keyword `telegram_observation`. Its value is a callable that returns the actor ID, receiving Bot account ID, transport profile and registered command name once, or `None`. Consumption checks the original event, unchanged command text, current receiver and its registration, same-profile routing and the current Gateway allowlist. Five seconds elapse from adapter capture, and scope exit retires any retained handle. Generic `**kwargs` callbacks continue to receive the existing context, and hosted commands receive no observation handle.

An observation establishes local transport provenance at the time of the read in the cooperative host. The lifecycle check covers transitions after adapter capture. It does not determine when Telegram first queued the input or hold a fence over a later action. Network authentication, authenticated owner enrollment, device and policy revisions, route ABA fencing and atomic admission still need independent evidence. The handle covers one callback, while redelivered SDK packets may start a new callback. Returned values can be copied and carry no permission. The probe emits synthetic IDs only. The artifact lives outside the runtime package.

## Results

Python 3.14.9 with the exact Telegram SDK 22.8 wheel locked by Hermes was used on all trees. One clean control confirmed that the existing handler sees no observation for the same direct SDK input. The earlier staged tree `97146739f6d9a6ba44b68338215490011ed38f5d` returned a stale observation in all seven new lifecycle cases. All 26 candidate cases and 36 existing native regression tests passed. The upstream command found no new blocking or advisory code health findings, all 15 static checks passed, and the import boundary check passed. The nine socket cases in the [historical experiment](../command-context/README.md) were outside this selection.

The candidate cases exercise two synthetic receiving accounts, one-shot read and scope expiry, forwarding, edits, group and bot messages, private topics, marked Business connections, inline-bot mediation, a different SDK Bot with the same numeric ID, a manufactured event, an exact event copy, deadline expiry, adapter disconnect or reassignment, SDK Bot replacement and loss of initialization, allowlist changes, legacy callback shape and an independent hosted process. The new cases use native lifecycle methods before callback binding and before the first read. They check polling fencing, polling generation turnover, reuse of the same Bot object across a simulated webhook reconnect and a polling change during allowlist validation. Fresh successor input sees the ordinary command result and a valid observation. SDK initialization and connection setup are synthetic. No network calls are made.

## Reproduce in a disposable checkout

Set `PROJECT` to this project checkout, `COPY` to a clean disposable Hermes checkout, `PYTHON` to its Python 3.14 test interpreter and `WHEEL` to the SDK 22.8 wheel recorded in `manifest.json`. Set `SDK` to a new directory outside both repositories. The checkout used by the standard project check stays clean.

```bash
set -eu
ARTIFACT="$PROJECT/experiments/telegram-command-observation"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$COPY" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$COPY" status --porcelain --untracked-files=all)"
printf '%s  %s\n' 42373918097f1b837cc4e717d588c19ea79651497ec712bb5b0c76e5e63c50e1 "$WHEEL" | sha256sum -c
printf '%s  %s\n' 4c6c51d0685ba50c5c6f260f5c9b226b8ef4f15ae41e4a8daf6575abd9fdb607 "$ARTIFACT/telegram-command-observation.patch" | sha256sum -c
mkdir "$SDK"
"$PYTHON" -m zipfile -e "$WHEEL" "$SDK"
cd "$COPY"
TEST_HOME="$(mktemp -d)"
export HOME="$TEST_HOME"
export HERMES_PYTHON="$PYTHON"
umask 022
PROBE="$ARTIFACT/test_observation.py"
IMPORTS="$COPY $PROJECT $PROJECT/tests/contracts $SDK"
bash scripts/run_tests.sh "$PROBE" --file-retries 0 -- -o "pythonpath=$IMPORTS" -k clean_pin -q
git apply --check "$ARTIFACT/telegram-command-observation.patch"
git apply --index "$ARTIFACT/telegram-command-observation.patch"
test "$(git write-tree)" = 7fa0c1fa67ebeba3c6e7ec9e1ad50d1c0e2b8489
bash scripts/run_tests.sh "$PROBE" --file-retries 0 -- -o "pythonpath=$IMPORTS" -k candidate -q
bash scripts/run_tests.sh "$PROJECT/tests/contracts/test_owner_telegram_ingress.py" \
  tests/hermes_cli/test_plugin_command_source.py tests/gateway/test_multiplex_transport_matrix.py \
  tests/gateway/test_telegram_callback_auth_fail_closed.py tests/gateway/test_telegram_auth_check.py \
  --file-retries 0 -- -o "pythonpath=$IMPORTS" -q
"$PYTHON" scripts/check --base "$BASE" --staged
"$PYTHON" scripts/boundary_lint.py --check
```
