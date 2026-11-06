"""Bounded, non-personal diagnostics. This is not an authorization service."""

from . import HERMES_BASELINE, PLUGIN_ID, VERSION
from .enforcement import build_enforcement_summary


def build_status() -> dict[str, object]:
    """Return a fresh result without consulting credentials, files, or providers."""
    return {
        "schema_version": "personal.status.v1",
        "status": "ok",
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "mode": "read_only",
        "stage": "foundation",
        "compatibility": {
            "target_hermes_commit": HERMES_BASELINE,
            "runtime_commit_verified": False,
            "note": "The baseline is a test target, not a probe of the running host.",
        },
        "capabilities": {
            "diagnostics": True,
            "personal_data_storage": False,
            "identity_binding": False,
            "action_authorization": False,
            "reminders": False,
            "external_delivery": False,
            "worker_model_routing": False,
        },
        "safety": {
            "plugin_write_tools_registered": False,
            "host_write_paths_enforced": False,
            "release_gate": "blocked",
            "reason": "Identity, authorization and write-path coverage are not implemented.",
            "scope": "This plugin does not disable or secure other Hermes tools.",
        },
        "write_path_inventory": build_enforcement_summary(),
    }
