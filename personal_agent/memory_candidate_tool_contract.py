"""Model-facing candidate proposal only; no review, authority or source fields."""

import re

from .memory_backend import MemoryError, _text

PERSONAL_MEMORY_CANDIDATE_SCHEMA: dict = {
    "name": "personal_memory_candidate",
    "description": (
        "Propose a review-only memory draft from this admitted turn's original user text, "
        "only after explicit candidate-on. This does not write canonical memory. At most "
        "three drafts per turn. Include an exact nonempty quote and its zero-based Python "
        "character offset, not a byte offset. Quotes are evidence of a substring, not proof "
        "of authorship, truth, endorsement, or a faithful paraphrase. Never propose secrets "
        "or permissions. Drafts expire after seven days; plaintext is removed only on a "
        "successful later candidate operation or explicit purge, not by a deletion deadline. "
        "Metadata/retry tombstones remain. A local operator must review "
        "and accept each candidate. Use the same request_id and arguments on uncertain retries."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "content", "quote", "quote_start", "request_id"],
        "properties": {
            "action": {"type": "string", "enum": ["propose"]},
            "content": {"type": "string", "minLength": 1, "maxLength": 2048},
            "topic": {"type": "string", "maxLength": 128},
            "quote": {"type": "string", "minLength": 1, "maxLength": 1024},
            "quote_start": {"type": "integer", "minimum": 0, "maximum": 8192},
            "request_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9._-]{1,128}$",
            },
        },
    },
}


def normalize_candidate_tool_request(arguments: dict) -> dict:
    required = {"action", "content", "quote", "quote_start", "request_id"}
    if (
        type(arguments) is not dict
        or not required <= arguments.keys()
        or arguments.keys() - required - {"topic"}
        or arguments["action"] != "propose"
    ):
        raise MemoryError("invalid_request")
    result = {key: value for key, value in arguments.items() if key != "action"}
    result.setdefault("topic", "")
    for field, limit, empty, multiline in (
        ("content", 2048, False, True),
        ("topic", 128, True, False),
        ("quote", 1024, False, True),
    ):
        if type(result[field]) is not str:
            raise MemoryError("invalid_request")
        _text(result[field], limit, empty=empty, multiline=multiline)
    if (
        type(result["quote_start"]) is not int
        or not 0 <= result["quote_start"] <= 8192
        or type(result["request_id"]) is not str
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", result["request_id"]) is None
    ):
        raise MemoryError("invalid_request")
    return result
