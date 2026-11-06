"""Offline synthetic voice checks; no capture, credentials or provider setup."""

import argparse
import json


def setup_voice_cli(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("voice", help="Check offline synthetic voice contracts")
    commands = parser.add_subparsers(dest="voice_command", required=True)
    commands.add_parser(
        "self-test",
        help="Run fixed in-memory simulation checks; does not enable voice or call providers",
    )


def run_voice_cli(args: argparse.Namespace) -> int:
    if args.voice_command != "self-test":
        raise ValueError("unsupported synthetic voice command")
    from .voice import run_voice_self_test

    report = run_voice_self_test()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "ok" else 1
