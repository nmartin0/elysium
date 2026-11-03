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
# R56: a field declared fuzzy, within its declared edits but not equal.
CLOSE = "close"


def _verdict(agreement: "bool | str | None", left_has_value: bool,
             right_has_value: bool, readable: bool = True) -> str:
    """What may be said about a pair without saying the values.

    THREE THINGS THAT MUST NOT LOOK ALIKE, which is this project's own
    rule stated in DEV_UI.md 9.7: "'Not permitted', 'restricted' and a
    real NULL must look like three different things." A field the
    reviewer MAY NOT READ, a field one record genuinely LACKS, and a
    field the matcher COULD NOT COMPARE are three different facts, and
    only one of them is evidence about whether these are the same
    person.

    READABILITY IS PASSED IN BECAUSE IT IS NOT DERIVABLE FROM THE
    ROWS, and assuming it was is what broke this. The caller fetches
    only readable fields, so an unreadable one is absent from both
    rows -- indistinguishable, from here, from a value that is really
    not there. Asked the wrong question, this returned ONE SIDE
    MISSING for every withheld field: a claim about the data, made
    about data the reviewer was not allowed to see, and the only
    verdict the old presence test could ever produce.

    WHAT AN UNREADABLE FIELD GETS IS THE MATCHER'S VERDICT, which is
    the module's whole premise -- "a reviewer can be told two emails
    AGREE without being shown either". Nothing new is disclosed: the
    verdict was always going to be shown, and now it is the right one.
    """
    # NOT A KEY CHECK, A VALUE CHECK. `get_object` returns a key for
    # every field it is ASKED for, so key presence only ever recorded
    # whether the route requested the field -- never whether a record
    # held it. The fact this verdict names is the value.
    if readable and not (left_has_value and right_has_value):
        return ONE_SIDE_MISSING
    if agreement is None:
        return UNCOMPARED
    if agreement == CLOSE:
        return CLOSE
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
        may_read = field_name in readable
        left_value = (left_row or {}).get(field_name)
        right_value = (right_row or {}).get(field_name)
        entry = {
            "field": field_name,
            "verdict": _verdict(agreed, left_value is not None,
                                right_value is not None, may_read),
            # WHETHER THE VALUE WAS WITHHELD, SAID RATHER THAN INFERRED
            # FROM ITS ABSENCE. `withheld_fields` used to read the
            # absence of `left`/`right` as "the reviewer could not see
            # this", which also catches a readable field that is simply
            # null on both sides -- telling a reviewer they judged
            # without seeing something they saw perfectly well, and
            # which was empty.
            #
            # A FLAG IS NOT A VALUE. It says that a value exists and is
            # not being shown, which the reviewer is entitled to know
            # and which the literature requires be recorded; it carries
            # nothing of the value itself.
            "readable": may_read,
        }
        if may_read:
            # ABSENT WHEN NULL, TOO, not just when withheld. The
            # response must never carry `"left": null` -- a None has
            # been serialised into this process and sits in anything
            # that cached it -- and the verdict above already says
            # which side was empty.
            if left_value is not None:
                entry["left"] = left_value
            if right_value is not None:
                entry["right"] = right_value
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

    KEYED ON PERMISSION, NOT ON ABSENCE. Reading the absence of
    `left`/`right` as "withheld" also catches a readable field that is
    null on both sides, which tells a reviewer they judged without
    seeing something they saw and which was empty -- and it silently
    stopped meaning anything at all while `_readable_fields` was
    returning nothing, when it named every field of every proposal.
    """
    return [entry["field"] for entry in entries if not entry.get("readable", True)]
