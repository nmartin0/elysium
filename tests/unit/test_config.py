"""Tests for core/config.py -- generic YAML loading."""

from core.config import load_yaml


def test_load_yaml_parses_simple_mapping(tmp_path):
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("a: 1\nb:\n  c: 2\n")

    result = load_yaml(yaml_file)

    assert result == {"a": 1, "b": {"c": 2}}


def test_load_yaml_parses_list(tmp_path):
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("items:\n  - one\n  - two\n")

    result = load_yaml(yaml_file)

    assert result == {"items": ["one", "two"]}
