"""Bounded literal query planning for automatic recall, never semantic expansion.

Chinese question scaffolding is a retrieval boundary, not an interpretation of
facts or negation. Every emitted term occurs verbatim in the current input.
Explicit backend search/recall requests never pass through this planner.
"""

import json
import re

from .memory_backend import MemoryError, _text

# A deliberately small closed list of question/function words. Longest match
# wins (e.g. 哪天 before 哪). No domain vocabulary, names or source history is used.
_BOUNDARIES = (
    "请说一下",
    "告诉我",
    "帮我",
    "查一下",
    "查询",
    "请问",
    "记得",
    "一下",
    "为什么",
    "怎么样",
    "什么时候",
    "什么",
    "多少",
    "哪里",
    "哪天",
    "哪家",
    "哪个",
    "哪些",
    "如何",
    "怎样",
    "是否",
    "喜欢",
    "想要",
    "想知道",
    "可以",
    "应该",
    "需要",
    "关于",
    "我",
    "你",
    "他",
    "她",
    "它",
    "的",
    "是",
    "在",
    "和",
    "与",
    "及",
    "吗",
    "呢",
    "了",
    "有",
    "不",
    "要",
    "想",
    "能",
    "会",
    "把",
    "给",
    "对",
    "从",
    "到",
    "请",
    "喝",
    "吃",
)
_BOUNDARY = re.compile("|".join(sorted(_BOUNDARIES, key=len, reverse=True)))
_CHUNKS = re.compile(r"[^\W_]+(?:[-_][^\W_]+)*")
# Han runs are separated from adjacent Latin words/numbers, keeping those intact.
_RUNS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\u3400-\u4dbf\u4e00-\u9fff]+")
_HAN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")


def automatic_recall_terms(query):
    """At most eight distinct, case-sensitive literal terms from <=2048 chars.

    Only Chinese runs gain question-boundary splitting. Other scripts retain
    the existing literal chunk behavior. This is intentionally not a tokenizer,
    synonym dictionary, name resolver, answer generator or injection detector.
    """
    if type(query) is not str or len(query) > 2048 or query.lstrip().startswith("/"):
        return []
    try:
        _text(query, 2048, empty=True, multiline=True)
    except MemoryError:
        return []
    terms = []
    for chunk in _CHUNKS.findall(query):
        for run in _RUNS.findall(chunk):
            parts = _BOUNDARY.split(run) if _HAN.fullmatch(run) else _CHUNKS.findall(run)
            for part in parts:
                if part and len(part) <= 128 and part not in terms:
                    terms.append(part)
                    if len(terms) == 8:
                        return terms
    return terms


def filter_automatic_recall(data, query, terms):
    """Conservatively filter one bounded pack; never query again or widen budgets.

    Only changed Han query plans with multiple terms need two literal matches.
    Existing explicit/unsplit lookup semantics remain unchanged. Counts refer to
    the backend's original literal-match snapshot; removed records are omitted,
    not asserted absent. This is a relevance heuristic, not identity resolution.
    """
    original = []
    for chunk in _CHUNKS.findall(query):
        if len(chunk) <= 128 and chunk not in original:
            original.append(chunk)
            if len(original) == 8:
                break
    if len(terms) < 2 or terms == original or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", query):
        return data
    result = dict(data)
    result["items"] = [r for r in data["items"] if len(r["matched_queries"]) >= 2]
    removed = len(data["items"]) - len(result["items"])
    result["omitted_records"] += removed
    result["items_json_chars"] = len(json.dumps(result["items"], ensure_ascii=True, sort_keys=True))
    result["automatic_filter"] = {
        "minimum_matched_terms": 2,
        "filtered_returned_records": removed,
        "refilled": False,
    }
    return result
