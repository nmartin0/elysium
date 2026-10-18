"""Fields filled in by a model that learned from the other records (R48).

    object_types:
      Customer:
        fields:
          churn_risk:
            predict:
              of: churned            # the field whose answer is learned
              from: [plan, tenure_months, region]
              chance_of: "yes"       # optional: the chance it is this value

Enrichment (enriched_fields.py) reads what a record SAYS. A prediction
fills in what the record does not say -- what is LIKELY to be true of
it -- by learning from the records whose answer is known. Three shapes,
decided by the declaration:

  CHANCE   `chance_of` names a value of a text or yes/no field: the field
           holds the chance, 0 to 1, that the answer is that value
  CLASS    a text or yes/no field without `chance_of`: the most likely
           answer
  NUMBER   a numeric field: the likely number

FILLED ONLY WHERE THE ANSWER IS NOT KNOWN. A record whose `of` field has
a value shows that value, and its prediction is empty: a guess beside
the real answer adds nothing but the chance of being mistaken for it.
The real field is never written (R52: nothing is imputed into served
data).

NEVER A CLASSIFIED FIELD, as an input or as the answer: whether a model
may learn from or about classified values -- special categories above
all -- is D3 and D5/R47, still open. Refused at load.

NOT THE ANSWER IN DISGUISE. An input that is the answer, or is computed
from it, would score perfectly and predict nothing; refused at load. One
that merely carries it -- a cancellation date beside "cancelled" -- the
loader cannot know, so the evaluation warns when a score is too good to
be true (core/predictions.py).

WHO MAY READ ONE: someone who may read the answer field and every
input, by the derived-field rule (derived_fields.gate_derived_grants). A
prediction is a summary of both.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from core.ontology.classifications import field_classifications

PREDICT_KEYS = frozenset({"of", "from", "chance_of"})
#: Keys a predicted field may carry beside `predict`, as an enriched one.
ALLOWED_BESIDE = frozenset({"predict", "display_name", "description", "classification",
                            "classifications", "type", "data_type"})
#: The answer field's types, by the shape they give.
CATEGORICAL_TARGETS = frozenset({"string", "boolean"})
NUMERIC_TARGETS = frozenset({"integer", "number", "decimal"})
#: What an input may be: anything with a value a tree can split on.
INPUT_TYPES = frozenset({"string", "boolean", "integer", "number", "decimal", "date",
                         "timestamp", "timestamptz"})
MAX_INPUTS = 20


@dataclass(frozen=True)
class Prediction:
    target: str
    inputs: tuple[str, ...]
    chance_of: "str | None"
    #: "chance", "class" or "number"
    kind: str

    def describe(self) -> str:
        return f"predicted from {', '.join(self.inputs)}"

    @property
    def data_type(self) -> str:
        """What the predicted field holds."""
        return "string" if self.kind == "class" else "number"


def prediction_of(field: Mapping, fields: Mapping) -> "Prediction | None":
    """The parsed declaration, or None for a field that is not predicted.
    Unvalidated: load calls validate_predicted_fields first. `fields` is
    the type's fields, which decide the shape from the answer's type."""
    declared = field.get("predict")
    if declared is None:
        return None
    target = declared.get("of")
    inputs = declared.get("from")
    if isinstance(inputs, str):
        inputs = [inputs]
    chance_of = declared.get("chance_of")
    target_type = ((fields.get(target) or {}).get("data_type") or "string") if isinstance(
        target, str) else "string"
    if target_type in NUMERIC_TARGETS:
        kind = "number"
    else:
        kind = "chance" if chance_of is not None else "class"
    return Prediction(str(target), tuple(inputs or ()),
                      None if chance_of is None else str(chance_of), kind)


def predicted_fields(type_def: Mapping) -> dict[str, Prediction]:
    """{field name: Prediction} for every predicted field of a type."""
    fields = type_def.get("fields") or {}
    return {name: prediction
            for name, field in fields.items()
            if (prediction := prediction_of(field, fields)) is not None}


def declaration_hash(object_type: str, field_name: str, prediction: Prediction) -> str:
    """What an approval is an approval OF: the question, its inputs and
    its shape. Any change to them is a different question."""
    canonical = json.dumps({"type": object_type, "field": field_name, "of": prediction.target,
                            "from": list(prediction.inputs), "chance_of": prediction.chance_of,
                            "kind": prediction.kind}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _computed(field: Mapping) -> bool:
    return any(key in field for key in ("derived", "enrich", "predict"))


def validate_predicted_fields(object_types: Mapping) -> None:
    """Refuses, at load, a prediction that could not be learned -- or one
    that would learn from or about a classified value."""
    for type_name, type_def in object_types.items():
        fields = type_def.get("fields") or {}
        for field_name, field in fields.items():
            if "predict" not in field:
                continue
            where = f"{type_name}.{field_name}"
            declared = field["predict"]
            if not hasattr(declared, "items"):
                raise ValueError(f"{where}: `predict` is {{of, from, chance_of?}}.")
            extra = sorted(set(declared) - PREDICT_KEYS)
            if extra:
                raise ValueError(f"{where}: unknown key(s) {extra} in `predict`.")
            if "derived" in field or "enrich" in field:
                raise ValueError(f"{where} is predicted, so it cannot also be derived or "
                                 f"enriched.")
            beside = sorted(set(field) - ALLOWED_BESIDE)
            if beside:
                raise ValueError(f"{where} is filled in by a model, so it has no stored "
                                 f"value; remove {beside}.")
            if field.get("type", "data") != "data":
                raise ValueError(f"{where}: a predicted field is a value, not a "
                                 f"{field['type']}.")
            target = declared.get("of")
            if not isinstance(target, str) or target not in fields:
                raise ValueError(f"{where}: `predict.of` names the field whose answer is "
                                 f"learned; {target!r} is not a field of {type_name}.")
            if target == field_name:
                raise ValueError(f"{where} cannot predict itself.")
            answer = fields[target]
            if answer.get("type", "data") != "data" or _computed(answer):
                raise ValueError(f"{where}: {target!r} is computed or a link; a model learns "
                                 f"an answer the source records.")
            target_type = answer.get("data_type") or "string"
            if target_type not in CATEGORICAL_TARGETS | NUMERIC_TARGETS:
                raise ValueError(f"{where}: {target!r} is {target_type}; a model here learns "
                                 f"text, yes/no or a number.")
            if field_classifications(answer):
                raise ValueError(f"{where}: {target!r} is classified "
                                 f"{sorted(field_classifications(answer))}, and a model never "
                                 f"learns about a classified value (D3, D5).")
            chance_of = declared.get("chance_of")
            if chance_of is not None and target_type in NUMERIC_TARGETS:
                raise ValueError(f"{where}: `chance_of` is for a text or yes/no answer; "
                                 f"{target!r} is a number, and is predicted as one.")
            if chance_of is not None and (not isinstance(chance_of, (str, bool))
                                          or not str(chance_of).strip()):
                raise ValueError(f"{where}: `chance_of` is one value of {target!r}.")
            prediction = prediction_of(field, fields)
            assert prediction is not None
            if field.get("data_type", prediction.data_type) != prediction.data_type:
                holds = "the most likely answer" if prediction.kind == "class" else "a number"
                raise ValueError(f"{where} holds {holds}, so it is {prediction.data_type}; "
                                 f"remove data_type {field['data_type']!r}.")
            _check_inputs(where, type_def, field_name, prediction, fields)


def _check_inputs(where: str, type_def: Mapping, field_name: str, prediction: Prediction,
                  fields: Mapping) -> None:
    inputs = prediction.inputs
    if not 1 <= len(inputs) <= MAX_INPUTS:
        raise ValueError(f"{where}: `predict.from` names 1 to {MAX_INPUTS} fields to learn "
                         f"from.")
    if len(set(inputs)) != len(inputs):
        raise ValueError(f"{where}: `predict.from` names a field twice.")
    for name in inputs:
        if not isinstance(name, str) or name not in fields:
            raise ValueError(f"{where}: `predict.from` names {name!r}, which this type does "
                             f"not have.")
        if name in (field_name, prediction.target):
            raise ValueError(f"{where}: {name!r} is the answer itself, so it cannot be "
                             f"learned from.")
        if name == type_def.get("id_field"):
            raise ValueError(f"{where}: {name!r} is the id -- different for every record, "
                             f"so there is nothing to learn from it.")
        source = fields[name]
        if source.get("type", "data") != "data":
            raise ValueError(f"{where}: {name!r} is a {source['type']}; learn from its "
                             f"values' fields instead.")
        if _computed(source):
            derived_from = (source.get("derived") or {})
            if prediction.target in json.dumps(derived_from):
                raise ValueError(f"{where}: {name!r} is computed from the answer "
                                 f"{prediction.target!r}, so it would give it away.")
            raise ValueError(f"{where}: {name!r} is computed; learn from the fields it comes "
                             f"from instead.")
        if (source.get("data_type") or "string") not in INPUT_TYPES:
            raise ValueError(f"{where}: {name!r} is {source['data_type']}, which a model "
                             f"here cannot learn from.")
        labels = field_classifications(source)
        if labels:
            raise ValueError(f"{where}: {name!r} is classified {sorted(labels)}, and a model "
                             f"never learns from a classified value (D3, D5).")


def fill_predicted_types(object_types: Mapping) -> None:
    """`type: data` and each predicted field's data_type written into the
    raw schema, as fill_enriched_types does, so every reader sees one
    declared type."""
    for type_def in object_types.values():
        fields = type_def.get("fields") or {}
        for field in fields.values():
            if "predict" in field:
                prediction = prediction_of(field, fields)
                assert prediction is not None
                field.setdefault("type", "data")
                field.setdefault("data_type", prediction.data_type)
