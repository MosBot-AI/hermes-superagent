"""Independent, metadata-only observations and scenario assertions for E1/E5 tests.

This is a harness, not a production retry/reconciliation implementation. Direct
remote SQLite reads are test oracles; real clients cannot assume that access.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .core import SCHEMA, FixtureError, canonical, strict_object, validate_envelope


@contextmanager
def _database(path, *, read_only=False):
    target = Path(path).resolve().as_uri() + "?mode=ro" if read_only else path
    conn = sqlite3.connect(target, uri=read_only)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def ground_truth(database):
    """Read remote facts without trusting the service's returned result."""
    with _database(database, read_only=True) as conn:
        conn.row_factory = sqlite3.Row
        effects = [dict(row) for row in conn.execute("SELECT * FROM effects ORDER BY seq")]
        attempts = [dict(row) for row in conn.execute("SELECT * FROM attempts ORDER BY seq")]
    return {"effects": effects, "attempts": attempts}


def classify_receipt(envelope, result):
    """Check structure/binding only. A plausible provider ID still needs an oracle."""
    try:
        strict_object(result, {"schema_version", "status", "delivered", "receipt_ref", "binding"})
        envelope = validate_envelope(envelope)
        expected = {k: v for k, v in envelope.items() if k not in {"target", "payload"}}
        if (
            result["schema_version"] != SCHEMA
            or result["status"] != "accepted"
            or result["delivered"] is not False
            or canonical(result["binding"]) != canonical(expected)
            or type(result["receipt_ref"]) is not str
            or not re.fullmatch(r"synthetic-receipt-[1-9][0-9]*", result["receipt_ref"])
        ):
            return "unknown_outcome"
    except FixtureError:
        return "unknown_outcome"
    return "accepted_claim"


def assert_matching_receipt(database, envelope, result):
    assert classify_receipt(envelope, result) == "accepted_claim", "receipt_schema_or_binding"
    expected = {k: v for k, v in envelope.items() if k not in {"target", "payload"}}
    rows = ground_truth(database)["effects"]
    matches = [r for r in rows if result["receipt_ref"] == f"synthetic-receipt-{r['seq']}"]
    assert len(matches) == 1, "receipt_not_in_remote_truth"
    assert canonical(json.loads(matches[0]["binding"])) == canonical(expected), (
        "receipt_does_not_match_effect"
    )
    assert matches[0]["status"] == "accepted", "receipt_status_disagrees"
    assert matches[0]["account_ref"] == envelope["account_ref"], "remote_account_disagrees"
    assert matches[0]["effect_key"] == envelope["effect_key"], "remote_effect_key_disagrees"
    return True


def assert_pure(before, after):
    assert before == after, "declared_read_or_prepare_mutated_remote"


def assert_no_blind_resend(database, *, effects, execute_attempts=1):
    actual = ground_truth(database)
    assert len(actual["effects"]) == effects, "unexpected_remote_effect_count"
    assert sum(a["operation"] == "execute" for a in actual["attempts"]) == execute_attempts, (
        "unexpected_execute_retry"
    )


class Observations:
    """Separate consumer database; never shares a transaction with remote effects."""

    def __init__(self, path):
        self.path = Path(path)
        with _database(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS observations("
                "seq INTEGER PRIMARY KEY, phase TEXT, outcome TEXT)"
            )

    def record(self, phase, outcome):
        if phase not in {"execute", "reconcile"} or outcome not in {"unknown_outcome", "accepted"}:
            raise FixtureError("invalid_observation")
        with _database(self.path) as conn:
            conn.execute("INSERT INTO observations(phase,outcome) VALUES(?,?)", (phase, outcome))

    def report(self):
        with _database(self.path) as conn:
            rows = conn.execute("SELECT phase,outcome FROM observations ORDER BY seq").fetchall()
        return {
            "observation_count": len(rows),
            "accepted_observations": sum(r[1] == "accepted" for r in rows),
            "latest_outcome": rows[-1][1] if rows else "not_started",
            "delivered": False,
        }


def execute_once(factory, envelope, observations, *, verifier=None, before_observe=lambda: None):
    """One test attempt only. Every transport failure remains unknown; never retry."""
    observations.record("execute", "unknown_outcome")
    try:
        result = factory().execute(envelope)
    except FixtureError:
        return {"status": "unknown_outcome"}
    before_observe()
    outcome = verified_outcome(envelope, result, verifier)
    if outcome == "accepted":
        observations.record("execute", outcome)
    return {"status": outcome}


def reconcile_only(factory, envelope, observations, *, verifier=None):
    """Replaceable adapter seam: recovery does not call execute under any result."""
    try:
        result = factory().reconcile(envelope)
        outcome = verified_outcome(envelope, result, verifier)
    except FixtureError:
        outcome = "unknown_outcome"
    observations.record("reconcile", outcome)
    return {"status": outcome}


def sanitized_report(database, observations):
    truth = ground_truth(database)
    # Fixed categories/counts only, not result prose, selectors, bodies, hashes or errors.
    return {
        "schema_version": "synthetic.report.v1",
        "remote_effect_count": len(truth["effects"]),
        "remote_execute_attempts": sum(a["operation"] == "execute" for a in truth["attempts"]),
        "consumer": observations.report(),
        "production_authorized": False,
    }


def verified_outcome(envelope, result, verifier):
    """Only an explicit test evidence oracle can turn a claim into acceptance."""
    if classify_receipt(envelope, result) != "accepted_claim" or verifier is None:
        return "unknown_outcome"
    try:
        verified = verifier(envelope, result)
    except FixtureError, AssertionError:
        return "unknown_outcome"
    return "accepted" if verified is True else "unknown_outcome"


def validate_sources(result, account):
    """Strict fixed corpus response schema. Source prose never becomes authority."""
    strict_object(result, {"schema_version", "account_ref", "items", "next_cursor"})
    if (
        type(account) is not str
        or account not in {"account-a", "account-b"}
        or result["schema_version"] != SCHEMA
        or result["account_ref"] != account
    ):
        raise FixtureError("invalid_source_result")
    cursor = result["next_cursor"]
    if cursor is not None and (type(cursor) is not int or not 1 <= cursor <= 100):
        raise FixtureError("invalid_source_result")
    items = result["items"]
    if type(items) is not list or len(items) > 4:
        raise FixtureError("invalid_source_result")
    ids = []
    for item in items:
        strict_object(
            item,
            {
                "source_id",
                "account_ref",
                "author_ref",
                "authenticated_owner",
                "provenance",
                "content",
                "scenario",
            },
        )
        source_id, content = item["source_id"], item["content"]
        if (
            type(source_id) is not str
            or not re.fullmatch(r"src-" + account[-1] + r"-[a-z0-9-]{1,48}", source_id)
            or item["account_ref"] != account
            or item["authenticated_owner"] is not False
            or type(content) is not str
            or not content
            or type(item["author_ref"]) is not str
            or item["author_ref"]
            not in {
                "synthetic-colleague",
                "synthetic-outsider",
                "synthetic-other-colleague",
                "synthetic-forwarder",
            }
            or type(item["scenario"]) is not str
            or item["scenario"]
            not in {"normal", "spoofed_owner", "prompt_injection", "conflicting_record"}
        ):
            raise FixtureError("invalid_source_result")
        try:
            if len(content.encode()) > 2048:
                raise FixtureError("invalid_source_result")
        except UnicodeError:
            raise FixtureError("invalid_source_result") from None
        provenance = strict_object(
            item["provenance"], {"kind", "scope_ref", "locator", "observed_at"}
        )
        if (
            type(provenance["kind"]) is not str
            or provenance["kind"] not in {"provider_record", "forwarded"}
            or provenance["scope_ref"] != "scope-" + account[-1]
            or provenance["observed_at"] != "2026-11-09T00:00:00Z"
            or type(provenance["locator"]) is not str
            or not re.fullmatch(
                r"https://sources\.fixture\.invalid/" + account + r"/[a-z0-9-]{1,64}",
                provenance["locator"],
            )
        ):
            raise FixtureError("invalid_source_result")
        ids.append(source_id)
    if len(ids) != len(set(ids)):
        raise FixtureError("invalid_source_result")
    return items
