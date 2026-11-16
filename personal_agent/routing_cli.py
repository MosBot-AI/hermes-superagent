"""Explicit local CLI diagnostics only; no model or slash-command surface."""

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from .routing_inspection import inspect_saved_routing, inspection_failure
from .routing_inventory import inspect_saved_inventory, inventory_failure
from .task_cli import current_profile_home


def setup_routing_cli(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "routing", help="Inspect saved routing declarations without calls"
    )
    commands = parser.add_subparsers(dest="routing_command", required=True)
    commands.add_parser(
        "inspect", help="Read saved local delegation settings; does not resolve or enable routing"
    )
    inventory = commands.add_parser(
        "inventory", help="Validate the saved route capability registry"
    )
    inventory.add_argument("--route", metavar="ID", help="Inspect one exact saved route ID")


class RoutingInspector:
    """A native registration's profile-bound read-only diagnostic lifetime."""

    def __init__(self, bound_home: Path):
        self.bound_home = bound_home
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def inspect(self) -> dict:
        return self._read(inspect_saved_routing, inspection_failure)

    def inventory(self, route_id: str | None) -> dict:
        return self._read(lambda raw: inspect_saved_inventory(raw, route_id), inventory_failure)

    def _read(self, evaluate: Callable[[object], dict], failure: Callable[[str], dict]) -> dict:
        if self.closed:
            return failure("inspector_closed")
        try:
            from agent.safe_worker_policy import (  # ty: ignore[unresolved-import]
                worker_config_snapshot,
            )
            from hermes_cli.config_backend import (  # ty: ignore[unresolved-import]
                FileBackend,
                get_config_backend,
            )

            if worker_config_snapshot() is not None:
                return failure("unsupported_runtime")
            if not self.bound_home.is_dir() or current_profile_home() != self.bound_home:
                return failure("profile_context_changed")
            # Select through the host's supported backend API. Do not bypass a
            # remote backend by opening its local config.yaml shadow directly.
            backend = get_config_backend()
            if type(backend) is not FileBackend:
                return failure("unsupported_config_backend")
            try:
                raw = backend.read_user_doc(self.bound_home)
            except FileNotFoundError:
                raw = {}
            if self.closed:
                return failure("inspector_closed")
            if current_profile_home() != self.bound_home:
                return failure("profile_context_changed")
            return evaluate({} if raw is None else raw)
        except SystemExit:
            return failure("unsupported_config_backend")
        except ImportError:
            return failure("host_inspection_unavailable")
        except Exception:
            return failure("saved_configuration_unreadable")

    def run(self, args: argparse.Namespace) -> int:
        if args.routing_command == "inspect":
            result = self.inspect()
        elif args.routing_command == "inventory":
            result = self.inventory(args.route)
        else:
            raise ValueError("unsupported routing diagnostic")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
