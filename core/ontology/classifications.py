"""Field classifications: what a property's VALUES are, declared once (R12).

    fields:
      email:
        type: data
        classification: pii
      salary:
        type: data
        classification: [pii, financial]

LABELS, NOT GRANTS. A classification says what a value IS -- personal,
financial -- and decides nothing about who may read it. Granting by
label is BLOCKING 6 ("grant by TAG rather than by field name"), which
changes what a grant means for every existing policy.yaml and so is a
decision before it is work. This is the half that is not: recording
the label where the data goes, so that when the decision is made there
is something to decide over, and so that anyone reading the lake today
-- a backup, an auditor, a future REST catalog (R17) -- can see which
columns hold what.

WHY IT MUST PROPAGATE, which is the whole of R12. Foundry: "If a
dataset has a file marking, every dataset that depends on it inherits
that marking", and "restricting access to a dataset always restricts
access to any data derived from it". A label on the ontology property
alone describes ONE of three copies of the value: the source column is
copied verbatim into bronze, standardised into silver, and conformed
into gold. core/mirror/classifications.py carries it to all three.

THE VOCABULARY IS OPEN, deliberately, for the same reason: which labels
exist is BLOCKING 6's question. What is checked is SHAPE -- lowercase,
identifier-like -- so "PII" and "pii " cannot quietly become three
labels for one thing.

REMOVING ONE IS AN ONTOLOGY EDIT, and recorded as one (config history).
Foundry calls removal "a sensitive action" requiring its own permission;
here it is whoever may change the ontology, which is the same set of
people who could have declared the field unclassified in the first
place.
"""

import re

_LABEL = re.compile(r"^[a-z][a-z0-9_]*$")


def field_classifications(field_info: dict) -> frozenset[str]:
    """The labels one field declares. Empty when it declares none."""
    declared = field_info.get("classification")
    if declared is None:
        return frozenset()
    if isinstance(declared, str):
        return frozenset({declared})
    return frozenset(declared)


def validate_field_classification(object_type_name: str, field_name: str,
                                  field_info: dict) -> None:
    """Refuses a classification that is not a label or list of labels."""
    declared = field_info.get("classification")
    if declared is None:
        return
    labels = [declared] if isinstance(declared, str) else declared
    if not isinstance(labels, list) or not labels:
        raise ValueError(
            f"Object type {object_type_name!r}: field {field_name!r} declares a "
            f"`classification` that is neither a label nor a non-empty list of "
            f"labels: {declared!r}."
        )
    for label in labels:
        if not isinstance(label, str) or not _LABEL.match(label):
            raise ValueError(
                f"Object type {object_type_name!r}: field {field_name!r} declares "
                f"classification {label!r}. A label is lowercase letters, digits "
                f"and underscores, starting with a letter -- 'pii', not 'PII' -- "
                f"so one label cannot be spelled three ways."
            )
