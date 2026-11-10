"""Transactional local FTS candidates; canonical records remain authoritative.

No asynchronous index worker or external projection exists. Caller owns the same
SQLite transaction as records/receipts. Do not pass untrusted FTS expressions.
"""

import sqlite3

from .memory_backend import MemoryError

CREATE_SQL = (
    "CREATE VIRTUAL TABLE memory_fts USING fts5(content, topic, "
    "tokenize='trigram case_sensitive 1')"
)
SCHEMA = {
    "memory_fts": CREATE_SQL,
    "memory_fts_data": "CREATE TABLE 'memory_fts_data'(id INTEGER PRIMARY KEY, block BLOB)",
    "memory_fts_idx": (
        "CREATE TABLE 'memory_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID"
    ),
    "memory_fts_content": "CREATE TABLE 'memory_fts_content'(id INTEGER PRIMARY KEY, c0, c1)",
    "memory_fts_docsize": "CREATE TABLE 'memory_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB)",
    "memory_fts_config": "CREATE TABLE 'memory_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID",
}


def create_index(connection: sqlite3.Connection) -> None:
    """Create and fill under the caller's writer lock; failures roll back migration."""
    try:
        connection.execute(CREATE_SQL)
        # FTS secure-delete is separate from PRAGMA secure_delete. Require it,
        # rather than retaining obsolete terms in FTS segment tombstones.
        connection.execute("INSERT INTO memory_fts(memory_fts,rank) VALUES ('secure-delete',1)")
        validate_index_config(connection)
        connection.execute(
            "INSERT INTO memory_fts(rowid,content,topic) "
            "SELECT sequence,content,topic FROM records WHERE status='active'"
        )
    except sqlite3.OperationalError as error:
        # Unsupported builds must not silently fall back to another index/mode.
        if "no such module" in str(error) or "tokenizer" in str(error) or "SQL logic" in str(error):
            raise MemoryError("fts_unavailable") from None
        raise


def validate_index_config(connection: sqlite3.Connection) -> None:
    if connection.execute("SELECT v FROM memory_fts_config WHERE k='secure-delete'").fetchall() != [
        (1,)
    ]:
        raise MemoryError("unsafe_fts_configuration")


def update_index(connection: sqlite3.Connection, record_id: str) -> None:
    """Publish only the just-mutated current record inside its writer transaction."""
    row = connection.execute(
        "SELECT sequence,status,content,topic FROM records WHERE record_id=?", (record_id,)
    ).fetchone()
    if row is None:
        raise MemoryError("storage_error")
    connection.execute("DELETE FROM memory_fts WHERE rowid=?", (row[0],))
    if row[1] == "active":
        connection.execute(
            "INSERT INTO memory_fts(rowid,content,topic) VALUES (?,?,?)", (row[0], row[2], row[3])
        )


def term_filter(terms: list[str]) -> tuple[list[str], list[str]]:
    """AND literal substrings; short Chinese terms use the bounded canonical scan."""
    clauses, args = [], []
    indexed = [term for term in terms if len(term) >= 3]
    if indexed:
        # Quoted MATCH strings escape embedded quotes, operators and punctuation.
        expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in indexed)
        clauses.append("sequence IN (SELECT rowid FROM memory_fts WHERE memory_fts MATCH ?)")
        args.append(expression)
    for term in terms:
        clauses.append("(instr(content, ?) > 0 OR instr(topic, ?) > 0)")
        args.extend([term, term])
    return clauses, args


def verify_query(connection, terms, *, evaluated_at, include_expired):
    """Read-only logical documents and complete current-query coverage, not forensic health.

    Caller holds the same read snapshot through payload selection. Never repair or
    load private text solely to diagnose drift. Pagination cannot hide omissions.
    """
    for table in ("records", "memory_fts_content"):
        if len(connection.execute(f"SELECT 1 FROM {table} LIMIT 1001").fetchall()) > 1000:
            raise MemoryError("record_limit" if table == "records" else "index_stale")
    if (
        connection.execute(
            "SELECT 1 FROM records r LEFT JOIN memory_fts_content f ON f.id=r.sequence "
            "WHERE r.status='active' AND "
            "(f.id IS NULL OR f.c0 IS NOT r.content OR f.c1 IS NOT r.topic) "
            "LIMIT 1"
        ).fetchone()
        or connection.execute(
            "SELECT 1 FROM memory_fts_content f LEFT JOIN records r ON r.sequence=f.id "
            "WHERE r.sequence IS NULL OR r.status!='active' LIMIT 1"
        ).fetchone()
    ):
        raise MemoryError("index_stale")
    scope, scope_args = ["status='active'"], []
    if not include_expired:
        scope.append("(expires_at IS NULL OR expires_at>?)")
        scope_args.append(evaluated_at)
    indexed, indexed_args = term_filter(terms)
    literal = ["(instr(content, ?) > 0 OR instr(topic, ?) > 0)" for _ in terms]
    literal_args = [part for term in terms for part in (term, term)]

    def ids(clauses, args):
        return set(
            connection.execute(
                f"SELECT sequence FROM records WHERE {' AND '.join(scope + clauses)} LIMIT 1001",
                [*scope_args, *args],
            ).fetchall()
        )

    if ids(literal, literal_args) != ids(indexed, indexed_args):
        raise MemoryError("index_stale")
