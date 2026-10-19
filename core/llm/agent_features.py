"""Four agent changes that wait on a measurement, each behind a switch.

THE RULE THEY WAIT ON: this project does not change what the model sees
or the steps it may take without measuring the change on a real model
(BLOCKING.md, agent-loop efficiency). Every one of these does. So each
is BUILT, tested without a model, and OFF -- until one bench session
(scripts/feature_bench.py) on the deployment's own model says which to
turn on. Off, the prompt is byte-for-byte what it was.

  filter_operators     the agent may write a filter VALUE as a condition
                       -- {"in": [...]}, {"min": .., "max": ..},
                       {"start": .., "end": ..}, {"contains": ".."} --
                       the vocabulary core/filters.py already gives the
                       UI (F-18, LB-2).
  search_result_cap    at most this many ids from one search reach the
                       model, with the total and a note saying how to
                       count or narrow instead (context rot, AL-3).
  free_text_search     a search_text step: the free-text search the UI
                       already has, instead of guessing an exact value
                       (LB-8).
  meaning_search       a search_meaning step: records ranked by what their
                       text MEANS (R45), for types that declare
                       semantic_search -- the same ranking Browse shows
                       as "Related in meaning". Needs llm.embedding_model.
  remember_from_query  a remember step, honoured only when the person's
                       question itself asks for something to be
                       remembered (E-14's "written only when a person
                       asks").
  brief_answers        the answer is asked to be as short as the question
                       allows (19 October). On a CPU the answer is the
                       one long thing the model writes, at ~1.5 tokens a
                       second. Off until the bench's `brief` arm says the
                       answers still state their facts.

AND ONE LIMIT THAT IS ON, because it changes nothing the model is shown:
answer_max_tokens, 400 unless said (null for none), the most an answer
may run to before it is cut -- a guard against a runaway, as the step
replies already have, and a cut answer says it was cut.

Declared under `agent:` in config.yaml with these names.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentFeatures:
    filter_operators: bool = False
    search_result_cap: "int | None" = None
    free_text_search: bool = False
    remember_from_query: bool = False
    meaning_search: bool = False
    brief_answers: bool = False
    #: Not a switch: a limit, on by default. See the module docstring.
    answer_max_tokens: "int | None" = 400

    @property
    def names_on(self) -> tuple[str, ...]:
        on = []
        if self.filter_operators:
            on.append("filter_operators")
        if self.search_result_cap is not None:
            on.append(f"search_result_cap={self.search_result_cap}")
        if self.free_text_search:
            on.append("free_text_search")
        if self.remember_from_query:
            on.append("remember_from_query")
        if self.meaning_search:
            on.append("meaning_search")
        if self.brief_answers:
            on.append("brief_answers")
        return tuple(on)


OFF = AgentFeatures()

DEFAULT_ANSWER_MAX_TOKENS = 400
#: Below this an ordinary answer naming a few records is cut; above it a
#: limit no longer guards anything on this hardware.
MIN_ANSWER_TOKENS = 32
MAX_ANSWER_TOKENS = 4096


def features_from_config(agent: dict) -> AgentFeatures:
    """The `agent:` block's switches, refused when malformed rather than
    read loosely: a switch typed wrong should fail at load, not leave a
    measured behaviour quietly off."""
    def flag(name: str) -> bool:
        value = agent.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(f"config.yaml agent.{name} must be true or false, got {value!r}.")
        return value

    cap = agent.get("search_result_cap")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        raise ValueError(f"config.yaml agent.search_result_cap must be a whole number of at "
                         f"least 1, or absent; got {cap!r}.")
    limit = agent.get("answer_max_tokens", DEFAULT_ANSWER_MAX_TOKENS)
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or not MIN_ANSWER_TOKENS <= limit <= MAX_ANSWER_TOKENS):
        raise ValueError(f"config.yaml agent.answer_max_tokens must be a whole number from "
                         f"{MIN_ANSWER_TOKENS} to {MAX_ANSWER_TOKENS}, or null for no limit; "
                         f"got {limit!r}.")
    return AgentFeatures(filter_operators=flag("filter_operators"), search_result_cap=cap,
                         free_text_search=flag("free_text_search"),
                         remember_from_query=flag("remember_from_query"),
                         meaning_search=flag("meaning_search"),
                         brief_answers=flag("brief_answers"), answer_max_tokens=limit)
