# Fusion and identity — a design

**The gap**, correctly identified: Elysium has the plumbing for
reaching data in different physical stores in one query --
`search_around()`, `resolve_reverse_links_batch()`, MDO -- and no
identity resolution. It follows relationships someone wrote down. It
does not infer them, and nothing merges two sources into one subject.

Nothing in this file is built.

---

## The precedent says this is a PIPELINE problem

Palantir's own anti-patterns document names exactly this case --
"System Silos occur when you create separate object types for the same
real-world entity based on the source system" -- and prescribes:

> Identify the primary key that uniquely identifies the entity across
> systems. **Build a transform that joins data from all source
> systems.** Define clear precedence rules for conflicting values.
> Create a single object type backed by the merged dataset.

An independent analysis is blunter: if the same entity arrives under
two keys, "you have an identity resolution problem that belongs in the
pipeline, **before the object type is worth defining at all**".

**SO THE ONTOLOGY IS RIGHT TO ONLY FOLLOW DECLARED LINKS.** Fusion
belongs upstream of it, and this design does not change the ontology's
behaviour at all.

## Which places it exactly: the gold layer Elysium does not have

Bronze is raw, silver is typed and validated. The medallion pattern's
third layer is gold -- "business-level tables tailored to specific use
cases".

**ENTITY RESOLUTION IS WHAT GOLD IS FOR.** Silver holds `Customer` as
the CRM sees it and `Customer` as billing sees it; gold holds the
resolved subject; the ontology points at gold.

That is the architectural slot, and it is worth having regardless --
aggregates and derived tables belong there too.

---

## THE PERMISSIONS PROBLEM, and why it is not a write-down

The obvious fear: merging a `us-east` record with a `us-west` one
means choosing a security value for the result. More permissive leaks;
more restrictive hides the merge from everyone who could use it. That
is SECURITY_ARCHITECTURE.md's \\*-property hole arriving through a
different door.

**IT DISSOLVES, AND THE MECHANISM IS ALREADY BUILT.** Elysium has
column-wise MDO, and `_resolve_shared_storage` records that this
mirrors "Palantir's own MDO scope choice". Foundry's stated reason for
column-wise MDO is exactly this: distinct subsets of properties
integrated from different datasources, "to support use cases where
there is a need for column-level access controls".

So:

**ONE OBJECT. FIELDS KEEP THE CLASSIFICATION OF THE SOURCE THEY CAME
FROM. MAC FILTERS PER FIELD, AS IT ALREADY DOES.**

Nothing is copied into a more permissive container, so there is no
write-down. A `us-west` user sees the subject with the `us-west`
fields populated and the rest absent -- which is what MAC already does
for a single-source object.

**WHAT DOES NOT DISSOLVE:** the identity itself has a classification.
Knowing that a `us-east` record and a `us-west` record are the same
person is a FACT, and it may be more sensitive than either record.
The LINK needs its own security treatment, and MDO does not answer
that.

---

## Three warnings from people who built this

**UNRESOLUTION IS A HARD REQUIREMENT.** Palantir rebuilt their entity
resolution in the mid-2010s and "a critical requirement was solving
not only the problem of resolution but also of unresolution. Often,
users would combine two entities, only for another user to come along
and disagree."

**NAIVE MERGING LOSES PROVENANCE.** Their own description: resolution
yields "a single winner with all properties... property provenance is
lost". For a system whose pitch is knowing where a value came from,
that would be a serious regression. MDO already tracks which storage a
field came from, so the information exists -- it must not be discarded
on the way into gold.

**AND THE FAILURE LIST IS SPECIFIC:** poorly-designed entity
resolution is "inscrutable to end users, produces incorrect
aggregations and false negative search results, and damages
performance".

---

# The design

## Hand-written joins are the PRIMARY path, not a fallback

A deployment states the rule: these two silos' customers share an
email, join on it. Deterministic, auditable, no inference, no
confidence score.

**THE GOLD LAYER MUST WORK WITH ZERO INFERENCE.** Inference only ever
ADDS PROPOSALS to a mechanism that already works without it. That is
what makes the riskier half safe to offer at all.

## Inference is OFF by default, and its proposals always need approval

**TWO INDEPENDENT SWITCHES**, because they answer different questions:

- *Is inference enabled?* Deployment config, defaults to FALSE.
- *Does a proposed merge need approval?* ALWAYS. Never configurable,
  because a setting is a thing someone turns off.

The default matches `auto_execute`, which already defaults to
confirmation and is "enforced in Python at the point of execution
rather than by asking the model to behave -- a prompt can be talked
around, a branch cannot". Consistency here is worth something.

## A proposed merge is a WRITE, through the queue that exists

Criteria, four-eyes, TTL, audit -- the whole apparatus, unchanged.

**AND THIS ANSWERS UNRESOLUTION NATIVELY.** If a merge is an approved
write, UN-merging is another write, with the same trail. Palantir
treated unresolution as critical because users disagree; Elysium's
approvals model handles disagreement already.

## When a declared rule and an inference disagree, THE RULE WINS

And the disagreement is RECORDED rather than dropped. A silently
ignored inference is a finding nobody sees; a recorded one tells you
your rule might be wrong.

## An approved inference becomes STORED DATA, not edited config

**THIS MATTERS MORE THAN IT SOUNDS.** If approving a merge rewrote
`ontology_schema.yaml`, then configuration -- the thing a human wrote
and reviews -- would silently grow entries nobody typed.

Decisions belong in a store, the way `sync_attempts` and pending
writes already are.

**CONFIG IS WHAT SOMEONE WROTE; DECISIONS ARE WHAT THE SYSTEM WAS
TOLD.** Keeping those separate is why a config diff means anything.

---

# Build order

1. **The gold layer.** The architectural slot. Useful alone.
2. **Declared resolution.** A join someone wrote down -- much closer to
   what Elysium already does well than to what it does not.
3. **Merged subjects as MDO**, with per-field classification and
   provenance preserved.
4. **Inferred resolution**, off by default, proposing writes into the
   approvals queue.

**Three of the four pieces already exist in some form** -- MDO, the
approvals queue, the medallion pipeline -- which is why this is
smaller than it first appeared.

# What none of this fixes

**MATCHING QUALITY.** Nothing here makes inference more accurate. It
makes a wrong merge reviewable and reversible, which is a different
and lesser claim.

**THE CLASSIFICATION OF THE LINK ITSELF**, noted above and unanswered.

---

# Presenting a probable match to a person (researched September 22)

The design above says an inferred merge is a proposal that needs
approval. It does not say what the approver SEES, and that is most of
whether this works.

## Two thresholds, not one

THE MDM PRECEDENT splits the score range in three with an AUTO-LINK
threshold and a CLERICAL-REVIEW threshold: above the first, merge
without asking; between the two, send for review; below, leave apart.
The thresholds are derived from stated error tolerances -- the
auto-link threshold from an allowable false-positive rate, the review
threshold from a desired false-negative rate -- rather than picked.

THAT MAPS ONTO ELYSIUM DIRECTLY, with one change: the owner's decision
(D2) already says a MAC conflict refuses the merge and sends it for
review regardless of score. So the review queue has two sources -- the
uncertain band, and the certain-but-conflicting.

## Review is expensive, and the cost is the design constraint

Published linkage work treats clerical review as a BUDGET: a study
using Splink on ~478,000 candidate pairs compares a baseline design
reviewing ~23% of pairs against a "budget" design reviewing ~7%, by
stratifying on match weight, agreement pattern and record ambiguity.
The lesson for us is that "send the uncertain ones for review" is not
a plan until somebody says how many a person can do in a day.

Another finding worth heeding: the DIVERSITY of the pairs shown
affects linkage quality, not just their number. A queue sorted purely
by score gives a reviewer twenty near-identical decisions in a row,
which is how attention fails.

## What the reviewer actually needs on screen

From the research, and from what Elysium can already produce:

  - THE TWO RECORDS SIDE BY SIDE, field by field, with agreements and
    disagreements marked -- the reviewer's decision is made on the
    agreement PATTERN, not the score.
  - THE SCORE, and what drove it: which fields contributed, and how
    much. A number alone cannot be argued with.
  - PROVENANCE PER FIELD, which silver's lineage now carries: which
    source said what, and when. Two records disagreeing about a
    surname is a different question when one source is six months
    stale.
  - THE CONSEQUENCE: what merging would do to the object, its links
    and its security classification -- stated before the click, since
    a merge is a write.

## The problem that is ours specifically

A REVIEWER MAY NOT BE CLEARED TO SEE THE FIELDS THAT DECIDE THE MATCH.
Elysium is MAC-governed; the person best placed to judge whether two
customers are the same may not be permitted to read the email address
that settles it.

THERE IS PRECEDENT, from privacy-preserving record linkage: masked
clerical review, where the display "conceal[s] the plaintext by
default, present[s] categorical value frequencies, and gradually
disclose[s] selected information". A reviewer can be told that two
values AGREE, or that a value is rare, without being shown it.

That is a genuinely good fit for a MAC system and worth building
rather than working around: the comparison a reviewer needs is usually
"do these agree", and agreement can be shown without disclosure. Where
disclosure is genuinely required, the queue should route the pair to
somebody cleared for it rather than degrading quietly.

## What this means for the build order

GOLD-6's review queue is not a list with two buttons. It is a
side-by-side comparison, a score explanation, per-field provenance, a
disclosure policy, and a routing rule. Worth knowing before GOLD-5
starts, because the matcher's output has to carry all of it.

