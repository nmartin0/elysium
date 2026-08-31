"""Tests for core/config.py -- generic YAML loading."""

import pytest
import yaml

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


def test_duplicate_top_level_key_is_rejected(tmp_path):
    # PyYAML's own long-standing, still-open bug (github.com/yaml/
    # pyyaml/issues/165): safe_load() itself silently keeps only the
    # LAST occurrence of a repeated mapping key, zero warning. _Strict
    # SafeLoader closes this at the source.
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("a: 1\na: 2\n")

    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        load_yaml(yaml_file)


def test_duplicate_key_is_rejected_at_any_nesting_level(tmp_path):
    # construct_mapping() is overridden once and runs for EVERY
    # mapping node PyYAML encounters -- proves the rejection isn't
    # only a top-level special case.
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("top:\n  nested:\n    x: 1\n    x: 2\n")

    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        load_yaml(yaml_file)


def test_duplicate_keys_that_are_not_adjacent_are_still_caught(tmp_path):
    # The realistic case -- a large file where a key gets accidentally
    # repeated far from its first occurrence, not two adjacent lines.
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("a: 1\nb: 2\nc: 3\na: 4\n")

    with pytest.raises(yaml.YAMLError, match="duplicate key 'a'"):
        load_yaml(yaml_file)


def test_still_only_ever_produces_plain_data_structures(tmp_path):
    # SECURITY: _StrictSafeLoader is a direct subclass of yaml.
    # SafeLoader, registering no additional constructors of its own --
    # proves this directly, not just by reading the class hierarchy:
    # a YAML tag that would execute arbitrary Python under yaml.load()
    # with the default Loader must still fail (or be rejected) here,
    # exactly as it would under the original yaml.safe_load().
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("bad: !!python/object/apply:os.system ['echo unsafe']\n")

    with pytest.raises(yaml.YAMLError):
        load_yaml(yaml_file)
