"""Drive the stock Gateway with a commit-boundary fault in one test transaction."""

import json
import os
import runpy
import sqlite3
import sys
from pathlib import Path

from native_bot_socket_guard import activate_child

CRASH_EXIT = 73


def run():
    activate_child()
    boundary = os.environ.get("HERMES_TASK_ACCEPTANCE_COMMIT")
    if boundary is not None:
        if boundary not in ("before_commit", "after_commit"):
            raise ValueError("Invalid task acceptance crash boundary")
        request_id = os.environ["HERMES_TASK_ACCEPTANCE_REQUEST"]
        home = Path(os.environ["HERMES_HOME"])
        marker = home.parent / "task-commit-boundary.json"
        database = home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
        connect = sqlite3.connect

        class CommitFault(sqlite3.Connection):
            receipt = None

            def execute(self, sql, parameters=(), /):
                if self.receipt is not None and sql == "COMMIT":
                    if boundary == "after_commit":
                        super().execute(sql, parameters)
                    marker.write_text(
                        json.dumps(
                            {
                                "boundary": boundary,
                                "in_transaction": self.in_transaction,
                                "receipt": self.receipt,
                            }
                        ),
                        encoding="utf-8",
                    )
                    os._exit(CRASH_EXIT)
                cursor = super().execute(sql, parameters)
                if sql.startswith("INSERT INTO receipts ") and parameters[0] == request_id:
                    self.receipt = json.loads(parameters[2])
                return cursor

        def connect_with_fault(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and Path(path) == database:
                kwargs["factory"] = CommitFault
            return connect(path, *args, **kwargs)

        sqlite3.connect = connect_with_fault

    sys.path.insert(0, str(Path.cwd()))
    runpy.run_module("gateway.run", run_name="__main__")


if __name__ == "__main__":
    run()
