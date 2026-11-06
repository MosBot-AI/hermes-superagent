#!/usr/bin/env python3
"""Check links, bilingual structure and JSON syntax, not semantic or API validity."""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINKS = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def anchors(path: Path) -> set[str]:
    content = path.read_text(encoding="utf-8")
    found = set(re.findall(r"<a\s+(?:name|id)=[\"']([^\"']+)", content))
    counts: Counter[str] = Counter()
    in_code = False
    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        match = re.match(r"^#{1,6}\s+(.+)", line)
        if in_code or not match:
            continue
        value = match[1].strip().rstrip("#").strip().lower()
        value = re.sub(r"<[^>]*>", "", value)
        value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"[^\w\-\s]", "", value).replace(" ", "-")
        number = counts[value]
        counts[value] += 1
        found.add(value + (f"-{number}" if number else ""))
    return found


def external_urls(content: str) -> Counter[str]:
    return Counter(url for url in LINKS.findall(content) if urlsplit(url).scheme)


def check_json_examples(content: str) -> tuple[int, list[str]]:
    """Validate fenced JSON examples without claiming schema conformance."""
    errors = []
    count = 0
    opening = 0
    language = None
    lines: list[str] = []

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-JSON constant: {value}")

    for number, line in enumerate(content.splitlines(), 1):
        fence = line.strip()
        if language is None and fence.startswith("```"):
            language = fence[3:].strip()
            opening = number
            lines = []
        elif language is not None and fence == "```":
            if language == "json":
                count += 1
                try:
                    json.loads("\n".join(lines), parse_constant=reject_constant)
                except ValueError as error:
                    errors.append(f"invalid JSON example at line {opening}: {error}")
            language = None
        elif language is not None:
            lines.append(line)
    if language == "json":
        errors.append(f"unterminated JSON example at line {opening}")
    return count, errors


def check_pair(path: Path, content: str) -> list[str]:
    translated = path.with_name(path.stem + "-zh.md")
    if not translated.exists():
        return ["Chinese counterpart missing"]
    chinese = translated.read_text(encoding="utf-8")
    errors = []
    if f"]({translated.name})" not in content or f"]({path.name})" not in chinese:
        errors.append("reciprocal language navigation missing")
    for number, line in enumerate(content.splitlines(), 1):
        if re.search(r"[\u4e00-\u9fff]", line) and "简体中文" not in line:
            errors.append(f"Chinese text remains outside navigation at line {number}")
    if external_urls(content) != external_urls(chinese):
        errors.append("external source URL counts differ")
    for pattern, label in (
        (r"^#{1,6} ", "headings"),
        (r"^\|", "table rows"),
        (r"^```", "code fences"),
    ):
        if len(re.findall(pattern, content, re.M)) != len(re.findall(pattern, chinese, re.M)):
            errors.append(f"{label} counts differ")
    return errors


def main() -> int:
    files = sorted(ROOT.glob("docs/**/*.md")) + sorted(ROOT.glob("experiments/**/*.md"))
    for pattern in ("README*.md", "CHANGELOG*.md", "THIRD_PARTY_NOTICES*.md"):
        files += sorted(ROOT.glob(pattern))
    errors = []
    checked = 0
    pairs = 0
    json_examples = 0
    for path in files:
        content = path.read_text(encoding="utf-8")
        count, example_errors = check_json_examples(content)
        json_examples += count
        errors.extend(f"{path.relative_to(ROOT)}: {error}" for error in example_errors)
        for raw in LINKS.findall(content):
            url = urlsplit(raw.strip("<>"))
            if url.scheme or raw.startswith("//"):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            checked += 1
            if not target.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing {raw}")
            elif url.fragment and target.suffix == ".md":
                if unquote(url.fragment) not in anchors(target):
                    errors.append(f"{path.relative_to(ROOT)}: missing anchor {raw}")
        if path.stem.endswith("-zh"):
            original = path.with_name(path.stem[:-3] + ".md")
            if not original.exists():
                errors.append(f"{path.relative_to(ROOT)}: English counterpart missing")
            continue
        pairs += 1
        errors.extend(f"{path.relative_to(ROOT)}: {error}" for error in check_pair(path, content))
    print(
        json.dumps(
            {
                "files": len(files),
                "pairs": pairs,
                "local_links_checked": checked,
                "json_examples_checked": json_examples,
                "errors": errors,
            },
            indent=2,
        )
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
