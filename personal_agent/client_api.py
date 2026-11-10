"""Shared client wire diagnostics; not HTTP admission or a native auth adapter.

The existing local CLI/model-tool permissions cannot authorize remote reads. This
module deliberately takes no identity/configuration arguments and never advertises
unimplemented shared endpoints, even when local capabilities are active.
"""

CONTRACT_VERSION = "0.1.0"
SCHEMA_VERSION = "personal.api.v1"
CAPABILITY_IDS = (
    "tasks.list",
    "approvals.read",
    "approvals.respond",
    "changes.poll",
    "conversations.resume",
    "memory.read",
    "memory.write",
)


def build_client_capabilities() -> dict[str, object]:
    """Build non-personal metadata without probing host state or opening a listener."""
    return {
        "schema_version": SCHEMA_VERSION,
        "data": {
            "contract_version": CONTRACT_VERSION,
            "backend": {"id": "hermes"},
            "capabilities": [
                {
                    "id": capability,
                    "supported": False,
                    "enabled": False,
                    "available": False,
                    "reason": "identity_unavailable",
                    "remediation": {
                        "kind": "operator_action",
                        "message": (
                            "A verified host identity adapter and shared route "
                            "implementation are required."
                        ),
                    },
                }
                for capability in CAPABILITY_IDS
            ],
            "transport": {"polling": False, "sse": False},
            "limits": {"max_page_size": 64},
        },
    }
