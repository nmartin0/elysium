"""The three worked examples stay, and this records why.

I proposed removing them. They are 1,148 characters, about 119 seconds
of a cold call at the VM's measured 0.104 s/char, and the literature
gave every reason to expect a 4B model to do better without them:
"over-prompting" is a named phenomenon, and "Beyond the Few-Shot
Paradigm" measured a 6.7B model at 23.5 zero-shot against 18.0
one-shot -- worse WITH an example.

SO BOTH ARMS WERE RUN, AND THE ANSWER WAS THE OTHER ONE.

Without the examples, plan mode went from 3 of 3 to 3 of 5, and
link_fanout -- which had PASSED with them, same case, same model --
failed. What the model got wrong:

    a step with no "id" at all
    an invented step name, "get_transaction_amount"
    a list of values in a filter that takes one
    a plan with no steps in it

EVERY ONE IS A FORMAT ERROR. Not one is a reasoning error, and that is
why the literature did not transfer: it indicts examples that teach a
TASK, where they bias a model toward surface patterns instead of
reasoning. These teach a SCHEMA. A model that has never seen the shape
of a plan does not infer it from prose.

This file exists so the next person to notice 119 seconds of examples
finds the experiment already run.
"""

from core.llm.agent_step_prompt import EXAMPLES_SECTION, _build_system_prompt

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {"name": {"type": "data", "data_type": "string"}},
    }
}


def test_the_examples_are_in_the_step_prompt():
    prompt = _build_system_prompt(SCHEMA, [], False, {})

    assert "Example: to answer" in prompt
    assert EXAMPLES_SECTION in prompt


def test_the_examples_are_in_the_plan_prompt_too():
    """PLAN MODE IS WHERE REMOVING THEM BROKE THINGS. Its failures
    were all format: a missing id, an invented step name, a list in a
    scalar filter, an empty plan."""
    plan_prompt = _build_system_prompt(SCHEMA, [], False, {}, data_is_shown=False)

    assert "Example: to answer" in plan_prompt


def test_all_three_examples_are_present():
    """Each shows a different shape -- one field, several fields on one
    object, several objects. Losing any one loses a shape."""
    prompt = _build_system_prompt(SCHEMA, [], False, {})

    assert prompt.count("Example: to answer") == 3
    assert '"step": "get_object"' in prompt
    assert '"field_names": ["f_a", "f_b"]' in prompt


def test_the_important_note_stands_on_its_own():
    """It used to say "(like [1, 2] above)", where "above" WAS the
    third example. That coupling is why removing the examples was
    never a simple delete. Reworded while the experiment was running,
    and kept: it is correct either way and depends on nothing."""
    prompt = _build_system_prompt(SCHEMA, [], False, {})

    assert "above) has been asked" not in prompt
    assert "for\nexample [1, 2]) has been asked" in prompt


def test_nothing_can_switch_them_off():
    """THE EXPERIMENT'S SCAFFOLDING IS GONE, deliberately. A flag left
    behind after its question is answered is a way for the losing arm
    to come back by accident."""
    import inspect

    import core.llm.agent_step_prompt as step_prompt

    assert not hasattr(step_prompt, "INCLUDE_EXAMPLES")
    assert "include_examples" not in inspect.signature(
        step_prompt._build_system_prompt
    ).parameters
