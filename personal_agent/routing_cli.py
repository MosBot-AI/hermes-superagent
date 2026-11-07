"""Explicit local CLI diagnostics only; no model or slash-command surface."""

import argparse
import json
from pathlib import Path

from .routing_inspection import inspect_saved_routing, inspection_failure
from .task_cli import current_profile_home


def setup_routing_cli(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "routing", help="Inspect saved routing declarations without calls"
    )
    commands = parser.add_subparsers(dest="routing_command", required=True)
    commands.add_parser(
        "inspect", help="Read saved local delegation settings; does not resolve or enable routing"
    )


class RoutingInspector:
    """A native registration's profile-bound read-only diagnostic lifetime."""

    def __init__(self, bound_home: Path):
        self.bound_home = bound_home
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def inspect(self) -> dict:
        if self.closed:
            return inspection_failure("inspector_closed")
        try:
            from agent.safe_worker_policy import (  # ty: ignore[unresolved-import]
                worker_config_snapshot,
            )
            from hermes_cli.config_backend import (  # ty: ignore[unresolved-import]
                FileBackend,
                get_config_backend,
            )

            if worker_config_snapshot() is not None:
                return inspection_failure("unsupported_runtime")
            if not self.bound_home.is_dir() or current_profile_home() != self.bound_home:
                return inspection_failure("profile_context_changed")
            # Select through the host's supported backend API. Do not bypass a
            # remote backend by opening its local config.yaml shadow directly.
            backend = get_config_backend()
            if type(backend) is not FileBackend:
                return inspection_failure("unsupported_config_backend")
            try:
                raw = backend.read_user_doc(self.bound_home)
            except FileNotFoundError:
                raw = {}
            if self.closed:
                return inspection_failure("inspector_closed")
            if current_profile_home() != self.bound_home:
                return inspection_failure("profile_context_changed")
            return inspect_saved_routing({} if raw is None else raw)
        except SystemExit:
            return inspection_failure("unsupported_config_backend")
        except ImportError:
            return inspection_failure("host_inspection_unavailable")
        except Exception:
            return inspection_failure("saved_configuration_unreadable")

    def run(self, args: argparse.Namespace) -> int:
        if args.routing_command != "inspect":
            raise ValueError("unsupported routing diagnostic")
        result = self.inspect()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
