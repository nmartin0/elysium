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
  remember_from_query  a remember step, honoured only when the person's
                       question itself asks for something to be
                       remembered (E-14's "written only when a person
                       asks").

Declared under `agent:` in config.yaml with these names.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentFeatures:
    filter_operators: bool = False
    search_result_cap: "int | None" = None
    free_text_search: bool = False
    remember_from_query: bool = False

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
        return tuple(on)


OFF = AgentFeatures()


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
    return AgentFeatures(filter_operators=flag("filter_operators"), search_result_cap=cap,
                         free_text_search=flag("free_text_search"),
                         remember_from_query=flag("remember_from_query"))
