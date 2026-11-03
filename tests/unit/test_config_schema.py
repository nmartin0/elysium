"""
A key nothing reads is refused at load, with the file, the key path and
the nearest valid key (core/config_schema.py).

`agnet:` for `agent:`, a field's `colum:`, a user's `regoin:`, a silo's
`adaptor:` -- each used to load cleanly and do nothing, so a misspelling
looked exactly like a setting that was working.

The shipped configurations are the other half: a model that forgot a
key the loader reads would refuse a good deployment, so every shipped
set is loaded through it.
"""

import re
import shutil
from pathlib import Path

import pytest
import yaml

from core.config import load_yaml
from core.config_schema import MODELS, unknown_key_findings, unknown_keys
from core.deployment_loader import load_deployment
from scripts.lint_deployment import lint_deployment

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "tests" / "integration" / "fixtures"
FILES = ("config.yaml", "ontology_schema.yaml", "policy.yaml", "data_silos.yaml")
SHIPPED = [ROOT / "deployment" / "etc", ROOT / "templates", FIXTURES, FIXTURES / "other_deployment"]


def _deployment(tmp_path) -> Path:
    for name in FILES:
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path


def _edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


# --- the shipped configurations are accepted ------------------------------

@pytest.mark.parametrize("directory", SHIPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_shipped_file_is_accepted(directory):
    checked = 0
    for name in (*FILES, "source_bindings.yaml"):
        path = directory / name
        if not path.exists():
            continue
        data = load_yaml(path)
        if name == "source_bindings.yaml" and "object_types" not in data:
            data = {"object_types": data}
        assert unknown_keys(name, data) == [], f"{directory}/{name}"
        checked += 1
    assert checked >= 4


def test_every_commented_example_in_a_shipped_config_is_accepted():
    """The documentation is configuration too: an example that would be
    refused when uncommented is a trap. `mirror: warehouse:` was one (the
    path belongs under `mirror.storage`)."""
    examples = 0
    for path in (ROOT / "deployment" / "etc" / "config.yaml", ROOT / "templates" / "config.yaml"):
        block = None
        blocks = []
        for line in path.read_text().splitlines():
            if re.match(r"^# [a-z_]+:", line):
                block = [line[2:]]
                blocks.append(block)
            elif block is not None and re.match(r"^#   \S", line):
                block.append(line[2:])
            elif block is not None and not re.match(r"^#\s*$", line):
                block = None
        for lines in blocks:
            data = yaml.safe_load("\n".join(lines))
            if isinstance(data, dict):
                examples += 1
                assert unknown_keys("config.yaml", data) == [], f"{path}: {lines[0]}"
    assert examples >= 8


def test_every_file_with_keys_to_check_has_a_model():
    assert set(MODELS) == {"config.yaml", "ontology_schema.yaml", "source_bindings.yaml",
                           "policy.yaml", "data_silos.yaml"}


# --- what is refused, and what the message says ---------------------------

CASES = [
    # (file, document, the key path in the message, the nearest valid key)
    ("config.yaml", {"agnet": {}}, "agnet", "agent"),
    ("config.yaml", {"agent": {"max_hop": 3}}, "agent.max_hop", "max_hops"),
    ("config.yaml", {"llm": {"provder": "x"}}, "llm.provder", "provider"),
    ("config.yaml", {"writes": {"pending_write_ttl_minute": 1}}, "writes.pending_write_ttl_minute",
     "pending_write_ttl_minutes"),
    ("config.yaml", {"mirror": {"retain_publication": 3}}, "mirror.retain_publication",
     "retain_publications"),
    ("ontology_schema.yaml", {"object_types": {"C": {"fields": {"n": {"colum": "x"}}}}},
     "object_types.C.fields.n.colum", "column"),
    ("ontology_schema.yaml", {"object_types": {"C": {"storage": {"tabel": "t"}}}},
     "object_types.C.storage.tabel", "table"),
    ("ontology_schema.yaml", {"object_types": {"C": {"id_fiel": "x"}}},
     "object_types.C.id_fiel", "id_field"),
    ("ontology_schema.yaml", {"object_types": {"C": {"security": {"fiel": "region"}}}},
     "object_types.C.security.fiel", "field"),
    ("ontology_schema.yaml", {"link_types": {"L": {"cardinalty": "one"}}},
     "link_types.L.cardinalty", "cardinality"),
    ("ontology_schema.yaml", {"action_types": {"A": {"sub_writes": [{"operaton": "update"}]}}},
     "action_types.A.sub_writes[0].operaton", "operation"),
    ("ontology_schema.yaml", {"action_types": {"A": {"parameters": {"p": {"requird": True}}}}},
     "action_types.A.parameters.p.requird", "required"),
    ("ontology_schema.yaml", {"action_types": {"A": {"affected_object_type": []}}},
     "action_types.A.affected_object_type", "affected_object_types"),
    ("policy.yaml", {"roles": {"r": {"allowed_action": []}}}, "roles.r.allowed_action",
     "allowed_actions"),
    ("policy.yaml", {"security_attribute": "region", "users": {"u": {"role": "r", "regoin": "x"}}},
     "users.u.regoin", "region"),
    ("data_silos.yaml", {"data_silos": {"s": {"adaptor": "sqlite"}}}, "data_silos.s.adaptor",
     "adapter"),
    ("source_bindings.yaml", {"object_types": {"C": {"fields": {"n": {"colum": "x"}}}}},
     "object_types.C.fields.n.colum", "column"),
]


@pytest.mark.parametrize("filename,document,path,nearest", CASES)
def test_a_misspelt_key_is_named_with_its_file_path_and_nearest_key(filename, document, path, nearest):
    [message] = unknown_keys(filename, document)

    assert message.startswith(f"{filename}: ")
    assert f"`{path}`" in message
    assert f"did you mean `{nearest}`?" in message


def test_a_key_with_no_near_match_lists_the_valid_ones():
    [message] = unknown_keys("config.yaml", {"agent": {"zzzzzz": 1}})

    assert "did you mean" not in message
    assert "max_hops" in message


def test_the_word_forms_of_security_are_accepted():
    for word in ("unrestricted", "inherit"):
        assert unknown_keys("ontology_schema.yaml", {"object_types": {"C": {"security": word}}}) == []
    assert unknown_keys("ontology_schema.yaml", {"object_types": {"C": {
        "security": {"via_field": "owner"}}}}) == []


def test_the_free_form_blocks_accept_any_key():
    """An adapter's own arguments and the mirror's storage options are
    not Elysium's to enumerate."""
    assert unknown_keys("data_silos.yaml", {"data_silos": {"s": {
        "adapter": "x", "connection": {"anything_the_adapter_reads": 1}}}}) == []
    assert unknown_keys("config.yaml", {"mirror": {"storage": {"warehouse": "/w", "s3.region": "x"}},
                                         "llm": {"connection": {"keep_alive": -1}}}) == []


def test_the_author_is_told_where_the_criteria_go_not_that_the_key_is_unknown():
    """Action-level submission_criteria has its own, better message
    (core/ontology/submission_criteria.py); this must not pre-empt it."""
    assert unknown_keys("ontology_schema.yaml",
                        {"action_types": {"A": {"submission_criteria": []}}}) == []


def test_a_wrong_value_is_not_this_files_to_report():
    """Values keep their existing checks and messages."""
    assert unknown_keys("config.yaml", {"agent": {"max_hops": "many"}}) == []
    assert unknown_keys("ontology_schema.yaml", {"object_types": ["not", "a", "mapping"]}) == []
    assert unknown_keys("config.yaml", ["not a mapping"]) == []


def test_findings_carry_the_location_so_a_line_can_be_found():
    [(location, _)] = unknown_key_findings("ontology_schema.yaml", {
        "action_types": {"A": {"sub_writes": [{"operaton": "update"}]}}})

    assert location == ("action_types", "A", "sub_writes", 0, "operaton")


# --- the loader and the linter both refuse --------------------------------

def test_the_loader_refuses_a_misspelt_setting(tmp_path):
    directory = _deployment(tmp_path)
    _edit(directory / "config.yaml", lambda d: d["agent"].update(max_hop=3))

    with pytest.raises(ValueError, match=r"config\.yaml: unknown key `agent\.max_hop`; did you mean `max_hops`"):
        load_deployment(directory)


def test_the_loader_refuses_a_misspelt_field_key_in_the_ontology(tmp_path):
    directory = _deployment(tmp_path)

    def change(d):
        d["object_types"]["Customer"]["fields"]["name"]["colum"] = "name"
    _edit(directory / "ontology_schema.yaml", change)

    with pytest.raises(ValueError, match=r"`object_types\.Customer\.fields\.name\.colum`"):
        load_deployment(directory)


def test_the_loader_refuses_a_misspelt_user_and_silo_key(tmp_path):
    directory = _deployment(tmp_path)
    _edit(directory / "policy.yaml", lambda d: d["users"]["user_alice"].update(regoin="x"))
    _edit(directory / "data_silos.yaml",
          lambda d: d["data_silos"]["primary_sql"].update(adaptor="sqlite"))

    with pytest.raises(ValueError) as caught:
        load_deployment(directory)

    # every file at once, so one edit pass fixes them all
    assert "`users.user_alice.regoin`" in str(caught.value)
    assert "`data_silos.primary_sql.adaptor`" in str(caught.value)


def test_the_loader_checks_the_bindings_file(tmp_path):
    directory = _deployment(tmp_path)
    (directory / "source_bindings.yaml").write_text(
        "object_types:\n  Customer:\n    storage: {silo: primary_sql, tabel: customers}\n")

    with pytest.raises(ValueError, match=r"source_bindings\.yaml: unknown key"):
        load_deployment(directory)


def test_the_unmodified_fixture_still_loads(tmp_path):
    """The other half: refusing must not touch a good deployment."""
    assert load_deployment(_deployment(tmp_path)) is not None


def test_the_linter_reports_the_same_keys_with_their_lines(tmp_path, capsys):
    directory = _deployment(tmp_path)
    _edit(directory / "config.yaml", lambda d: d["agent"].update(max_hop=3))
    _edit(directory / "policy.yaml", lambda d: d["users"]["user_alice"].update(regoin="x"))

    assert lint_deployment(directory) is False

    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "config.yaml: unknown key `agent.max_hop`; did you mean `max_hops`?" in out
    assert "(config.yaml, line " in out
    assert "policy.yaml: unknown key `users.user_alice.regoin`" in out


def test_the_linter_accepts_the_unmodified_fixture(tmp_path):
    assert lint_deployment(_deployment(tmp_path)) is True


def test_action_level_criteria_still_get_their_own_message(tmp_path):
    directory = _deployment(tmp_path)

    def change(d):
        action = next(iter(d["action_types"].values()))
        action["submission_criteria"] = []
    _edit(directory / "ontology_schema.yaml", change)

    with pytest.raises(ValueError, match="each sub_write"):
        load_deployment(directory)
