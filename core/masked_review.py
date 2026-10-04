"""What a merge reviewer is shown when they may not read the fields
that decide the match.

THE PROBLEM, kept whole because it is a security design rather than a
UI preference:

    A REVIEWER MAY NOT BE CLEARED TO SEE THE FIELDS THAT DECIDE THE
    MATCH. Elysium is MAC-governed; the person best placed to judge
    whether two customers are the same may not be permitted to read
    the email address that settles it.

THE ANSWER IS NOT OURS AND HAS A LITERATURE. Privacy-preserving record
linkage calls it MASKED CLERICAL REVIEW: systems "that conceal the
plaintext by default, present categorical value frequencies, and
gradually disclose selected information". What the reviewer is given
is "merely selected plaintext based on the information whether an
attribute pair is equal, dissimilar, or somewhat similar".

That is the shape of the decision anyway. `FUSION_AND_IDENTITY.md`
already says "the reviewer's decision is made on the agreement
PATTERN, not the score", and `Candidate` already carries
`agreement: dict[str, bool]` -- the verdict without the value. A
reviewer can be told two emails AGREE without being shown either.

THE REQUIREMENT THE LITERATURE STATES, and the one that decides how
this is written:

    The facility responsible for the (masked) clerical review should
    only have access to those plaintext attributes that are displayed.

So a masked comparison does not carry the hidden values and mark them
hidden. It NEVER HOLDS THEM. The difference is invisible in a
rendered screen and total in a log, a cache, an error report or a
future refactor -- it is the rule `core/notifications.py` already
states for its own rows: "filtering-after-assembly is where these
systems leak, because the unfiltered thing existed".

IT DECIDES NOTHING ABOUT ACCESS. `readable_fields` is passed in,
computed by a caller that has a mediator, exactly as
`core/change_hints.py` takes a visible schema. A second place
deciding one security question is how two rules drift apart.
"""

#: What a field comparison can say when the values are withheld.
AGREE = "agree"
DIFFER = "differ"
ONE_SIDE_MISSING = "one side missing"
UNCOMPARED = "not compared"


def _verdict(agreement: "bool | None", left_present: bool,
             right_present: bool) -> str:
    """What may be said about a pair without saying the values."""
    if not left_present or not right_present:
        return ONE_SIDE_MISSING
    if agreement is None:
        return UNCOMPARED
    return AGREE if agreement else DIFFER


def masked_comparison(agreement: dict, left_row: dict, right_row: dict,
                      readable_fields) -> list[dict]:
    """One entry per field: a verdict always, values only if readable.

    THE VERDICT IS ALWAYS SAFE and the value usually is not. "These
    two emails agree" tells a reviewer what they need and tells them
    nothing about either address; it is derivable from data they
    cannot read, but so is the proposal they are being asked to judge,
    and refusing them the verdict would mean refusing them the task.

    WHAT IS WITHHELD IS WITHHELD BY ABSENCE. An unreadable field's
    entry has no `left` or `right` key at all, rather than a key set
    to None or to a sentinel. A caller cannot accidentally render,
    log, or serialise what was never put in the structure.

    FIELDS ARE THOSE THAT WERE COMPARED, in the matcher's order. A
    field present in the rows and not in `agreement` was not part of
    the decision, and showing it would invite a reviewer to weigh
    something the score did not.
    """
    readable = set(readable_fields or ())
    entries = []
    for field_name, agreed in (agreement or {}).items():
        left_present = field_name in (left_row or {})
        right_present = field_name in (right_row or {})
        entry = {
            "field": field_name,
            "verdict": _verdict(agreed, left_present, right_present),
        }
        if field_name in readable:
            if left_present:
                entry["left"] = left_row[field_name]
            if right_present:
                entry["right"] = right_row[field_name]
        entries.append(entry)
    return entries


def agreement_pattern(entries: list) -> str:
    """The pattern a reviewer actually decides on, as one line.

    `FUSION_AND_IDENTITY.md`: "the reviewer's decision is made on the
    agreement PATTERN, not the score", and "a number alone cannot be
    argued with". This is the pattern in a form that fits in a
    sentence, for an audit entry or a summary -- names and verdicts,
    never values.
    """
    return ", ".join(f"{entry['field']}: {entry['verdict']}"
                     for entry in entries)


def withheld_fields(entries: list) -> list[str]:
    """Which fields the reviewer judged without seeing.

    RECORDED, BECAUSE IT CHANGES WHAT THE DECISION MEANS. An approval
    made while three of five deciding fields were masked is a weaker
    artifact than one made with all five visible, and whoever reads
    the decision later should be able to tell which they are holding.
    """
    return [entry["field"] for entry in entries
            if "left" not in entry and "right" not in entry]
