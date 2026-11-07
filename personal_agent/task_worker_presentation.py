"""Native-client text views only. Never model prompts, commands or storage writes."""

import json
import unicodedata

from .task_worker_ledger import DIAGNOSTIC_EXPLANATIONS

MAX_VIEW_CHARS = 40000


def quoted(value):
    # Keep ordinary CJK/emoji readable, but escape controls, format/bidi marks,
    # lone surrogates and Unicode line separators. JSON already escapes C0.
    # Model-authored text remains quoted data, never executable instructions.
    encoded = json.dumps(value, ensure_ascii=False)
    return "".join(
        json.dumps(char, ensure_ascii=True)[1:-1]
        if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        else char
        for char in encoded
    )


def render_worker_reply(raw):
    result = json.loads(raw)
    if result["status"] == "error":
        return "Planning worker unavailable: " + quoted(result["error"]["code"]) + "."
    data = result["data"]
    if "help" in data:
        text = "Planning worker (review only)\n" + data["help"]
    elif "items" in data:
        lines = [f"Planning requests in this session/route: {data['scope_count']}"]
        for item in data["items"]:
            lines.append(
                quoted(item["request_id"])
                + " | "
                + item["state"]
                + " | task "
                + quoted(item["task_id"])
                + f" | snapshot revision {item['snapshot_revision']}"
            )
        if not data["items"]:
            lines.append("No requests on this page.")
        if data["next_cursor"] is not None:
            lines.append("Next: /personal-plan-worker list --after " + data["next_cursor"])
        lines.append(data["notice"])
        text = "\n".join(lines)
    else:
        lines = []
        if "request_id" in data:
            lines.append("Request: " + quoted(data["request_id"]))
        if "state" in data:
            label = "Worker result" if data.get("native_client_view") else "State"
            lines.append(label + ": " + data["state"])
        if "task_id" in data:
            lines.append("Task: " + quoted(data["task_id"]))
            lines.append(f"Snapshot revision: {data['snapshot_revision']}")
        if "current_revision" in data:
            lines.append(
                f"Current revision: {data['current_revision']}"
                + (" (snapshot is stale)" if data["stale"] else "")
            )
        if "diagnostic" in data:
            diagnostic = data["diagnostic"]
            code = diagnostic["code"]
            if code is not None:
                lines.append("Diagnostic: " + code + ". " + DIAGNOSTIC_EXPLANATIONS[code])
                lines.append(
                    "No retry or key reset was performed. "
                    "Do not use a new key to retry an uncertain outcome."
                )
            attempts = diagnostic["submission_attempts"]
            lines.append(
                "Local callback submission attempts: "
                + ("unknown" if attempts is None else str(attempts))
                + ". Not proof of provider execution, charges or delivery."
            )
        if "draft" in data:
            lines.append(
                "Untrusted draft (quoted):\n" + quoted(data["draft"])
                if data["draft"] is not None
                else "No draft in this terminal receipt."
            )
        for field in ("notice", "delivery_notice", "disclosure"):
            if field in data:
                lines.append(data[field])
        if result.get("replayed"):
            lines.append("Existing request; no new authorization or submission.")
        text = "\n".join(lines)
    if len(text) > MAX_VIEW_CHARS:
        return "Planning worker view exceeds the safe display limit; no draft was displayed."
    return text
