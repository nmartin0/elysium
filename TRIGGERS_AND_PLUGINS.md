# Triggers and the plugin API — a design

Two features that need building later and designing now, because both
touch the security model and both are hard to retrofit.

Neither is built. This file is what to build, why, and what the
precedent does.

---

# Part one: triggers

**What it is**: a condition on ontology data, and an effect when it is
met. Foundry calls this Automate; it replaced an earlier Object
Monitors product and is "a single entry point for all business
automation in the platform".

**Elysium has none.** Scheduling is deliberately external (cron, a
systemd timer), and `api/reload.py` records keeping a scheduler out as
a decision rather than an omission.

## What Foundry does, and which parts to take

**CONDITION + EFFECT**, with the conditions ontology-shaped:

- Objects **added to** a set
- Objects **removed from** a set — and note their example: monitoring
  open support tickets means the condition fires when a ticket's
  status changes to anything else. Removal from a SET, not deletion.
- Objects **modified in** a set, optionally watching named properties
- Streaming conditions, which we have no equivalent for and do not
  need: Elysium is snapshot-only, by a decision with the cost measured
  and the trigger named.

A "set" is a saved search. **Elysium already has saved explorations**
— a URL plus a name — which is the same thing.

**EFFECTS** are actions, notifications, or a function.

## THE PERMISSION MODEL IS THE PART TO COPY EXACTLY

Foundry splits it three ways, and it is subtler than it first looks:

- **Condition evaluation** uses the automation OWNER's permissions.
- **Action effects** execute AS the owner. Submission criteria are
  evaluated against the owner; the audit log records the owner.
- **Notification effects use each RECIPIENT's own permissions.**

They state the consequence plainly: an automation may "trigger for
some recipients but not others (based on their access)" and "send
different notification content to different recipients".

**FOR ELYSIUM THIS IS NOT A NICETY, IT IS THE ONLY CORRECT ANSWER.**
With MAC, a notification saying "3 transactions exceeded the
threshold" must say a different number to someone who can only see
us-west. Evaluating the notification per recipient is the difference
between a feature and a data leak, and it must be in the design from
the first line rather than added after someone notices.

## An action must be able to refuse automation

Foundry lets an action type toggle off "the switch that allows
Automate to submit the action", under Security & Submission Criteria.

Some actions should only ever be taken by a person who looked at the
screen. This is one field on the action type schema and it belongs in
the first version.

## Is proposing rather than executing a flaw? No — and we already have both

An earlier framing of this design said Elysium would PROPOSE where
Foundry EXECUTES, and asked whether that was a critical weakness. It
would have been. It is also not what Elysium does.

**`auto_execute` ALREADY EXISTS**, per action type, validated in
`core/ontology/action_types.py`, defaulting to confirmation and
enforced "in Python at the point of execution rather than by asking
the model to behave -- a prompt can be talked around, a branch
cannot".

Its own docstring cites the same Foundry reasoning: a deployment
"should be able to let an agent file a low-stakes note without also
letting it move money unattended".

**So an automation's effect uses the action's OWN setting.** An
auto-executing action fires; a confirmation-required action lands in
the approvals queue. No new concept, no new decision, and the
distinction is already validated at config load.

## THE REAL RISKS, which are about volume rather than authority

**QUEUE FLOODING.** `MAX_SUB_WRITES` is 20 and `DEFAULT_TTL` is 15
minutes. An automation firing across a thousand objects either exceeds
the sub-write cap or creates fifty pending writes that expire before
anyone reads them. Foundry has an "execute once for all objects"
option for exactly this; we would need the equivalent, plus a stated
answer for what happens when a condition matches more than the cap.

**FOUR-EYES AGAINST AN AUTOMATION.** Elysium's criteria vocabulary can
say "the approver must not be the proposer". If an automation proposes
as its owner, the owner cannot approve it — arguably correct, and it
means every confirmation-required automation needs a second human
every time it fires. Worth deciding deliberately rather than
discovering.

**EVALUATION CADENCE.** Conditions should be evaluated when the mirror
changes, because that is when data moves and nothing else can move it.
That ties triggers to the sync and gives a natural, already-scheduled
moment — no new scheduler, which keeps `api/reload.py`'s decision
intact.

## Sketch, in build order

1. A condition: a saved exploration plus a check (gained rows, lost
   rows, crossed a count). Evaluated after a successful sync.
2. A notification effect, evaluated PER RECIPIENT. In-product first;
   email and webhooks later, each a place data leaves the deployment.
3. An action effect, using the action's own `auto_execute`.
4. `automatable: false` on action types that must never fire unattended.

---

# Part two: the plugin API

**The goal**: third parties add sub-apps to a plain Elysium, with the
same libraries Elysium's own sub-apps use, front and back. Their
sub-app can register events, query through the agent, and have the
agent aware of it.

## THE BOUNDARY ALREADY EXISTS

`ui/packages/` holds five sub-apps — admin, approvals, browse, query,
schema — and one `shell-api`. Every sub-app imports from
`@elysium/shell-api` and nothing else: 113 imports across three
modules (`api`, `types`, `format`). The shell lazy-loads each panel.

**So the work is not inventing a plugin system. It is hardening a
boundary that exists and declaring it a contract.**

## DECLARE FIRST, THEN FIND THE CHEATING

The instinct to convert Elysium's own sub-apps onto the third-party
API is right, and the ORDER matters: declare the current boundary the
API, then find where the sub-apps reach past it. That list is
discoverable today. Building an API first and converting afterwards
discovers the same list later and more expensively.

This is the **two reference implementations** rule — ship at least two
non-trivial extensions from different categories, proving the
abstraction is not single-use. Five is stronger, and it is the same
discipline as the Vessel/PortCall ontology test: there, prove no Acme
nouns are baked in; here, prove no first-party privileges are.

## VERSION THE CONTRACT, NOT THE APPLICATION

SemVer the plugin API separately, with a manifest field naming the
contract a plugin needs. Elysium already has configuration
GENERATIONS, and a plugin declaring which contract generation it
requires fits that grain exactly.

## WHAT A PLUGIN SHOULD NOT GET

**A private channel to the agent.** The agent acts on a user's behalf,
and a plugin that could register agent capabilities directly is a
different security question from one that renders a page.

**Instead: a plugin extends the ONTOLOGY through the existing
mechanisms** — declares object types, actions, functions. Then the
agent's awareness comes free, and MAC, submission criteria, the
approvals queue and the audit log all keep applying without a second
implementation of any of them.

That is the single most important constraint in this document.

## WHAT TO PROMISE HONESTLY

"Robust charting, analytics, statistics" is a product in itself. There
is one `ChartsPanel`. Promising third parties a visualisation library
commits us to maintaining one, and the research is blunt: "plugin
support creates a permanent maintenance obligation."

Expose what exists, scoped honestly, and grow it. A narrow contract
that holds beats a wide one that breaks.

## THE SECURITY POSITION, stated rather than implied

Superset is the closest analogue and instructively modest: extensions
disabled by default behind a flag, external extensions running
in-process with the host, sandboxing "planned" rather than shipped,
administrators responsible for vetting what they install.

A data platform shipping extensions without isolation — and SAYING SO.
That is the honest starting position and better than claiming
isolation we do not have.

**So, for a first version:** off by default, in-process, vetted by an
administrator, and documented as such. Sandboxing is a later decision
with real options (out-of-process, WASM) and real costs.

## What would make this real

1. Freeze `shell-api` as a versioned contract; enumerate what it
   exposes.
2. Find every place a first-party sub-app reaches past it. Each is
   either a gap to fill or a privilege to remove.
3. A manifest: name, contract version, the routes and nav entries it
   claims.
4. A backend equivalent — a plugin contributing ontology fragments and
   functions, loaded through the same validation a deployment's own
   configuration gets.
5. Only then, a third-party example built with nothing else.
