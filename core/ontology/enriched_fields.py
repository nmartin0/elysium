"""Fields a model fills in, through rules a person approved (R41, R42, R38).

    object_types:
      SupportTicket:
        fields:
          mood:
            enrich:
              from: [subject, body]
              instruction: How the customer feels in this ticket.
              choices: [positive, neutral, negative]

COMPILE FIRST. A model on this deployment's hardware takes 40 to 160
seconds a call, so asking it once per row is not an option at any size
worth enriching. EVAPORATE (Arora et al., VLDB 2024) showed the way
round: have the model write FUNCTIONS once, over a sample, and run those
over every row -- "a 110x reduction in the amount of text the LLM
processes", and, by scoring many candidates against the model's own
direct answers on the sample and keeping the good ones, better than
asking per document. scripts/compile_enrichment.py does that here.

RULES ARE DATA, NEVER CODE (decided 15 October). The paper synthesises
Python; a function written by a model that read the data can be steered
BY the data, and running it is running whatever a ticket's text talked
the model into. So a model may only write the ordered rules below, which
this module checks and applies. A person can read every one of them.

    {"when": [{"field": "subject", "contains_any": ["refund", "angry"]}],
     "then": "negative"}

  - the first rule whose every condition holds gives the value;
  - a condition holds when the field contains ANY of its terms as whole
    words ("sad" does not match "crusade"), compared case-folded;
  - no rule holds: the value is EMPTY, never a guess (R52: nothing is
    imputed into served data).

APPROVED FIRST (decided 15 October). Nothing a recipe would produce is
published until a person approves it, and an approval is tied to the
declaration's hash: change the instruction, the inputs or the choices
and the approval no longer applies -- the field goes empty until a new
recipe is approved, rather than publishing answers to a question nobody
approved.

NEVER A CLASSIFIED INPUT (decided 15 October, R42). A field carrying a
classification label -- pii, financial, anything -- cannot be an input:
whether data may reach a model at all is D3, still open. Refused at
load, so it cannot be switched on by accident.

SEVERAL RULE SETS MAY VOTE (17 October). EVAPORATE-Code+ keeps many
candidate functions and "aggregate[s] their extractions using weak
supervision", dropping any whose estimated accuracy is at or below 0.5,
and beats asking the model per row by 10.1 F1 points. A recipe may
therefore be one rule set, or several MEMBERS each with a weight from
how often it agreed with the model on its examples; each member that
answers votes its weight for its value, the heaviest value wins, and a
tie is empty -- never a coin toss. Every member is still a rule set a
person reads.

    {"combine": "weighted_vote",
     "members": [{"weight": 1.6, "rules": [...]}, {"weight": 0.9, "rules": [...]}]}

CHOICES, OR A VALUE TAKEN FROM THE TEXT (17 October). `choices:` asks
"which of these?"; `extract: true` asks "what does the text say it is?"
-- an order number, an amount, a date -- with the field's `data_type`
saying which kind of value. Its rules are context words plus a fixed
shape, and its value is always a piece of the input; the language, and
why the model never writes a regular expression, is
core/ontology/extraction_rules.py. A field has exactly one of the two.

WHO MAY READ ONE: as for a derived field -- someone who may read the
field AND every input. An inferred mood is a summary of the ticket's
text, and would otherwise hand out what the text says to someone refused
the text.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from core.ontology.classifications import field_classifications
from core.ontology.extraction_rules import (
    MAX_TAKE_WORDS,
    MAX_WITHIN,
    SHAPES_FOR,
    phrase_words,
    take,
)
from core.ontology.extraction_rules import describe as describe_extraction

#: Keys an enriched field may carry beside `enrich`. Like a derived
#: field it has no column, and a constraint on a value nobody enters is
#: a constraint on its inputs. `classification` stays: an inference CAN
#: be sensitive (a health condition read from free text), and R47 is
#: exactly that question.
ALLOWED_BESIDE = frozenset({"enrich", "display_name", "description", "classification",
                            "classifications", "type", "data_type"})
ENRICH_KEYS = frozenset({"from", "instruction", "choices", "extract"})

MAX_INSTRUCTION = 500
MAX_CHOICES = 50
MAX_CHOICE = 80

#: Bounds on what a model may propose. Generous for a rule a person
#: will read, and a bound on what a request or a model may store.
MAX_RULES = 40
#: At most this many rule sets vote in one recipe -- each is read by the
#: person approving it, and more than a handful is not read.
MAX_MEMBERS = 5
#: A member's weight is a log-odds; past this it says nothing more.
MAX_WEIGHT = 10.0
MAX_CONDITIONS = 4
MAX_TERMS = 25
MAX_TERM = 60


@dataclass(frozen=True)
class Enrichment:
    inputs: tuple[str, ...]
    instruction: str
    choices: tuple[str, ...]
    #: For a field whose value is TAKEN FROM the text: the field's data
    #: type (string, integer, decimal or date). None for choices.
    extract: "str | None" = None

    def describe(self) -> str:
        verb = "extracted" if self.extract else "inferred"
        return f"{verb} from {', '.join(self.inputs)}"


def enrichment_of(field: Mapping) -> "Enrichment | None":
    """The parsed declaration, or None for a field that is not enriched.
    Unvalidated: load calls validate_enriched_fields first."""
    declared = field.get("enrich")
    if declared is None:
        return None
    inputs = declared.get("from")
    if isinstance(inputs, str):
        inputs = [inputs]
    extract = (str(field.get("data_type") or "string")
               if declared.get("extract") is True else None)
    return Enrichment(tuple(inputs or ()), str(declared.get("instruction") or "").strip(),
                      tuple(str(choice) for choice in declared.get("choices") or ()), extract)


def enriched_fields(type_def: Mapping) -> dict[str, Enrichment]:
    """{field name: Enrichment} for every enriched field of a type."""
    return {name: enrichment
            for name, field in (type_def.get("fields") or {}).items()
            if (enrichment := enrichment_of(field)) is not None}


def declaration_hash(object_type: str, field_name: str, enrichment: Enrichment) -> str:
    """What an approval is an approval OF. Any change to the question --
    its inputs, its words, its choices -- is a different question."""
    question = {"type": object_type, "field": field_name, "from": list(enrichment.inputs),
                "instruction": enrichment.instruction, "choices": list(enrichment.choices)}
    if enrichment.extract is not None:
        # ONLY WHEN EXTRACTING, so every choices field's hash -- and
        # every approval already given -- is what it was.
        question["extract"] = enrichment.extract
    canonical = json.dumps(question, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_enriched_fields(object_types: Mapping) -> None:
    """Refuses, at load, an enriched field that could never be filled --
    or that would send a classified value to a model."""
    for type_name, type_def in object_types.items():
        fields = type_def.get("fields") or {}
        for field_name, field in fields.items():
            if "enrich" not in field:
                continue
            where = f"{type_name}.{field_name}"
            declared = field["enrich"]
            if not hasattr(declared, "items"):
                raise ValueError(f"{where}: `enrich` must say {{from, instruction}} and either "
                                 f"`choices` or `extract: true`.")
            extra = sorted(set(declared) - ENRICH_KEYS)
            if extra:
                raise ValueError(f"{where}: unknown key(s) {extra} in `enrich`.")
            if "derived" in field:
                raise ValueError(f"{where} cannot be both derived and enriched.")
            beside = sorted(set(field) - ALLOWED_BESIDE)
            if beside:
                raise ValueError(f"{where} is filled in by approved rules, so it has no "
                                 f"stored value; remove {beside}.")
            if field.get("type", "data") != "data":
                raise ValueError(f"{where}: an enriched field is a value, not a {field['type']}.")
            if "extract" in declared and declared["extract"] is not True:
                raise ValueError(f"{where}: `extract` is `true` or left out.")
            if ("choices" in declared) == ("extract" in declared):
                raise ValueError(f"{where}: `enrich` needs exactly one of `choices` (pick one of "
                                 f"these) or `extract: true` (take the value from the text).")
            data_type = field.get("data_type", "string")
            if "extract" in declared:
                if data_type not in SHAPES_FOR:
                    raise ValueError(f"{where}: an extracted value is one of "
                                     f"{sorted(SHAPES_FOR)}; {data_type!r} is not offered yet.")
            elif data_type != "string":
                raise ValueError(f"{where}: an enriched field holds one of its choices, so it "
                                 f"is a string; remove data_type {field['data_type']!r}.")
            enrichment = enrichment_of(field)
            assert enrichment is not None
            _check_inputs(where, field_name, enrichment, fields)
            if not enrichment.instruction:
                raise ValueError(f"{where}: `enrich` needs an instruction -- the question the "
                                 f"model answers for each row.")
            if len(enrichment.instruction) > MAX_INSTRUCTION:
                raise ValueError(f"{where}: the instruction is at most {MAX_INSTRUCTION} "
                                 f"characters.")
            if enrichment.extract is not None:
                continue
            choices = enrichment.choices
            if not 2 <= len(choices) <= MAX_CHOICES:
                raise ValueError(f"{where}: `choices` needs between 2 and {MAX_CHOICES} values; "
                                 f"this version chooses among values the author named.")
            if len({choice.casefold() for choice in choices}) != len(choices):
                raise ValueError(f"{where}: two choices differ only in case.")
            if any(not choice.strip() or len(choice) > MAX_CHOICE for choice in choices):
                raise ValueError(f"{where}: each choice is non-empty text of at most "
                                 f"{MAX_CHOICE} characters.")


def _check_inputs(where: str, field_name: str, enrichment: Enrichment, fields: Mapping) -> None:
    if not enrichment.inputs:
        raise ValueError(f"{where}: `enrich.from` names the fields a value is read from.")
    for name in enrichment.inputs:
        if not isinstance(name, str) or name not in fields:
            raise ValueError(f"{where}: `enrich.from` names {name!r}, which this type does "
                             f"not have.")
        if name == field_name:
            raise ValueError(f"{where} cannot be read from itself.")
        source = fields[name]
        if source.get("type") == "link":
            raise ValueError(f"{where}: {name!r} is a link; enrichment reads text.")
        if "derived" in source or "enrich" in source:
            raise ValueError(f"{where}: {name!r} is computed itself; read the fields it "
                             f"comes from instead.")
        if (source.get("data_type") or "string") != "string":
            raise ValueError(f"{where}: {name!r} is {source['data_type']}; rules match words, "
                             f"so the inputs are text.")
        # R42, AND THE OWNER'S CALL: never a classified value to a model
        # until D3 says data may leave the VM at all.
        labels = field_classifications(source)
        if labels:
            raise ValueError(f"{where}: {name!r} is classified {sorted(labels)}, and a "
                             f"classified field is never sent to a model.")


def fill_enriched_types(object_types: Mapping) -> None:
    """`type: data` and `data_type: string` written into the raw schema,
    so every reader sees one declared type, as fill_result_types does
    for derived fields."""
    for type_def in object_types.values():
        for field in (type_def.get("fields") or {}).values():
            if "enrich" in field:
                field.setdefault("type", "data")
                field.setdefault("data_type", "string")


# ---- the rule language --------------------------------------------------

class RuleError(ValueError):
    """A proposed rule set this module will not run."""


_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text) -> list[str]:
    return _WORD.findall(str(text).casefold()) if text is not None else []


def _contains_phrase(words: list[str], phrase: list[str]) -> bool:
    if not phrase:
        return False
    width = len(phrase)
    return any(words[at:at + width] == phrase for at in range(len(words) - width + 1))


def check_rules(rules, enrichment: Enrichment) -> list[dict]:
    """A rule set as THIS module will run it, or RuleError.

    Everything a model proposes passes through here before it is stored,
    scored or shown: it can name only the declared inputs, conclude only
    a declared choice, and has nothing else to say. The returned rules
    are rebuilt from what was checked, so an extra key a model added
    never reaches storage."""
    if not isinstance(rules, list) or not rules:
        raise RuleError("a recipe is a non-empty list of rules")
    if len(rules) > MAX_RULES:
        raise RuleError(f"at most {MAX_RULES} rules")
    if enrichment.extract is not None:
        return [_check_extraction(index, rule, enrichment)
                for index, rule in enumerate(rules, start=1)]
    by_fold = {choice.casefold(): choice for choice in enrichment.choices}
    checked = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, Mapping):
            raise RuleError(f"rule {index} is not {{when, then}}")
        then = rule.get("then")
        if not isinstance(then, str) or then.casefold() not in by_fold:
            raise RuleError(f"rule {index} concludes {then!r}, which is not one of the choices")
        when = rule.get("when")
        if not isinstance(when, list) or not 1 <= len(when) <= MAX_CONDITIONS:
            raise RuleError(f"rule {index} needs 1 to {MAX_CONDITIONS} conditions")
        conditions = []
        for condition in when:
            if not isinstance(condition, Mapping):
                raise RuleError(f"rule {index} has a condition that is not {{field, contains_any}}")
            field = condition.get("field")
            if field not in enrichment.inputs:
                raise RuleError(f"rule {index} reads {field!r}, which is not an input")
            terms = condition.get("contains_any")
            if (not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS
                    or not all(isinstance(term, str) for term in terms)):
                raise RuleError(f"rule {index}: contains_any is 1 to {MAX_TERMS} words or phrases")
            cleaned = []
            for term in terms:
                words = _words(term)
                if not words or len(term) > MAX_TERM:
                    raise RuleError(f"rule {index}: {term!r} is not a word or phrase of at most "
                                    f"{MAX_TERM} characters")
                cleaned.append(" ".join(words))
            conditions.append({"field": field, "contains_any": sorted(set(cleaned))})
        checked.append({"when": conditions, "then": by_fold[then.casefold()]})
    return checked


_EXTRACTION_KEYS = {"field", "after", "within", "take"}


def _check_extraction(index: int, rule, enrichment: Enrichment) -> dict:
    """One extraction rule as extraction_rules will run it, or RuleError.
    Rebuilt from what was checked, like a choices rule."""
    if not isinstance(rule, Mapping):
        raise RuleError(f"rule {index} is not {{field, after, within, take}}")
    shape = rule.get("take")
    allowed = set(_EXTRACTION_KEYS) | ({"max_words"} if shape == "words" else set())
    if not _EXTRACTION_KEYS <= set(rule) <= allowed:
        raise RuleError(f"rule {index} is {{field, after, within, take}}"
                        + (", with max_words for words" if shape == "words" else ""))
    field = rule["field"]
    if field not in enrichment.inputs:
        raise RuleError(f"rule {index} reads {field!r}, which is not an input")
    assert enrichment.extract is not None
    shapes = SHAPES_FOR[enrichment.extract]
    if shape not in shapes:
        raise RuleError(f"rule {index} takes {shape!r}; a {enrichment.extract} field takes "
                        + " or ".join(shapes))
    within = rule["within"]
    if not isinstance(within, int) or isinstance(within, bool) or not 1 <= within <= MAX_WITHIN:
        raise RuleError(f"rule {index}: within is 1 to {MAX_WITHIN} words")
    phrases = rule["after"]
    if (not isinstance(phrases, list) or not 1 <= len(phrases) <= MAX_TERMS
            or not all(isinstance(phrase, str) for phrase in phrases)):
        raise RuleError(f"rule {index}: after is 1 to {MAX_TERMS} words or phrases")
    cleaned = []
    for phrase in phrases:
        words = phrase_words(phrase)
        if not words or len(phrase) > MAX_TERM:
            raise RuleError(f"rule {index}: {phrase!r} is not a word or phrase of at most "
                            f"{MAX_TERM} characters")
        cleaned.append(" ".join(words))
    checked = {"field": field, "after": sorted(set(cleaned)), "within": within, "take": shape}
    if shape == "words":
        count = rule.get("max_words")
        if (not isinstance(count, int) or isinstance(count, bool)
                or not 1 <= count <= MAX_TAKE_WORDS):
            raise RuleError(f"rule {index}: max_words is 1 to {MAX_TAKE_WORDS}")
        checked["max_words"] = count
    return checked


def apply_rules(rules: list[dict], row: Mapping) -> "tuple[str | None, int | None]":
    """(value, 1-based rule number) for one row, or (None, None) when no
    rule holds. `rules` must have come through check_rules. An
    extraction rule's value is the text it found, as written; the field's
    type is applied after (extraction_rules.typed)."""
    cache: dict[str, list[str]] = {}
    for number, rule in enumerate(rules, start=1):
        if "after" in rule:
            found = take(rule, row.get(rule["field"]))
            if found is not None:
                return found, number
            continue
        holds = True
        for condition in rule["when"]:
            field = condition["field"]
            if field not in cache:
                cache[field] = _words(row.get(field))
            words = cache[field]
            if not any(_contains_phrase(words, term.split()) for term in condition["contains_any"]):
                holds = False
                break
        if holds:
            return rule["then"], number
    return None, None


def is_ensemble(recipe) -> bool:
    """Whether a recipe is several voting rule sets rather than one."""
    return isinstance(recipe, Mapping) and "members" in recipe


def check_recipe(recipe, enrichment: Enrichment):
    """A recipe as THIS module will run it -- one rule set, or several
    voting -- or RuleError. Rebuilt from what was checked, as
    check_rules does, so nothing unchecked reaches storage."""
    if not is_ensemble(recipe):
        return check_rules(recipe, enrichment)
    if set(recipe) - {"combine", "members"} or recipe.get("combine") != "weighted_vote":
        raise RuleError("a combined recipe is {combine: weighted_vote, members}")
    members = recipe.get("members")
    if not isinstance(members, list) or not 2 <= len(members) <= MAX_MEMBERS:
        raise RuleError(f"a combined recipe has 2 to {MAX_MEMBERS} members")
    checked = []
    for number, member in enumerate(members, start=1):
        if not isinstance(member, Mapping) or set(member) != {"weight", "rules"}:
            raise RuleError(f"member {number} is not {{weight, rules}}")
        weight = member["weight"]
        if (not isinstance(weight, (int, float)) or isinstance(weight, bool)
                or not 0 < weight <= MAX_WEIGHT):
            raise RuleError(f"member {number}'s weight is a number above 0 and at most "
                            f"{MAX_WEIGHT}")
        try:
            rules = check_rules(member["rules"], enrichment)
        except RuleError as e:
            # WHICH SET, so a refusal names the one to look at.
            raise RuleError(f"member {number}: {e}") from e
        checked.append({"weight": round(float(weight), 3), "rules": rules})
    return {"combine": "weighted_vote", "members": checked}


def apply_recipe(recipe, row: Mapping) -> "str | None":
    """One row's value from a checked recipe, or None. A combined recipe
    is a weighted vote of its members; nobody answering, or a tie for
    the heaviest value, is empty -- an honest blank, never a guess."""
    if not is_ensemble(recipe):
        return apply_rules(recipe, row)[0]
    # KEYED IGNORING CASE AND SPACING, so two sets that extracted "INV-7"
    # and "inv-7" agree; the first set's own text is the answer. For a
    # choice the key is the choice, which is already canonical.
    votes: dict[str, float] = {}
    first_seen: dict[str, str] = {}
    for member in recipe["members"]:
        value, _ = apply_rules(member["rules"], row)
        if value is not None:
            key = " ".join(value.casefold().split())
            votes[key] = votes.get(key, 0.0) + member["weight"]
            first_seen.setdefault(key, value)
    if not votes:
        return None
    heaviest = max(votes.values())
    winners = [key for key, weight in votes.items() if weight == heaviest]
    return first_seen[winners[0]] if len(winners) == 1 else None


def describe_recipe(recipe) -> list[dict]:
    """A recipe for the person approving it: one entry per rule set, its
    weight (None for a lone set) and its rules in plain words."""
    if not is_ensemble(recipe):
        return [{"weight": None, "rules": [describe_rule(rule) for rule in recipe]}]
    return [{"weight": member["weight"], "rules": [describe_rule(rule) for rule in member["rules"]]}
            for member in recipe["members"]]


def describe_rule(rule: Mapping) -> str:
    """One rule in plain words, for the person approving it."""
    if "after" in rule:
        return describe_extraction(rule)
    parts = [f"{condition['field']} mentions "
             + " or ".join(repr(term) for term in condition["contains_any"])
             for condition in rule["when"]]
    return f"If {' and '.join(parts)}: {rule['then']}"
