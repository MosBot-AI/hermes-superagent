#!/bin/sh
# Run real native Bot reply acceptance with private Linux login startup.
set -eu
umask 077

usage() {
    printf '%s\n' \
        'Usage: sh acceptance/live/run_native_bot_poll_reply.sh --hermes CHECKOUT --hermes-python PYTHON [--receipt RESULT.xml] [--installed] [--consume]' \
        '       sh acceptance/live/run_native_bot_poll_reply.sh --hermes CHECKOUT --hermes-python PYTHON [--receipt RESULT.xml] MODE [--review-recovery]' \
        'Use --upstream-recovery-base to select the separate review baseline or its clean control.' \
        'Installed mode supports poll, --consume, --push, --owner-loss, --settled-loss and --held-waiter-restart.' \
        'Installed recovery with --review-recovery also requires --install-hermes CLEAN_CHECKOUT.' \
        'Use --install-tool-store DIRECTORY to stage pinned installer tools.' \
        'Modes: --push --reconnect --owner-loss --settled-loss --finished-loss --planned-restart' \
        '       --held-waiter-restart --drained-waiter-restart' \
        'Review only: --killed-settled-receipt --mismatched-waiter-receipt' \
        '             --delayed-waiter-receipt --missing-waiter-receipt --combined-write-failure' \
        '             --consumed-loss --admitted-loss --result-write-failure --consumed-write-failure --admitted-write-failure'
}

host=
python=
receipt=
installed=0
install_tool_store=
install_hermes=
review_recovery=0
upstream_recovery_base=0
mode=poll
test_file=test_native_bot_poll_reply.py
case_name=test_native_stateless_bot_poll_reply_persists_unconsumed_completion
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --installed) installed=1; shift ;;
        --review-recovery) review_recovery=1; shift ;;
        --upstream-recovery-base) upstream_recovery_base=1; shift ;;
        --consume)
            if [ "$mode" != poll ]; then usage >&2; exit 2; fi
            mode=consume
            case_name=test_native_stateless_bot_wait_consumes_reply_before_fallback
            shift ;;
        --push|--reconnect|--owner-loss|--settled-loss|--finished-loss|--consumed-loss|--admitted-loss|--planned-restart|--held-waiter-restart|--drained-waiter-restart|--killed-settled-receipt|--mismatched-waiter-receipt|--result-write-failure|--consumed-write-failure|--admitted-write-failure|--combined-write-failure|--delayed-waiter-receipt|--missing-waiter-receipt)
            if [ "$mode" != poll ]; then usage >&2; exit 2; fi
            mode=${1#--}
            test_file=test_native_bot_push_reply.py
            case "$mode" in
                push) case_name=test_native_viewed_bot_reply_wakes_sender_once ;;
                reconnect) case_name=test_native_disconnected_bot_reply_recovers_once ;;
                owner-loss)
                    test_file=test_native_bot_owner_loss.py
                    case_name=test_native_inflight_bot_reply_reconciles_after_owner_loss ;;
                settled-loss)
                    test_file=test_native_bot_owner_loss.py
                    case_name=test_native_settled_bot_reply_reconciles_after_owner_loss ;;
                held-waiter-restart)
                    test_file=test_native_bot_owner_loss.py
                    case_name=test_native_held_bot_reply_reconciles_after_planned_restart ;;
                killed-settled-receipt|mismatched-waiter-receipt|delayed-waiter-receipt|missing-waiter-receipt)
                    test_file=test_native_bot_owner_loss.py ;;
                drained-waiter-restart)
                    test_file=test_native_bot_owner_loss.py
                    case_name=test_native_drained_bot_reply_reconciles_after_planned_restart ;;
                finished-loss|consumed-loss|admitted-loss|result-write-failure|consumed-write-failure|admitted-write-failure|combined-write-failure)
                    test_file=test_native_bot_finished_loss.py
                    case_name=test_native_finished_bot_reply_needs_sender_recovery ;;
                planned-restart)
                    test_file=test_native_bot_finished_loss.py
                    case_name=test_native_planned_restart_drops_pending_sender_notification ;;
            esac
            shift ;;
        --hermes|--hermes-python|--receipt|--install-tool-store|--install-hermes)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then usage >&2; exit 2; fi
            case "$1" in
                --hermes) host=$2 ;;
                --hermes-python) python=$2 ;;
                --receipt) receipt=$2 ;;
                --install-tool-store) install_tool_store=$2 ;;
                --install-hermes) install_hermes=$2 ;;
            esac
            shift 2
            ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [ -z "$host" ] || [ -z "$python" ]; then usage >&2; exit 2; fi
if { [ -n "$install_tool_store" ] || [ -n "$install_hermes" ]; } && [ "$installed" -ne 1 ]; then
    usage >&2; exit 2
fi
if [ "$upstream_recovery_base" -eq 1 ]; then
    case "$mode" in
        poll|consume|push|reconnect) usage >&2; exit 2 ;;
    esac
fi
if [ "$installed" -eq 1 ]; then
    if [ "$review_recovery" -eq 1 ] && [ -z "$install_hermes" ]; then usage >&2; exit 2; fi
    case "$mode" in
        poll|consume|owner-loss|settled-loss|held-waiter-restart) ;;
        push) case_name=test_installed_recipient_reply_wakes_viewed_sender_once ;;
        *) usage >&2; exit 2 ;;
    esac
fi

case "$mode" in
    consumed-loss|admitted-loss|result-write-failure|consumed-write-failure|admitted-write-failure|killed-settled-receipt|mismatched-waiter-receipt|combined-write-failure|delayed-waiter-receipt|missing-waiter-receipt)
        if [ "$review_recovery" -ne 1 ]; then usage >&2; exit 2; fi ;;
esac
if [ "$review_recovery" -eq 1 ]; then
    case "$mode" in
        owner-loss) case_name=test_proposed_inflight_bot_sender_recovers_after_owner_loss ;;
        settled-loss) case_name=test_proposed_settled_bot_sender_recovers_after_owner_loss ;;
        finished-loss) case_name=test_proposed_finished_bot_sender_recovers_after_owner_loss ;;
        consumed-loss) case_name=test_proposed_consumed_bot_result_stays_consumed_after_owner_loss ;;
        admitted-loss) case_name=test_proposed_admitted_bot_completion_is_not_duplicated ;;
        planned-restart) case_name=test_proposed_planned_restart_recovers_pending_sender_notification ;;
        held-waiter-restart) case_name=test_proposed_held_bot_reply_reconciles_after_planned_restart ;;
        drained-waiter-restart) case_name=test_proposed_drained_bot_reply_reconciles_after_planned_restart ;;
        killed-settled-receipt) case_name=test_proposed_killed_waiter_restores_settled_receipt ;;
        mismatched-waiter-receipt) case_name=test_proposed_killed_waiter_refuses_mismatched_receipt ;;
        delayed-waiter-receipt) case_name=test_proposed_waiter_retries_temporarily_missing_receipt ;;
        missing-waiter-receipt) case_name=test_proposed_waiter_falls_back_when_receipt_stays_missing ;;
        combined-write-failure) case_name=test_proposed_combined_write_failure_recovers_from_previous_checkpoint ;;
        result-write-failure) case_name=test_proposed_failed_result_write_recovers_pending_sender_notification ;;
        consumed-write-failure) case_name=test_proposed_failed_result_write_preserves_consumption ;;
        admitted-write-failure) case_name=test_proposed_failed_result_write_does_not_repeat_admission ;;
        *) usage >&2; exit 2 ;;
    esac
fi

export PATH=/usr/bin:/bin
repo=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
host=$(CDPATH='' cd -- "$host" && pwd -P)
# Keep the virtual environment's interpreter link so Python loads that environment.
python=$(CDPATH='' cd -- "$(dirname -- "$python")" && pwd -P)/$(basename -- "$python")
test -x "$python"
for program in git ip mount readlink setpriv timeout unshare; do
    if ! command -v "$program" >/dev/null; then
        printf 'Missing Linux acceptance command %s\n' "$program" >&2
        exit 2
    fi
done
mount_namespace=$(readlink /proc/self/ns/mnt)
network_namespace=$(readlink /proc/self/ns/net)

staged_receipt=
prepared=
trap '
    if [ -n "$staged_receipt" ]; then rm -f -- "$staged_receipt"; fi
    if [ -n "$prepared" ]; then rm -rf -- "$prepared"; fi
' EXIT
if [ -n "$receipt" ]; then
    staged_receipt=$(mktemp -- "$(dirname -- "$receipt")/.bot-poll-reply.XXXXXX")
fi
if [ "$installed" -eq 1 ]; then
    # Prepare the exact package with the normal scanner before isolating reply traffic.
    prepared=$(mktemp -d /var/tmp/hbp.XXXXXX)
    set -- "${install_hermes:-$host}" "$prepared"
    if [ -n "$install_tool_store" ]; then
        set -- "$@" --tool-store "$install_tool_store"
    fi
    if [ "$upstream_recovery_base" -eq 1 ]; then
        set -- "$@" --upstream-recovery-base
    fi
    timeout --kill-after=5s 365s "$python" -I -B \
        "$repo/acceptance/live/prepare_installed_bot_poll_recipient.py" "$@" < /dev/null
fi

if ! env -i PATH="$PATH" LANG=C.UTF-8 TZ=UTC \
    timeout --kill-after=5s 150s unshare --user --map-current-user --keep-caps \
    --mount --propagation private --net --pid --mount-proc --fork --kill-child=SIGKILL \
    sh -eu -c '
        # Check namespace identity before mounting over any system path.
        test "$(readlink /proc/self/ns/mnt)" != "$4"
        test "$(readlink /proc/self/ns/net)" != "$5"
        test "$$" -eq 1
        mount -t tmpfs -o mode=1777,size=64m,nr_inodes=8192 tmpfs /tmp
        ip link set lo up
        test "$(ip -o link show | wc -l)" -eq 1
        test -z "$(ip -4 route show default)"
        test -z "$(ip -6 route show default)"
        work=$(mktemp -d /tmp/hbp.XXXXXX)
        mkdir -m 700 "$work/user" "$work/tmp"
        : > "$work/empty"
        for path in /etc/profile /etc/bash.bashrc /etc/bash.bash_logout; do
            if [ -e "$path" ] || [ -L "$path" ]; then
                test -f "$path"
                test ! -L "$path"
                mount --bind "$work/empty" "$path"
            fi
        done
        if [ -e /etc/profile.d ] || [ -L /etc/profile.d ]; then
            test -d /etc/profile.d
            test ! -L /etc/profile.d
            mount -t tmpfs -o mode=755,size=1m,nr_inodes=128 tmpfs /etc/profile.d
        fi

        cd "$1"
        if ! setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs \
            env -i PATH=/usr/bin:/bin LANG=C.UTF-8 TZ=UTC HOME="$work/user" TMPDIR="$work/tmp" \
            PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
            HERMES_TEST_ROOT="$2" HERMES_BOT_POLL_NAMESPACE=1 HERMES_BOT_POLL_INSTALLED="$6" \
            HERMES_BOT_REVIEW_RECOVERY="$9" HERMES_BOT_UPSTREAM_RECOVERY_BASE="${10}" \
            "$3" -m pytest -q -p no:cacheprovider --show-capture=no --tb=short \
            -o junit_logging=no --basetemp="$work/test" --junitxml="$work/result.xml" \
            "acceptance/live/$8::$7" >&2; then
            exit 1
        fi
        setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs \
            env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$work/user" TMPDIR="$work/tmp" \
            PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 "$3" - "$work/result.xml" "$6" "$7" <<\PY
from pathlib import Path
import sys
from xml.etree import ElementTree

receipt = Path(sys.argv[1])
tree = ElementTree.parse(receipt)
cases = tree.findall(".//testcase")
excluded = ("error", "failure", "skipped", "system-out", "system-err")
if (
    len(cases) != 1
    or cases[0].get("name") != sys.argv[3]
    or any(tree.findall(f".//{tag}") for tag in excluded)
):
    raise SystemExit("Expected one clean passing native Bot reply case")
for suite in tree.iter("testsuite"):
    suite.attrib.pop("hostname", None)
    if sys.argv[2]:
        suites = {
            "test_installed_recipient_reply_wakes_viewed_sender_once": "native_bot_push_reply_installed",
            "test_native_stateless_bot_wait_consumes_reply_before_fallback": "native_bot_poll_reply_installed",
            "test_native_stateless_bot_poll_reply_persists_unconsumed_completion": "native_bot_poll_reply_installed",
        }
        suite.set("name", suites.get(sys.argv[3], "native_bot_recovery_installed"))
sys.stdout.buffer.write(ElementTree.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True))
PY
    ' bot-poll-reply "$repo" "$host" "$python" "$mount_namespace" "$network_namespace" "$prepared" "$case_name" "$test_file" "$review_recovery" "$upstream_recovery_base" \
    < /dev/null > "${staged_receipt:-/dev/null}"; then
    printf '%s\n' 'Isolated native Bot reply acceptance failed.' >&2
    exit 1
fi

if [ -n "$staged_receipt" ]; then
    mv -fT -- "$staged_receipt" "$receipt"
fi
printf '%s\n' 'Isolated native Bot reply acceptance passed.'
