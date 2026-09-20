# Non-user-derived constraints — an assessment

**The question**: should objects and actions be gated by the same
RBAC/MAC framework as users, so that boundaries inside Elysium are
enforced rather than conventional?

**The short answer**: the instinct is right and one part of it is a
real, named hole. The rest divides into what already exists, what
would be dangerous, and what is worth doing in a particular order.

Nothing in this file is built.

---

## What already exists, and should not be rebuilt

`check_access()` is the chokepoint. **24 call sites**, and every one
writes an audit line before returning. Object visibility gated by MAC
IS the current model.

So "objects gated by RBAC/MAC" is not a new mechanism. Proposing one
beside it would be a parallel system; the work is extending the
chokepoint that exists.

**AND THE EFFECT-REACHABILITY CHECK IS THE FIRST NON-USER-DERIVED
CONSTRAINT.** `_validate_effects_are_reachable()` says an action may
only mutate types its parameters reach, regardless of who runs it.
Everything below is a continuation of that, not a departure from it.

---

## THE REAL HOLE: Elysium enforces half of MAC

**EVERY MAC CHECK COMPARES AN OBJECT TO THE USER'S SECURITY VALUE.
NOTHING EVER COMPARES TWO OBJECTS TO EACH OTHER.** Verified: six call
sites of `_security_allowed`, every one against
`user_record.security_value`.

Consider an analyst cleared for both EU and US data, running an action
that reads an EU customer's email and writes it into a US-classified
record. **Every MAC check passes** -- the user may see both objects.
EU data now sits in a US object, readable by someone cleared only for
US.

**The boundary was crossed by DATA, not by a person, and nothing
looked.**

This is Bell-LaPadula's **\*-property** -- *no write down* -- which MAC
systems have enforced since the 1970s. Elysium enforces the **simple
security property** (no read up) and not its partner. Neither term
appears anywhere in the codebase, so this is not a decision that was
made; it is one that has not been noticed.

**IT IS ALSO THE HONEST FORM OF "CAN OBJECTS SEE OTHER OBJECTS".** The
question is not whether an object may READ another -- objects have no
agency and do not read. It is whether one object's data may FLOW into
another, which is information flow control.

---

## What would be dangerous, and the safe form of it

**ACTIONS CARRYING THEIR OWN AUTHORITY IS A CONFUSED DEPUTY.** If an
action can do something its caller cannot, it is a privilege
escalation vector wearing a feature's clothes. Foundry avoids this by
executing as the automation's owner and checking submission criteria
against them.

**THE SAFE FORM IS INTERSECTION.** An action may touch at most X; the
user may touch at most Y; effective authority is X ∩ Y. That only ever
REDUCES power. Attenuation, never amplification.

Stated as a rule to hold to: **no mechanism added here may let a
request do something the requesting user could not already do.**

---

## On formal verification — what is and is not realistic

**VERIFYING ELYSIUM IS NOT REALISTIC**, and claiming it would be the
kind of overclaim this project keeps catching. It is Python over
SQLite, Iceberg, pyiceberg and FastAPI.

**THE seL4 PATTERN IS**: verify a small core, test the rest. Elysium's
grant algebra is small enough to specify precisely --

- is intersection associative and commutative?
- can a composition of two permitted effects exceed the union of what
  each permits?
- does attenuation hold under every path a request can take?

Those are answerable, and answering them is worth something. "The
internals are formally verified" would not be true and should not be
said.

**WORTH WRITING DOWN ONLY AFTER THE PIECES IT DESCRIBES EXIST.** A
specification of a mechanism that has not been built describes an
intention rather than a system.

---

## On category theory — keep the content, drop the vocabulary

The useful claim underneath is:

> **Effects compose, and composition preserves constraints.** If
> action A may touch {Customer, Transaction} and B may touch
> {Transaction}, then A-then-B may touch at most the union, and
> nothing in a composition may exceed it.

That is checkable, and statable without naming a functor. The value is
in the DISCIPLINE -- behaviour following a known pattern, so that
reasoning about the whole is possible from the parts -- rather than in
the vocabulary.

**AND THE VOCABULARY HAS A COST.** Every reader of the code would need
it. A property written plainly is enforced by a check anyone can read;
one written categorically is enforced by a check fewer people will
maintain.

---

## Build order, with the reasoning

### 1. ~~A request-scoped trace id~~ MOSTLY DONE

**THE MECHANISM ALREADY EXISTED AND REACHED ALMOST NOTHING.**
`RequestContext` carries a `request_id`, `check_access()` stamps it on
every audit line, `entries_for_request()` reads them back -- and ONE
ROUTE OUT OF THIRTY-NINE created one. Browse did not, so twelve
object-reading call sites wrote untracked lines.

`get_object` also dropped it: a per-field loop around `get_field`,
which accepted a context all along.

Search and object-detail now carry one, AND RETURN IT, which is what
makes the trace reachable.

**THE WAY TO ASK ALSO ALREADY EXISTED:** `GET /requests/{id}/trace`,
scoped to the caller's own requests. Query returned its id and its UI
showed the trace; Browse recorded one nobody could ask for, which is
the same as absent for anyone trying to use it.

**STILL OPEN:** the remaining object-reading routes, and ADMIN-SIDE
tracing. The endpoint filters to the caller's own user_id -- correct
for transparency, useless for debugging someone else's request. Those
are two different needs and only one is served.

**SMALLEST, AND IT MAKES EVERYTHING BELOW OBSERVABLE.**
`check_access()` already sees every object access and already writes an
audit line. What it cannot answer is "show me everything this one
query touched, in order", because nothing ties the lines together.

Would have shortened several real debugging sessions. It is also the
foundation the diagnostic sweep and the per-hop agent metrics both
need, so it pays for itself three times.

### 2. Flow control on actions — the write-down check

The concrete form of the object-to-object question. Compare the
security values of objects an action READS against those it WRITES,
and refuse a write-down.

The chokepoint already knows every value it needs; what is missing is
the comparison. Precedented, bounded, and it closes a hole rather than
adding a feature.

**THE DECISION IS SETTLED, and the question was wrong.** It asked
whether Elysium's MAC values are ORDERED or INCOMPARABLE. Bell and
LaPadula's own model has BOTH, and the answer was in the original
paper.

**A SECURITY LABEL IS A PAIR:** a sensitivity LEVEL and a set of
COMPARTMENTS. Given `L1 = (S1, C1)` and `L2 = (S2, C2)`:

    L1 <= L2   when   S1 <= S2   and   C1 subset-of C2

Levels are TOTALLY ordered -- Unclassified, Confidential, Secret, Top
Secret. Compartments are NOT ordered at all; they are a set, and the
relation between two sets is containment.

**SO INCOMPARABILITY IS NORMAL, NOT A PROBLEM TO DESIGN AROUND.** The
standard teaching example is `(secret, {crypto})` against `(top
secret, {nuclear})` -- neither dominates the other, and the model
expects that.

**ELYSIUM'S VALUES ARE COMPARTMENTS.** `us-east` and `us-west` are
disjoint sets with no ranking, which is exactly what a compartment is.
The current check -- string equality -- is the DEGENERATE CASE of the
lattice: one compartment each, and equality is `C1 subset-of C2` in
both directions at once.

**WHICH MAKES THE WRITE-DOWN CHECK SMALL.** It is the same dominance
predicate applied between two OBJECTS rather than between an object
and a user. The published assessment of this is that "the lattice is
mechanizable: dominance, least upper-bound, and reading/writing
predicates are simple, total, decidable functions on integer ranks
plus subset tests on compartment sets".

**AND THE REMAINING CHOICE IS SETTLED TOO: COMPARTMENTS ONLY.**
Researched against Foundry, which Elysium models itself on, and the
answer is the opposite of adopting the pair up front.

**FOUNDRY KEEPS THEM APART, and ships only one by default.** Markings
are compartments -- "to access a resource, a user must be a member of
ALL Markings applied to a resource", which is set containment exactly.
Classification-based Access Controls are levels -- "every user can
only access data that is classified at or below their own
classification level". And "classifications can NOT be used together
with markings or organizations on the same mandatory control
property".

**CBAC IS OFF BY DEFAULT**, and "configuration of classification
markings requires Palantir involvement". So the system this design
follows treats compartments as the default and levels as an opt-in
extension needing vendor setup.

**AND DEFERRING LEVELS COSTS NO EXPRESSIVENESS**, which is why that
works. Foundry notes markings can express hierarchy anyway: "the data
tiers are hierarchical, and users who have access to the Identifiable
Data Marking also have access to the De-identified Data Marking". A
level hierarchy is a CHAIN OF NESTED COMPARTMENT SETS -- `{secret}`
inside `{secret, topsecret}` gives "top secret dominates secret" with
no levels mechanism at all. Levels are ergonomics over something
compartments already say.

**SO THE CHECK IS SMALLER THAN THE LATTICE SUGGESTS:**
`source_compartments` must be a subset of `target_compartments`, and
with today's single-string values that is the equality already in the
code -- applied between two OBJECTS instead of object-and-user.

**ONE THING NEITHER MODEL COVERS**, recorded before somebody asks for
it: Foundry's classification markings have DISJUNCTIVE components,
where "users belonging to one of the groups... can satisfy the CBAC
access condition. This is commonly used to define releasability." OR
rather than AND. Neither Bell-LaPadula nor Elysium has it, and
"shareable with partner X or partner Y" is the request that will want
it.

**AND TWO SPECIAL LABELS COMPLETE THE LATTICE**, worth having from the
start: SYSTEM_HIGH dominates everything (highest level, every
compartment) and SYSTEM_LOW is dominated by everything (lowest level,
no compartments). Without them a lattice has no top or bottom, and
code that needs one invents a special case.

### 3. ~~Intersection for action authority~~ ALREADY ATTENUATED

**VERIFIED, AND THERE IS NOTHING TO INTERSECT.** The entry assumed an
action "declares at most what it may touch". It declares
`affected_object_types`, `description`, `parameters` and `sub_writes`
-- and NO AUTHORITY OF ITS OWN. There is no second authority to
intersect the user's with.

**AND EVERY ACTION WRITE IS ALREADY CHECKED AGAINST THE CALLER.**
`_security_allowed(object_type, object_id, user_record.security_value)`
-- the caller's own value, at every write. Nothing impersonates,
nothing synthesises a UserRecord, nothing runs as a service account.
Confirmed by search rather than by reading.

**SO THE CONFUSED-DEPUTY RISK IS ALREADY CLOSED** on the axis that
matters. What remains is the RBAC side, and that is deliberate rather
than missing: a user needs `execute:ActionName` and NOT a write grant
on the underlying type, because an action IS the capability. Granting
"may transfer funds" without granting "may write Account" is the
reason named actions exist, and Foundry's model is the same.

**WHAT THE ENTRY WAS REACHING FOR**, if anything: making the bound
`_validate_effects_are_reachable` computes at config load into
something composable -- a declared capability rather than a derived
one. That is a refactor with a design benefit, not a hole, and it
should be labelled as such rather than sitting in a security list
where it reads as a gap.

**THE THIRD SECURITY ENTRY TO BE SMALLER THAN WRITTEN**, after 0.3's
cache bound and 3.5's ordered-vs-incomparable question. All three
described a defect that reading the code carefully ruled out.

### 4. The grant algebra, specified

2 and 3 exist, so these are no longer aspirational. Each is pinned by
a UNIVERSAL test in `tests/unit/test_grant_algebra.py` -- one that
fails when a NEW mechanism appears, not merely when an existing one
breaks.

**ONE CHOKEPOINT.** `write_fields` and `create_object` are the only
ways an adapter mutates anything, and both are called from
`write_mediator` alone. Verified across the whole tree. A second
caller would bypass the pending-write log, the approvals queue, the
MAC check and the compartment check at once, while every test of
those still passed.

**ATTENUATION ONLY.** No mechanism may do what its caller could not.
An action declares no authority of its own, and every write is
checked against `user_record.security_value`. Nothing synthesises a
UserRecord -- which is the shape this fails in: a service account, a
scheduled trigger, an automation "running as the system".

**AUTHORITY IS NEVER STORED.** It is re-evaluated at the point of
use, against the CURRENT generation. A pending write survives a
restart and a reload, so a decision taken at proposal would be taken
under rules that may no longer exist.

**DATA DOES NOT CROSS COMPARTMENTS.** Every other check compares an
object to the USER; the \\*-property check compares what was READ to
what is being WRITTEN, which is the only way a flow is visible at
all.

**AND THE DOCUMENT AND THE TESTS MUST AGREE.** A test file is not a
specification -- somebody reasoning about this reads here, somebody
changing it runs those -- so a test fails if this section stops naming
what it checks. It fired once already, on the edit that removed
"attenuation only" while correcting item 3.

---

## What this is not

**Not a capability system.** Objects do not become principals; they
have no agency to grant.

**Not a second permission framework.** Every piece extends
`check_access()` and the audit log that already surrounds it.

**Not a claim of verification.** A verified grant algebra, at most,
with everything around it tested as now.
