"""
Constraints enforced on real writes -- at proposal, and again at confirm.

THROUGH A REAL ACTION. The shipped RecategorizeTransactions sets
Transaction.category; a copy of the shipped configuration declares
`one_of` on that field, and the action is proposed and confirmed.

AT CONFIRM TOO, against the CURRENT schema. A proposal made before a
constraint existed must not slip through by being approved after it.
"""

import shutil

import pytest
import yaml

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import ConstraintViolation

PROPOSER = UserRecord("debug", "us-west", "debug")
APPROVER = UserRecord("reviewer", "us-west", "debug")


def _deployment(synced, constrained: bool, name: str):
    """The shipped configuration, constrained or not, over the test's own
    synced data (E-08) -- which used to be a COPY of the developer's data
    directory, credentials and all, and empty on a fresh clone."""
    from core.deployment_loader import build_generation

    config = synced.data_dir.parent / f"etc-{name}"
    shutil.copytree(synced.config_dir, config)
    if constrained:
        path = config / "ontology_schema.yaml"
        schema = yaml.safe_load(path.read_text())
        schema["object_types"]["Transaction"]["fields"]["category"]["constraints"] = {
            "one_of": ["food", "travel"],
        }
        path.write_text(yaml.safe_dump(schema, sort_keys=False))
    return build_generation(config, synced.data_dir, synced.log_dir)


def _propose(generation, category):
    return generation.write_mediator.propose_action(
        PROPOSER, "RecategorizeTransactions",
        {"transaction_ids": ["1"], "new_category": category}, origin="human",
    )


class TestAtProposal:
    def test_a_value_the_field_refuses_is_refused(self, synced_deployment):
        constrained = _deployment(synced_deployment, True, "c")

        with pytest.raises(ConstraintViolation, match="Transaction.category"):
            _propose(constrained, "rent")

    def test_the_message_names_the_value_and_the_rule(self, synced_deployment):
        constrained = _deployment(synced_deployment, True, "c")

        with pytest.raises(ConstraintViolation) as refused:
            _propose(constrained, "rent")

        assert "'rent'" in str(refused.value)
        assert "food" in str(refused.value)

    def test_an_allowed_value_is_proposed(self, synced_deployment):
        assert _propose(_deployment(synced_deployment, True, "c"), "food") is not None

    def test_without_a_constraint_anything_goes(self, synced_deployment):
        """CONSTRAINTS ARE OPT-IN: the shipped deployment declares none,
        and behaves exactly as before."""
        assert _propose(_deployment(synced_deployment, False, "u"), "rent") is not None


class TestAtConfirm:
    def test_a_constraint_added_after_proposal_still_applies(self, synced_deployment):
        """RE-EVALUATED AT THE POINT OF USE. Proposed before the rule
        existed, confirmed after -- and refused."""
        before = _deployment(synced_deployment, False, "before")
        pending = _propose(before, "rent")

        after = _deployment(synced_deployment, True, "after")

        with pytest.raises(ConstraintViolation):
            after.write_mediator.confirm_and_execute(pending, True, approver=APPROVER)
