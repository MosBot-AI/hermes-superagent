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
