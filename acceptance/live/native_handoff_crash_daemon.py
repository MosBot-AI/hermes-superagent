"""Run the stock Gateway and interrupt just one fixture handoff transaction."""

import json
import os
import runpy
import sqlite3
import sys
from pathlib import Path

from native_bot_socket_guard import activate_child

CRASH_EXIT = 74


def run():
    activate_child(extra_unix_roots=(Path(os.environ["XDG_RUNTIME_DIR"]),))
    case = json.loads(os.environ["HERMES_HANDOFF_ACCEPTANCE_CRASH"])
    stage = case["stage"]
    home = Path(os.environ["HERMES_HOME"])
    marker = home.parent / "handoff-crash.json"
    ledger = home / "plugin-data/hermes-personal-agent/kanban-handoff/receipts.sqlite3"
    native = Path(case["native_path"]).as_uri() + "?mode=rw"
    connect = sqlite3.connect
    if stage == "after_claim":
        database = str(ledger)
        prefix = "UPDATE handoffs SET state='claimed'"
        token = case["id"]
    elif stage in ("before_native_commit", "after_native_commit"):
        database = native
        prefix = "INSERT INTO tasks "
        token = case["key"]
    else:
        raise ValueError("Unknown fixture handoff crash boundary")

    def connect_with_fault(path, *args, **kwargs):
        if str(path) == database:
            base = kwargs.get("factory", sqlite3.Connection)

            class CommitFault(base):
                armed = False

                def execute(self, sql, parameters=(), /):
                    if self.armed and sql == "COMMIT":
                        journal_mode = super().execute("PRAGMA journal_mode").fetchone()[0]
                        if stage != "before_native_commit":
                            super().execute(sql, parameters)
                        marker.write_text(
                            json.dumps(
                                {
                                    "stage": stage,
                                    "in_transaction": self.in_transaction,
                                    "journal_mode": journal_mode,
                                }
                            ),
                            encoding="utf-8",
                        )
                        os._exit(CRASH_EXIT)
                    cursor = super().execute(sql, parameters)
                    if sql.lstrip().startswith(prefix) and token in parameters:
                        self.armed = True
                    return cursor

            # The native connection still implements the host's tracking lifecycle.
            kwargs["factory"] = CommitFault
        return connect(path, *args, **kwargs)

    sqlite3.connect = connect_with_fault
    sys.path.insert(0, str(Path.cwd()))
    runpy.run_module("gateway.run", run_name="__main__")


if __name__ == "__main__":
    run()
