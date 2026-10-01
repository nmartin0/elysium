# Blocking

**The one planning file.** Everything here is work that CANNOT be done
without a person: a decision, a judgement about the product, a machine
nobody has, or an answer only the owner holds.

Anything that could be done has been done, and the document it came
from has been deleted. That is the rule this file exists to enforce:
if an item can be built, it does not belong here -- it belongs in the
code.

## How a document leaves

1. Every item in it is checked **against the code**, not taken at its
   word. The roadmap that preceded this file found SEVEN built things
   described as open, four of them still wrong when somebody later
   built against them.
2. What can be done is done, with tests and a control.
3. What cannot is moved here, with what it is blocked on and what
   would unblock it.
4. **Anything else in the file that is worth keeping moves into the
   code it describes**, as a comment beside the thing it explains. A
   measured fact in a deleted file is a measured fact lost.
5. The file is deleted, and every reference to it is rehomed.

Step 4 is the one that costs. `SCALABILITY.md` was cited six times
from `core/`, `adapters/` and `tests/`; those citations now carry the
numbers themselves.

## Consumed so far

| document | outcome |
| --- | --- |
| `SCALABILITY.md` | both decisions already built; benchmark numbers moved into the code that cited them |
| `QUERY_PLAN.md` | four unbuilt UI features, all product direction; its deferred MAC argument kept below |
| `LAKE_METADATA_NOTE.md` | three of its four answers were built; the fourth -- a reader -- is built here. Its one deferral kept below |
| `AUDIT_INTAKE.md` | superseded by `AUDIT_CHECKLIST.csv` by its own words; all 67 findings verified present there first; its alias table folded into the ten rows it concerns |
| `AUDIT_INTAKE_PIPELINE.md` | same; 50 ids checked, every one tracked |

---

# Blocked on a decision

## 1. `F-02` with `F-03` -- no valid policy can authorise a cross-type action

**The sharpest one, and it outranks the rest.** Reproduced: the policy
validator rejects every `write:` grant, while the write path demands
one per field. So no valid policy can authorise a cross-type action at
all.

Two ways out, and they are not equivalent:

- **Restore `write:` as a grant.** Keeps the authorisation model as
  written and makes the validator agree with the write path.
- **Drop the per-field demand and rely on `execute:` alone.** Simpler,
  and it CHANGES THE AUTHORISATION MODEL -- what a grant means, and
  what an audit entry records about why a write was allowed.

`F-12c` goes with it: the rejection message claims `write:` is "not
enforced anywhere", which is false either way. `F-03`'s `KeyError` on
a delete is part of the same change.

**Blocked on:** which of the two. The second is a product decision
about the permission model, not a bug fix.

## 2. Batch C -- quarantine the ROW, or refuse the TABLE?

Seven `ZOO` findings collapse into this single question: `ZOO-11`,
`ZOO-12`, `ZOO-15`, `ZOO-17`, `ZOO-18`, `ZOO-21`, `ZOO-22`. Today an
`N/A` in an integer column refuses the whole table.

The quarantine machinery already exists -- `core/mirror/duplicates.py`,
the expectations policy with `warn`, `quarantine` and `fail` -- so the
mechanism is not the blocker. The POLICY is: silently dropping a row
loses data the operator may not notice, and refusing a table stops a
pipeline for one bad cell.

**Also closes:** `R22` and `R27`.

**Blocked on:** the owner's choice of default, and whether it is
per-field declarable.

## 3. `LLM3-3` -- where does the security attribute live?

Raised by the security agent before it was destroyed, and the class
behind the worst finding of the audit. Two shapes:

- **A side table** keyed by object, holding the security value.
- **A column plus a check** that the pipeline never rewrites it.

The agent leaned toward the side table without recommending it. My own
argument, recorded at the time: the column-plus-check option has the
same "must be remembered" property one level down -- every future
pipeline stage must read the carried value rather than the column --
which is an argument FOR the side table that was not in their
write-up.

**Also closes:** `R50` and `R52`, both of which sit downstream of
where the value lives.

**Blocked on:** a design decision with migration consequences.

## 4. `E-02` residual -- which value identifies a caller behind a proxy?

One keyword argument: `login_attempt_tracker.record_failure(username,
source=<WHICH VALUE>)`. The attack is closed; the residual is that
unauthenticated requests are counted per-source and there is no
correct source.

`request.client.host` is the PROXY when one is in front, so every
caller shares one budget and the first enumeration exhausts it for
everybody. `INSTALL.md` says TLS terminates at a proxy. The honest
answer is the right-most TRUSTED entry of `X-Forwarded-For` -- never
the left-most, which a caller controls -- and that needs trusted-proxy
configuration which does not exist.

**Blocked on:** whether to add trusted-proxy configuration, and what
its default should be.

## 5. `NEW-4` -- should an absent gold table raise rather than answer `None`?

`get_raw_field` returns `None` both for "no such table" and "no such
row", while `find_ids` raises. A caller cannot tell a missing
deployment from a missing record.

**Blocked on:** whether changing it breaks callers that rely on the
lenient shape.

## 6. `NEW-5` -- undeclared source columns sit in the lake in the clear

Bronze holds every column the source has, declared or not -- which is
deliberate and documented. The consequence is that an undeclared SSN
is in Parquet with no field grant and no read path, and nothing says
so.

Three options: opt out per silo, encrypt at rest, or document it as
intended.

**Blocked on:** which, and it is a security posture decision.

## 7. `NEW-6` -- should invisible-character detection default on?

`no_invisible_characters` and `no_misleading_text` are opt-in per
field. A deployment that does not know to ask gets no protection.

**Blocked on:** whether a default-on rule that can quarantine rows is
acceptable, given it would change what an existing deployment accepts.

## 8. `NEW-7` -- build a reader for the gold history, or drop it

Nothing reads `gold_history`. A total failure of it looked like a
one-line warning for an unknown length of time partly because no
consumer would have noticed either.

**Blocked on:** whether the feature is wanted. A record nobody reads
is a cost with no benefit.

## 9. `A6` -- one generation serving two ages

A pinned type sees an old snapshot while an unpinned type sees the
current one, within one generation. Three options were recorded:
leave it, build an authoritative pin map including link tables, or pin
per request.

**Blocked on:** the choice. The first option is defensible and should
be taken explicitly rather than by default.

## 10. `WIRED-1` -- wire `reauthorize_conditions`, or decide not to

`/api/saved-views` returns `view.conditions` verbatim. The method
written to say what a caller has since lost access to is called by
nothing. Its own docstring: "a saved artifact is a request, never an
authority."

**Blocked on:** it changes an API response shape, which the UI
consumes.

## 11. `DEP-1` to `DEP-6` -- five dependency adoptions

Each is a yes or no about a named library. Cheap to answer, and not
mine to answer.

---

# Blocked on a machine or a person running something

## 12. `--workers` for real

Patches 292-295 fixed all four blockers. It has only ever run as two
apps inside one test process.

**Blocked on:** somebody running it.

## 13. The agents' reported-done work

Twenty-five rows across `LB`, `AR`, `E2` and `AL` are marked REPORTED
DONE on the departed agents' own evidence. They are not verifiable
from outside their branches, and those agents no longer exist.

**Blocked on:** somebody exercising that code, or accepting the
reports as they stand.

## 14. `pgserver` on Python 3.13

There is no wheel. The only real-PostgreSQL tests cannot run on the
machine that gates every patch, and the SQLAlchemy adapter is the
production read path.

**Blocked on:** a 3.12 environment for those tests, or a different
PostgreSQL fixture.

## 15. Nothing runs the 70 declared controls

`scripts/check_controls.py` works and is deliberately not in
`lint.sh`, because each control runs a slice of the suite. Nothing
invokes it.

**Blocked on:** choosing what does -- a CI job, a release step, or the
branch-merge script.

---

# Blocked because it is product direction

## 16. Thirty-odd recommendations that are not engineering questions

`R41`, `R42`, `R45`, `R48`, `R51`, `R53`, `R56` to `R62` and their
neighbours are LLM enrichment, embeddings, model predictions,
statistical matching and truth discovery. These are not "should we do
this well" questions; they are "is Elysium this product" questions,
and they should not be picked off a list by whoever is next.

## 17. What the Query screen should contain

Four features, none built, from `QUERY_PLAN.md`. They are product
direction rather than engineering: what a question box should offer
somebody who has never used it.

1. **Example questions from the deployment.** A deployment states what
   its data is good for; nobody else can. NOT by reusing
   `example_queries.yaml` as it stands -- its entries are user-paired
   for the runner. Either a separate `ui_examples:` key or a
   `for_display: true` marker on entries that qualify; the second is
   smaller and keeps one list.
2. **The question, read back** -- what the system understood.
3. **Follow-on questions** after an answer.
4. **History** of what this person has asked.

Its own order: 1 and the cheap half of 3 need nothing and would help
immediately.

**Explicitly not to be built**, and the reasoning is worth keeping:
clarifying questions before answering (an extra model call on a system
where the model is already the slow part, for a problem nobody has
reported) and a conversation thread (Elysium answers questions about
an ontology; it is not a chat assistant, and threading makes "which
generation answered this" much harder to state).

**Blocked on:** product design, and there is no front-end agent now.

## 18. A starter question can leak what MAC hides

From `QUERY_PLAN.md`, kept because it is a security argument rather
than a preference, and because feature 1 above cannot ship without
answering it.

The examples name specific ids:

    - user_id: user_alice
      query: "What are cust_001's recent transactions?"

Alice can see `cust_001`; Bob cannot. Showing Bob that example tells
him a customer called `cust_001` EXISTS. He cannot read it -- MAC
still refuses -- but he has learned it exists from a system built
specifically to refuse that. `get_field` on a hidden object returns
`None`, indistinguishable from "no such object", ON PURPOSE.

**And the `user_id` key does not solve it.** That is the deployment
author's assertion about who should see what, not something
`check_access` enforces. An author adding an example under the wrong
user, or a user's grants changing later, produces a quiet leak that
nothing detects.

**Blocked on:** whether display examples must be written to name no
real object at all, which is a constraint on deployment authors rather
than a feature.

## 19. Bootstrapping a deployment FROM the lake manifest

`LAKE_METADATA_NOTE.md` answered four questions about what the lake
should hold. Three were already built -- WHERE
(`_elysium/manifest-<generation>.json`, one per configuration
generation), WHEN (on configuration change, not every sync) and
SECRETS (never published; the manifest carries only the `adapter` key
per silo). The fourth, a reader that REPORTS, is built now.

**Its own deferral, kept because the reasoning is the point:**

> The stronger version -- bootstrapping a new deployment FROM the
> manifest -- is tempting and should wait. A copy that can become a
> source of truth is a copy that can disagree with one, and the whole
> reason this is a copy is to avoid that.

**Blocked on:** whether Elysium should ever configure itself from a
lake. It is a question about what the lake IS, not about code.

## 20. Saved SELECTIONS

A set of chosen OBJECTS rather than a saved question, and what bulk
actions would operate on. `BACKLOG.md` is explicit that the UI must
not conflate it with saved explorations.

**Blocked on:** product design.

---

# Not blocked, and not here

Six infrastructure recommendations are open and buildable: `R4` (one
consistent read per silo per run), `R5` (bounded-memory batched sync),
`R10` (SCD2 changelog), `R19` (a source-mutation matrix in CI), `R20`
(Iceberg branches for previews). They are days each rather than hours,
and `R4` and `R5` conflict enough that the order matters -- but they
need no decision, so they stay out of this file until one of them
does.
