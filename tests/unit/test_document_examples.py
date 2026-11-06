"""Documentation examples are valid JSON, not validated API implementations."""

import pytest

from scripts.check_docs import check_json_examples


def test_complete_json_examples_and_non_json_code():
    content = '```json\n{"revision": 1, "enabled": false}\n```\n```text\nnot JSON\n```'
    assert check_json_examples(content) == (1, [])


@pytest.mark.parametrize("body", ['{"revision": ...}', '{"revision": 1,}', "NaN", ""])
def test_invalid_json_examples_report_the_opening_line(body):
    count, errors = check_json_examples(f"Title\n\n```json\n{body}\n```")
    assert count == 1
    assert len(errors) == 1
    assert errors[0].startswith("invalid JSON example at line 3:")


def test_unterminated_json_example_is_an_error():
    assert check_json_examples('```json\n{"revision": 1}') == (
        0,
        ["unterminated JSON example at line 1"],
    )


@pytest.mark.parametrize("relative", ["experiments/review/README.md", "THIRD_PARTY_NOTICES.md"])
def test_bilingual_checker_covers_review_artifacts_and_notices(
    tmp_path, monkeypatch, capsys, relative
):
    import json

    from scripts import check_docs

    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# English document\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    assert check_docs.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["files"] == 1
    assert report["errors"] == [f"{relative}: Chinese counterpart missing"]
