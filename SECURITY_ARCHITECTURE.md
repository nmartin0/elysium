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

### 1. A request-scoped trace id

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

**A DECISION IT NEEDS FIRST:** whether Elysium's MAC values are
ORDERED. Bell-LaPadula assumes a lattice -- secret dominates
confidential. Elysium's values are regions (`us-west`, `us-east`),
which are incomparable rather than ranked. For incomparable values the
rule is simpler and stricter: **an action may not read one partition
and write another at all.** Whether that is too strict for real use is
the thing to find out before building it.

### 3. Intersection for action authority

An action declares at most what it may touch; effective authority is
the intersection with the user's. Attenuation only.

Partly exists already: `_validate_effects_are_reachable` bounds an
action's effects by its parameters. This makes the bound explicit and
composable rather than derived.

### 4. The grant algebra, specified

Once 2 and 3 exist there is something worth specifying, and the
properties above become testable rather than aspirational.

---

## What this is not

**Not a capability system.** Objects do not become principals; they
have no agency to grant.

**Not a second permission framework.** Every piece extends
`check_access()` and the audit log that already surrounds it.

**Not a claim of verification.** A verified grant algebra, at most,
with everything around it tested as now.
