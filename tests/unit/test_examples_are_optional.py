"""The three worked examples can be measured, not just argued about.

They are 1,148 characters of the system prompt. The VM measured prompt
evaluation at 0.104 seconds per character on a cold call, so they cost
about 119 seconds of every cold query -- the largest block after the
schema itself.

THE LITERATURE IS GENUINELY SPLIT, WHICH IS WHY THIS IS A FLAG AND
NOT A DELETION.

Against them: "over-prompting" is a named phenomenon -- excessive
examples reducing performance -- and "Beyond the Few-Shot Paradigm"
measured a 6.7B model at 23.5 zero-shot against 18.0 one-shot, worse
WITH an example. Ours is a 4B model with three, all the same shape,
which is exactly the out-of-distribution case where examples are said
to hinder.

For them: few-shot is recommended precisely "when zero-shot doesn't
work", and each of these was added after a measured failure.

So the default does not change. One run with and one run without, on
the same cases, is the only thing that settles it.
"""

import core.llm.agent_step_prompt as step_prompt
from core.llm.agent_step_prompt import _build_system_prompt

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {"name": {"type": "data", "data_type": "string"}},
    }
}


def _prompt(**kwargs):
    return _build_system_prompt(SCHEMA, [], False, {}, **kwargs)


def test_the_default_keeps_them():
    """NOTHING SHIPS AS A BEHAVIOUR CHANGE until a run says it should.
    A flag that quietly flips the default is a deletion wearing an
    experiment's clothes."""
    assert "Example: to answer" in _prompt()


def test_the_flag_removes_all_three():
    without = _prompt(include_examples=False)

    assert "Example: to answer" not in without
    assert "ExampleType" not in without
    assert "RelatedType" not in without


def test_removing_them_saves_what_it_claims():
    saved = len(_prompt()) - len(_prompt(include_examples=False))

    # ~119 seconds of a cold call, at the measured 0.104 s/char.
    assert 1000 < saved < 1300, saved


def test_no_dangling_reference_is_left_behind():
    """THE COUPLING THAT MADE THIS MORE THAN A DELETE.

    The first IMPORTANT note said "check EVERY ID from a list result
    (like [1, 2] above)" -- and "above" was the third example. Cutting
    the examples would have left the note pointing at nothing, which
    is worse than either arm: a reader, or a model, following a
    reference to text that is not there.

    Reworded to stand alone, so BOTH arms read correctly.
    """
    for prompt in (_prompt(), _prompt(include_examples=False)):
        assert "above) has been asked" not in prompt
        assert "for\nexample [1, 2]) has been asked" in prompt


def test_the_important_notes_survive_either_way():
    """A DIFFERENT CATEGORY, deliberately untouched. The notes are not
    demonstrations -- they are instructions that fixed specific
    measured failures, and the literature indicting examples says
    nothing about them. Cut separately, if at all."""
    for prompt in (_prompt(), _prompt(include_examples=False)):
        assert "IMPORTANT: Before you finish" in prompt
        assert "IMPORTANT: If a previous get_field result is a LIST" in prompt


def test_the_switch_is_off_by_default_at_module_level():
    """The bench sets it; nothing else should. A deployment wanting
    this permanently gets a real config key."""
    assert step_prompt.INCLUDE_EXAMPLES is True
