#!/bin/sh
# Run real native Bot reply acceptance with private Linux login startup.
set -eu
umask 077

usage() {
    printf '%s\n' \
        'Usage: sh acceptance/live/run_native_bot_poll_reply.sh --hermes CHECKOUT --hermes-python PYTHON [--receipt RESULT.xml] [--installed] [--consume]' \
        '       sh acceptance/live/run_native_bot_poll_reply.sh --hermes CHECKOUT --hermes-python PYTHON [--receipt RESULT.xml] (--push | --reconnect | --owner-loss | --settled-loss | --finished-loss | --consumed-loss | --admitted-loss | --planned-restart | --result-write-failure) [--review-recovery]'
}

host=
python=
receipt=
installed=0
review_recovery=0
mode=poll
test_file=test_native_bot_poll_reply.py
case_name=test_native_stateless_bot_poll_reply_persists_unconsumed_completion
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --installed) installed=1; shift ;;
        --review-recovery) review_recovery=1; shift ;;
        --consume)
            if [ "$mode" != poll ]; then usage >&2; exit 2; fi
            mode=consume
            case_name=test_native_stateless_bot_wait_consumes_reply_before_fallback
            shift ;;
        --push|--reconnect|--owner-loss|--settled-loss|--finished-loss|--consumed-loss|--admitted-loss|--planned-restart|--result-write-failure)
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
                finished-loss|consumed-loss|admitted-loss|result-write-failure)
                    test_file=test_native_bot_finished_loss.py
                    case_name=test_native_finished_bot_reply_needs_sender_recovery ;;
                planned-restart)
                    test_file=test_native_bot_finished_loss.py
                    case_name=test_native_planned_restart_drops_pending_sender_notification ;;
            esac
            shift ;;
        --hermes|--hermes-python|--receipt)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then usage >&2; exit 2; fi
            case "$1" in
                --hermes) host=$2 ;;
                --hermes-python) python=$2 ;;
                --receipt) receipt=$2 ;;
            esac
            shift 2
            ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [ -z "$host" ] || [ -z "$python" ]; then usage >&2; exit 2; fi
if [ "$installed" -eq 1 ] && [ "$test_file" != test_native_bot_poll_reply.py ]; then
    usage >&2
    exit 2
fi

case "$mode" in
    consumed-loss|admitted-loss|result-write-failure)
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
        result-write-failure) case_name=test_proposed_failed_result_write_loses_pending_sender_notification ;;
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
    timeout --kill-after=5s 365s "$python" -I -B \
        "$repo/acceptance/live/prepare_installed_bot_poll_recipient.py" "$host" "$prepared" < /dev/null
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
            HERMES_BOT_REVIEW_RECOVERY="$9" \
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
        suite.set("name", "native_bot_poll_reply_installed")
sys.stdout.buffer.write(ElementTree.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True))
PY
    ' bot-poll-reply "$repo" "$host" "$python" "$mount_namespace" "$network_namespace" "$prepared" "$case_name" "$test_file" "$review_recovery" \
    < /dev/null > "${staged_receipt:-/dev/null}"; then
    printf '%s\n' 'Isolated native Bot reply acceptance failed.' >&2
    exit 1
fi

if [ -n "$staged_receipt" ]; then
    mv -fT -- "$staged_receipt" "$receipt"
fi
printf '%s\n' 'Isolated native Bot reply acceptance passed.'
