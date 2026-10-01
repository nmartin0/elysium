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
| the nine agent files | `HANDOVER_*`, `REQUESTS_*`, `STATUS_*` -- 8,662 lines from three agents that no longer exist. 25 SEC findings rescued into the CSV first; every other id verified already tracked |
| `000COORDINATION.md` | the protocol for four agents that no longer exist, and all four branches are merged. Its ownership table was already wrong -- `SEC-06` measured it matching 89 of 145 source files. Consuming it surfaced a real conversion that had been unblocked for forty patches |
| `LIBRARY_AUDIT.md` | 1.1 superseded by its own Part 4.6; 1.2 MEASURED AND REJECTED, with the numbers now in `request_metrics.py` and eight tests enforcing it; 1.3 is available work, below. Parts 2-4 are reasoning about when to take a dependency, kept in `PRINCIPLES.md`'s territory |
| `OPEN_RISKS.md` | all five resolved or measured: 1, 2 and 5 fixed by earlier patches, 3 built and wired, 4's premise shown out of date in patch 490. Its 24 code citations now name what each risk WAS |---
| `GOLD_MIGRATION_SURVEY.md` | every file it named was reworked; its proposed shape IS `build_gold_view`. Its parity test exists and passes (42) |
| `ACCESS_CONTROL_PROPOSAL.md` | not built, and a change to what a grant MEANS. Below |
| `CONFIG_ROUND_TRIP_AND_UI_KIT.md` | not built; needs a dependency decision and product direction. Below |
| `OBJECT_EXPLORER_PLAN.md` | phases 1 and 2 (backend) built, and the blocker they existed to remove is gone -- `in` and `not_in` are in the filter vocabulary. Phases 3-5 are frontend; below |
| `THIRD_PARTY_EXTENSIONS.md` | a design, unbuilt. Its finding about module federation kept below, because it is the kind of thing a later reader would otherwise rediscover the hard way |# Blocked on a decision
| `TRIAGE.md` | fully absorbed: its 45 ids are CSV rows, its mutation sweep is the 70 declared controls in `scripts/check_controls.py`, its reachability sweep is the `WIRED-` rows |
| `LIVE_UPDATES_AND_PIPELINE_BUILDER.md` | nothing built; its security decision kept below because it is the reason the design is shaped as it is |
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

## 13a. Twenty-five inherited security findings

The security agent kept its own register because it was not allowed to
edit `AUDIT_CHECKLIST.csv`, and said so:

> ONE ASK OF BACKEND: fold these into `AUDIT_CHECKLIST.csv` and this
> file can go. It exists because I may not edit that one, not because
> two registers are a good idea -- and two lists is the exact failure
> this project keeps finding.

**That ask was never honoured while they existed.** Patch 487 did it:
all 27 `SEC-` ids are now rows. Six map onto work already done under
my numbering (`SEC-01` is `LLM3-1`, `SEC-02`/`SEC-03` are `LLM3-2`,
`SEC-05` is `PA001-A11`, `SEC-17` was rebuilt in patch 465). One was
withdrawn by its own author as overstated. The rest are open and
INHERITED -- raised by somebody who can no longer be asked what they
meant.

**Blocked on:** nothing, for the tractable ones -- they are ordinary
work now that they are on the list. Named here only because their
provenance matters: a finding whose author is gone cannot be
clarified, only reproduced or dropped.

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

## 20. Grant by TAG rather than by field name

From `ACCESS_CONTROL_PROPOSAL.md`. Declare a vocabulary -- `pii`,
`financial`, `internal`, `restricted` -- tag FIELDS with it, and let a
role grant `read:tag:pii` instead of enumerating every field.

**The burden it answers was counted rather than asserted**, which is
why the proposal is worth keeping whole:

        10 types x 15 fields   ->    160 grant strings PER ROLE
        50 types x 20 fields   ->  1,050 grant strings PER ROLE
       120 types x 25 fields   ->  3,120 grant strings PER ROLE

Every one hand-written, per role, per deployment. Add a property to a
type and every role that should see it needs editing.

The shape has a real safety property: a new property is UNREADABLE
until tagged, which is the deny-by-default behaviour already in place,
now at field level. It also proposes inheriting tags from the type and
declaring only exceptions.

**Blocked on:** this changes what a grant MEANS, and every existing
`policy.yaml` with it. Nothing of it is built -- no tags anywhere in
`core/` or `api/` -- so it is a decision before it is work.

## 21. Writing configuration from the UI

From `CONFIG_ROUND_TRIP_AND_UI_KIT.md`. Its own finding is why it is
hard: **the configuration files are mostly COMMENTS**, so a naive
load-and-dump destroys the thing that makes them readable. Its design
keeps YAML as the source of truth and round-trips through
`ruamel.yaml`, which preserves comments.

`ruamel` is not a dependency today, so this needs one of the `DEP`
answers before it is even possible.

**Blocked on:** that dependency call, and on whether configuration
should be editable from the UI at all.

## 22. Object Explorer phases 3 to 5

Phases 1 and 2 are built. **The blocker they existed to remove is
gone:** the plan opens with "our filter is equality only ... so
'region is us-west OR us-east' is not expressible -- which means
clicking two bars on a chart cannot be expressed either." `core/filters.py`
now has `in` and `not_in`, so it is.

What remains is frontend: the table, the charts, and saving and acting
on a selection. The last of those is the same thing as item 23 below.

**Blocked on:** product design, and there is no front-end agent.

## 23. A plugin API, and the reason module federation is not it

`THIRD_PARTY_EXTENSIONS.md` designs third-party extensions. None of it
is built, and whether Elysium should have them at all is a product
question.

**ITS MOST IMPORTANT FINDING IS WORTH KEEPING WHOLE**, because it is
the kind of thing a later reader would otherwise rediscover by
shipping it:

> A federated module runs **in your page, in your origin**. It gets
> the same DOM, the same cookies, the same `localStorage`, and the
> same authenticated access to every `/api/*` route as Elysium itself.
> The federation frameworks say so themselves -- they "do not claim
> that same-realm JavaScript is a security sandbox".

Module federation is the obvious answer and the wrong one. The design
proposes JSON-RPC 2.0 over `postMessage` instead, a third-party
adapter as a SILO, and ontology fragments declared as DATA rather than
code.

**Blocked on:** whether to have an extension story at all. Everything
downstream of that is design work that cannot start first.

## 24. Live updates, and the decision that shapes them

Nothing is built -- no SSE, no `EventSource`, no streaming response
anywhere in `api/`. What makes the design worth keeping is its
security decision, which is quoted rather than summarised:

> **EVENTS CARRY NO DATA.** An event says "something of this kind
> changed", never what changed. The client then refetches through the
> SAME authorised endpoints it already uses, so MAC, roles and every
> permission check apply exactly as they do now.
>
> The alternative -- pushing the changed object down the stream --
> would put a second, parallel read path beside the mediator, and
> every security rule would have to be re-implemented on it
> correctly, forever. That is how leaks happen. A hint plus a refetch
> cannot leak: the refetch is the existing, tested path.

It also notes that a hint's SCOPE needs care: "a Customer changed"
tells a user that SOME customer changed, so hints name a TYPE and a
kind of change and nothing more.

**And a measured answer to a question the owner asked:** whether an
alert could arrive as MAIL. SSE cannot do that -- it pushes to an open
browser -- and Elysium has NO SMTP SUPPORT OF ANY KIND today. Mail is
a separate delivery channel, not a variation on this.

**Blocked on:** whether live updates are wanted enough to carry a
streaming endpoint, and separately whether mail delivery is in scope
at all.

## 25. Saved SELECTIONS

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

**`LIB-3`, folding the SQLite adapter into the SQLAlchemy one as a
dialect**, joins them, and `LIBRARY_AUDIT.md` called it the strongest
of its three because it adds NO new dependency. `sqlite_adapter.py`
builds SQL by string interpolation at 50 sites while
`sqlalchemy_adapter.py` uses the expression API for the same job.

The risk it carries is identifier quoting: every f-string
interpolating a table or column name is a place where a declared
schema controls SQL text. That is configuration rather than user
input, which is why it has not bitten -- but a library that quotes
identifiers correctly answers a CLASS of bug rather than its
instances.

Write-path first, with the existing tests as the parity check. 75
files reference the SQLite adapter, most of them tests using it as the
cheap real database, and the write path is where a mistake reaches a
customer's database. Days, not hours -- but no decision, so not here.
