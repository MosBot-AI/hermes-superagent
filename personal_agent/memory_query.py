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


# Recognize whole, single-clause questions before the legacy character splitter.
# Slots stay verbatim; these are grammatical markers, never domain/name aliases.
_QUESTION_END = r"(?:[？?！!。]+)?"
_WHO = re.compile(r"(.+?)\s*(?:由)?谁\s*([^\W_]+)" + _QUESTION_END + r"$")
_CHOICE = re.compile(
    r"(.+?)(?:喜欢|想要)(?:哪种|哪类|什么类型的)\s*([^\W_]+)" + _QUESTION_END + r"$"
)
_ATTRIBUTE = re.compile(
    r"(.+?)(?:现在|目前)?(?:是|在|为|有)?"
    r"(?:什么时候|哪一天|哪天|哪里|哪儿|多少|什么|谁|哪个|哪些)"
    r"(?:呢|吗)?" + _QUESTION_END + r"$"
)
_PREFIX = re.compile(r"^(?:请问|请告诉我|告诉我|我想知道)\s*")
_SINGLE_CLAUSE = re.compile(r"^[\w\s?？!！。-]+$")


def _slot_terms(slot):
    """Keep Han names/attributes whole, separating only script/word boundaries."""
    return [
        part
        for chunk in _CHUNKS.findall(slot)
        for run in _RUNS.findall(chunk)
        for part in ([run] if _HAN.fullmatch(run) else _CHUNKS.findall(run))
    ]


def _question_terms(query):
    """Return required literal slots only for bounded, recognizable syntax.

    This is not a general parser. In particular, arbitrary Chinese subject/verb
    compounds and multi-clause prompts continue through the historical planner.
    Requiring all slots prevents two words of an entity from replacing evidence
    for its requested attribute. Subject names are never character-stopword split.
    """
    text = _PREFIX.sub("", query.strip(), count=1)
    if not _SINGLE_CLAUSE.fullmatch(text):
        return None
    match = _WHO.fullmatch(text)
    if match:
        subject, attribute = match.groups()
        subject = subject.rstrip().removesuffix("的").rstrip()
    else:
        match = _CHOICE.fullmatch(text)
        if match:
            subject, attribute = match.groups()
        else:
            match = _ATTRIBUTE.fullmatch(text)
            if not match:
                return None
            body = match[1].strip()
            if "的" in body:
                subject, attribute = body.split("的", 1)
            elif re.search(r"(?:现在|目前)", text[len(body) :]) or " " in body:
                subject, attribute = "", body
            else:
                return None
    subject, attribute = subject.strip(), attribute.strip()
    if subject == "我":
        subject = ""
    if not attribute:
        return None
    parts = _slot_terms(subject) + _slot_terms(attribute)
    # A recognized question that exceeds the limit cannot silently discard its
    # late attribute/subject and turn into a broader entity-only lookup.
    terms = list(dict.fromkeys(parts))
    if len(terms) > 8 or any(not term or len(term) > 128 or term not in query for term in terms):
        return []
    return terms


def automatic_recall_terms(query):
    """At most eight distinct, case-sensitive literal terms from <=2048 chars.

    Recognized questions preserve literal subject/attribute slots. Otherwise
    only Chinese runs gain question-boundary splitting. Other scripts retain
    the existing literal chunk behavior. This is intentionally not a tokenizer,
    synonym dictionary, name resolver, answer generator or injection detector.
    """
    if type(query) is not str or len(query) > 2048 or query.lstrip().startswith("/"):
        return []
    try:
        _text(query, 2048, empty=True, multiline=True)
    except MemoryError:
        return []
    planned = _question_terms(query)
    if planned is not None:
        return planned
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

    Recognized multi-slot questions require every slot. Other changed Han plans
    retain the historical two-match rule. Counts refer to
    the backend's original literal-match snapshot; removed records are omitted,
    not asserted absent. This is a relevance heuristic, not identity resolution.
    """
    planned = _question_terms(query)
    required = list(range(len(terms))) if planned == terms and len(terms) >= 2 else None
    original = []
    for chunk in _CHUNKS.findall(query):
        if len(chunk) <= 128 and chunk not in original:
            original.append(chunk)
            if len(original) == 8:
                break
    if required is None and (
        len(terms) < 2 or terms == original or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", query)
    ):
        return data
    result = dict(data)
    result["items"] = [
        record
        for record in data["items"]
        if (
            all(index in record["matched_queries"] for index in required)
            if required is not None
            else len(record["matched_queries"]) >= 2
        )
    ]
    removed = len(data["items"]) - len(result["items"])
    result["omitted_records"] += removed
    result["items_json_chars"] = len(json.dumps(result["items"], ensure_ascii=True, sort_keys=True))
    result["automatic_filter"] = {
        "minimum_matched_terms": len(required) if required is not None else 2,
        "filtered_returned_records": removed,
        "refilled": False,
    }
    if required is not None:
        result["automatic_filter"]["required_query_indices"] = required
    return result
