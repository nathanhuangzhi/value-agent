import json

from app.tools.json_io import (
    atomic_write_json,
    jsonl_field_set,
    read_json_array,
    read_jsonl,
)


def test_atomic_write_json_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "out.json"
    atomic_write_json(path, [{"a": 1}])
    assert path.exists()
    assert json.loads(path.read_text()) == [{"a": 1}]


def test_atomic_write_json_replaces_existing(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(path, [{"v": 1}])
    atomic_write_json(path, [{"v": 2}])
    assert json.loads(path.read_text()) == [{"v": 2}]


def test_read_json_array_returns_empty_when_missing(tmp_path):
    assert read_json_array(tmp_path / "missing.json") == []


def test_read_json_array_returns_empty_on_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    assert read_json_array(path) == []


def test_read_json_array_returns_empty_when_root_is_not_array(tmp_path):
    path = tmp_path / "obj.json"
    path.write_text('{"this": "is an object"}')
    assert read_json_array(path) == []


def test_read_jsonl_skips_blank_and_invalid_lines(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(
        '{"ticker": "AAA"}\n'
        "\n"
        "not-json-line\n"
        '{"ticker": "BBB"}\n'
    )
    rows = read_jsonl(path)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB"]


def test_jsonl_field_set_returns_unique_values(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(
        '{"ticker": "AAA"}\n'
        '{"ticker": "BBB"}\n'
        '{"ticker": "AAA"}\n'  # duplicate
    )
    assert jsonl_field_set(path, "ticker") == {"AAA", "BBB"}


def test_jsonl_field_set_handles_missing_file(tmp_path):
    assert jsonl_field_set(tmp_path / "missing.jsonl") == set()
