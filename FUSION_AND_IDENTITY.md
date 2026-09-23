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

---

# GOLD-6: which library, decided by installing them (September 23)

The owner asked for thorough research into probabilistic identity
resolution, including what the canonical Python libraries actually
provide. So they were installed and run, not just read about.

## The field, and why Splink is the one to consider

SPLINK (Ministry of Justice, MIT): Fellegi-Sunter, the model this
design already committed to. A 2026 comparison of four libraries on
three datasets found it "the fastest at 6.9s and the most
memory-efficient at 10.0 MB -- its DuckDB backend handles blocking and
comparison in SQL". It is also the one whose vocabulary matches ours:
m and u probabilities, match weights, blocking rules.

DEDUPE: active learning -- "you label pairs interactively, it trains a
classifier". Powerful, and the interactive labelling "makes automation
harder", which for an unattended nightly pipeline is disqualifying.

RECORDLINKAGE: a clean scikit-learn-style API, and the same comparison
notes "the project hasn't been updated since July 2023". It also won
on the hardest dataset (0.923 F1 against Splink's 0.728), which is
worth remembering: FELLEGI-SUNTER IS NOT UNIVERSALLY BEST. It suits
PII-shaped data, which is what an ontology's entities usually are.

ZINGG: Spark. Wrong shape for an on-prem single-node deployment.

## What Splink actually gives us, read from the installed package

  linker.training.estimate_u_using_random_sampling
  linker.training.estimate_parameters_using_expectation_maximisation
  linker.training.estimate_m_from_pairwise_labels
  linker.inference.predict
  linker.inference.compare_two_records
  linker.inference.find_matches_to_new_records
  linker.inference.deterministic_link
  linker.clustering.cluster_pairwise_predictions_at_threshold
  linker.visualisations.waterfall_chart / match_weights_chart

THREE OF THOSE MATTER MORE THAN THE REST, for what this design says it
needs:

  compare_two_records SCORES ONE PAIR ON DEMAND. That is the review
  screen: a reviewer opens a proposed merge and the score is computed
  for that pair, without a batch job.

  predict RETURNS gamma_<field> PER PAIR -- which comparison level
  each field landed in -- alongside match_weight and match_probability.
  So the "what drove the score" explanation the review needs is DATA,
  not their Altair chart. Verified by running it.

  find_matches_to_new_records matches new records against an existing
  set, which is what a nightly pipeline does after the first build.

## What it costs, measured

186 MB across seven transitive dependencies -- duckdb 61, numpy 57,
pandas 39, igraph 16, altair 6, sqlglot 3, jinja2 0.5. Elysium today
declares TEN dependencies in total and none of those seven.

For an on-prem product that sometimes installs air-gapped, that is not
a detail. It is also, for most deployments, WEIGHT FOR A FEATURE THEY
WILL NEVER TURN ON: this design already says inference is off by
default and only ever ADDS PROPOSALS.

## A REPRODUCED BUG, and it changes the recommended path

estimate_u_using_random_sampling raises

    ValueError: Salting partitions must be specified and > 1

MEASURED ACROSS SIX COMBINATIONS: splink 4.0.8 and 4.0.17, duckdb
1.1.3 and 1.5.5, pandas 2.3.3 and 3.0.2. It fails in all of them, so
it is Splink's, not a version-matching problem we could pin our way
out of. (duckdb 1.1.3 with pandas 3 fails earlier still, on the new
string dtype.)

AND THE PATH THAT AVOIDS IT IS THE ONE WE SHOULD WANT ANYWAY.
Declaring m and u probabilities outright -- no EM, no random sampling
-- works: verified end to end, 1,400 pairs predicted, and a single
pair scored on demand at match_weight 0.212 / probability 0.537 with
its per-field levels returned.

Declared weights are also the auditable choice. A governed system
should be able to tell a reviewer WHY two records scored as they did
in terms somebody chose, rather than in terms an unsupervised
algorithm inferred from data nobody inspected. Unsupervised training
remains available later as a way to PROPOSE weights for a person to
accept -- the same rule as everywhere else here.

## The decision

  1. A MATCHER INTERFACE in core, with two implementations behind it.
  2. THE DETERMINISTIC MATCHER IS BUILT IN and has no dependencies:
     declared keys, normalised, compared exactly. It is what
     FUSION_AND_IDENTITY calls the primary path, and it must keep
     working with nothing installed.
  3. SPLINK IS AN OPTIONAL EXTRA (`pip install elysium[identity]`),
     loaded only when a deployment declares probabilistic matching.
     A deployment that never turns inference on never pays the 186 MB.
  4. WEIGHTS ARE DECLARED, not estimated, for the reasons above --
     which also routes around the bug rather than waiting on it.
  5. TWO THRESHOLDS, as the MDM precedent says: above the auto-link
     threshold a merge is proposed automatically; between the two it
     goes to review; below, nothing. Both are declared, per type.
  6. EVERY MERGE IS STILL A PROPOSAL through the write queue, and a
     MAC conflict still refuses it (decision D2). The library scores;
     it never decides.

## What is checked before any of it is built

The bug above should be re-tested on each Splink release, and the
version pinned to one where either the declared-weights path or the
whole training path is known to work. The test belongs in the suite,
skipped when the extra is not installed, so a deployment that DOES
enable identity resolution finds out at CI time rather than at 2am.

