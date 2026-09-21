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

A "set" is a saved search, and an earlier version of this file said
Elysium already had them.

**THAT WAS HALF TRUE AND MISLEADING.** `SavedView` is `{name, url,
saved_at}` in the BROWSER'S localStorage. The concept exists and the
SERVER CANNOT SEE IT -- so nothing that runs on a schedule can
reference one, which is exactly what a condition must do.

**MOVING SAVED VIEWS SERVER-SIDE IS THE REAL PREREQUISITE** for
object-set conditions, and it is a larger piece than the per-recipient
evaluation below. It needs an owner, a name, a stored query rather
than a URL, and a decision about whether one person's saved view may
be referenced by another person's automation.

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

## HOW PER-RECIPIENT EVALUATION ACTUALLY WORKS

An earlier version of this file called this "the genuinely novel
security work". It is not novel at all, and seeing why is what makes
the design right.

**`search_object(user_record, ...)` ALREADY TAKES A USER.** So:

    condition evaluated as the OWNER      did this fire at all?
    condition evaluated as a RECIPIENT    what does their
                                          notification say?

Both go through `check_access`, MAC and the audit log unchanged.
**There is no second permission path to get wrong**, which is the
property that matters more than any other here.

### Three things fall out for free

**A RECIPIENT WHOSE EVALUATION RETURNS NOTHING GETS NO NOTIFICATION.**
Not an empty one -- none. That is Foundry's "may trigger for some
recipients but not others", arrived at as the natural behaviour rather
than a special case: if you can see nothing, there is nothing to tell
you.

**THE COUNT IS PER-RECIPIENT BY CONSTRUCTION.** Alice's notification
says 3 because her search returned 3; Bob's says 1 because his
returned 1. Nobody computes a "real" number and redacts it -- THERE IS
NO PRIVILEGED VIEW TO LEAK FROM.

**AND EVERY NOTIFICATION IS AUDITED**, because the evaluation went
through the normal read path. "What did Bob's notification tell him"
is answerable from the trail that already exists.

### The rule to write down

**A notification carries only what its recipient's own evaluation
produced.** Never a number computed once and shared; never a payload
assembled by the owner and filtered afterwards.

Filtering-after-assembly is where these systems leak, because the
unfiltered thing existed.

### What it costs, honestly

**N SEARCHES PER FIRING**, one per recipient. Bounded by the scan
ceiling, and not free: fifty recipients means fifty searches.

**AND ACTION EFFECTS ARE CHEAPER THAN NOTIFICATIONS**, which is the
opposite of what an earlier version of this file assumed.
`propose_action(user_record, action_type, parameters, origin)` already
exists, already takes a typed origin, and already lands in the
approvals queue with criteria, four-eyes, TTL and audit. A
NOTIFICATION has no machinery at all -- no delivery channel, no
recipient concept, nothing.

So "notifications first because the approvals integration can wait"
was wrong twice over: the integration is nearly free, and the
notification plumbing is the part that does not exist.

**THE REAL ARGUMENT FOR MIRROR HEALTH FIRST** is narrower and better:
you cannot auto-fix a refused sync, so that condition admits no action
effect. The first condition is notification-only because of what it
is, not because notifications are cheaper.

## ~~An action must be able to refuse automation~~ BUILT

`automatable: false` on an action type, validated at config load and
refused at PROPOSAL -- so it never reaches a queue looking like a
decision somebody could make.

**A DIFFERENT QUESTION FROM auto_execute**, and the two are easy to
confuse. `auto_execute` asks whether a proposal needs confirming;
`automatable` asks whether a trigger may propose it AT ALL. An action
can be both: safe without confirmation when a person asked, and never
started by a condition firing at 3am.

**ABSENT MEANS TRUE**, which is the one permissive default in that
validator. Every action already passes through the approvals queue
unless `auto_execute` says otherwise, so a trigger proposing one
produces a pending write somebody must decide on. The flag is for
actions that should not even be PROPOSED unattended.

**AND `automation` IS A THIRD ORIGIN**, not a kind of agent. An agent
is a model reasoning on somebody's behalf in a conversation they are
having; an automation is a condition that fired while everybody was
asleep. `origin` reaches the audit trail and the approval criteria,
so that difference matters most to whoever decides whether to approve
it.

**THE REFUSAL IS NOT A PermissionError.** Nobody's grants are wrong
-- the action itself says it must be started by a person.

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

## SUPERSEDED IN PART -- see THIRD_PARTY_EXTENSIONS.md

The plugin half of this document assumed plugins could run in-process,
administrator-vetted, the way Superset ships extensions. A later
assessment took the stricter premise -- every component untrusted,
including first-party -- and reached different conclusions:

- **MODULE FEDERATION IS DISQUALIFIED**, not merely risky. It gives
  remote code the host's DOM, cookies and authenticated API access.
- **A third-party adapter is a SILO**, so the mirror pipeline is
  already the sandbox for its data.
- **The channel comes before the boundary**, because isolating an
  inadequate API means doing both twice.

What holds from this document: the boundary already exists, declare it
before converting to it, and a plugin must not get a private channel
to the agent.

## THE MIRROR'S OWN HEALTH IS A CONDITION, and was missing here

Everything above is a condition on ONTOLOGY DATA -- objects added,
removed, modified. That is Foundry's vocabulary and it leaves out the
thing an administrator most needs told.

**THE QUESTION THAT EXPOSED IT:** an administrator idle on the mirror
panel learns nothing until they reload -- and worse, one who is not
looking at all learns nothing ever. A sync refused at three in the
morning is discovered on Tuesday.

Polling the panel makes it fresher for somebody already watching. It
does nothing for the case that matters, and mistaking it for a fix
would leave the real gap open.

**A DASHBOARD IS FOR INVESTIGATING A PROBLEM YOU KNOW ABOUT.
NOTIFICATION IS FOR LEARNING ONE YOU DO NOT.**

So the condition vocabulary needs a second kind:

    a sync was REFUSED
    a table has not synced successfully for longer than N
    the integrity check found a problem

Each is already computed. `sync_attempts` records every refusal with
its full drift report; `check_mirror` returns its problems; the
snapshot carries the last change. Nothing needs measuring that is not
already measured -- what is missing is something that WATCHES.

**AND THE EFFECT SIDE NEEDS NO CHANGE.** These are notifications, and
notifications already evaluate per recipient. A mirror failure is not
MAC-sensitive in itself, but who should hear about it is a grants
question, and routing it through the same machinery keeps that answer
in one place.

**EVALUATED AFTER A SYNC,** which is where the data changes and where
the cadence argument above already put it. A refused sync is exactly
the moment to decide whether somebody should be told.

## Sketch, in build order

0. ~~MIRROR HEALTH FIRST~~ **BUILT.** `core/notifications.py` holds
   one row per recipient; `core/mirror/health_condition.py` is the
   condition; `scripts/run_sync.py` evaluates it after every sync,
   which is the only moment the facts are current.

   **REPEATS ARE SUPPRESSED PER RECIPIENT**, comparing the SUMMARY
   rather than the condition -- "3 tables stale" becoming "5 tables
   stale" is news and goes through.

   **RECIPIENTS COME FROM A GRANT**, `manage:deployment`: if you can
   start a sync you should hear that one is needed, and adding an
   administrator changes the recipient list by doing so.

   **AND THE UI EXISTS**, at `/notifications`: a panel listing what
   arrived, newest first, with a per-row read control.

   **UNGATED, FOR THE SAME REASON AS APPROVALS.** Notifications are
   scoped by user in the query, so somebody with none sees an empty
   page rather than a forbidden one -- the uniform denial every read
   path here uses. Gating would also be WRONG rather than merely
   unnecessary: a notification goes to whoever a condition names,
   decided per condition, and no single permission describes that.

   **MARKED SEEN ON A CLICK, NOT ON RENDER.** Opening a list is not
   reading it, and a badge that cleared itself when somebody glanced
   at the tab would lose the one thing it is for.

0. (original note) MIRROR HEALTH FIRST, because it is the smallest and the most
   clearly needed: a sync refused, or a table stale beyond a
   threshold. The facts are already recorded; nothing watches them.
   It also exercises the whole path -- condition, effect, recipient --
   WITHOUT NEEDING SAVED VIEWS TO EXIST SERVER-SIDE, which is the
   prerequisite the object-set conditions have and this one does not.

0.5 ~~SAVED VIEWS, SERVER-SIDE~~ **BUILT.** `core/saved_views.py`,
   with `GET/POST /saved-views` and `DELETE /saved-views/{id}`.

   **A STORED QUERY, NOT A URL.** The URL carried `type`, `q`,
   `sort`, `view` and `filters`; only the first, second and last
   describe WHAT MATCHES. The others describe how a person likes to
   look at it, which a condition counting rows should not have to
   parse a URL to ignore.

   **THE CROSS-USER QUESTION IS ANSWERED: THEY STAY PRIVATE.** A
   query can name specific ids -- "customer_id = cust_001" says
   cust_001 exists -- which is the leak shape that deferred the Query
   panel's starter questions.

   **AND A CONDITION STILL WORKS ACROSS RECIPIENTS**, because a
   recipient never sees the query. They see the condition's
   DESCRIPTION, which its author wrote, and their OWN count from
   running that query with their OWN authority. The query is used on
   their behalf and never disclosed to them.

   **VERIFIED ON THE SHIPPED DEPLOYMENT:** the same "All
   transactions" view counts 4 for a us-west reader and 2 for a
   us-east one.

0.75 ~~A TRIGGER SOMEBODY MAKES~~ **BUILT.** `core/triggers.py`, its
   endpoints, and the UI.

   **MADE WHERE THE VIEWS ARE:** each saved view carries a Watch
   control, and a dialog asks what to watch for -- a dialog rather
   than another menu level, because a threshold needs a number and a
   choice, and a submenu asking for both is a form pretending not to
   be one.

   **MANAGED WHERE THE NOTIFICATIONS ARRIVE.** The Notifications
   panel has two tabs -- what you have been told, and what will tell
   you -- because those are one question from two ends, and somebody
   silencing a noisy trigger arrives from the notice it sent.

   **DISABLE BEFORE DELETE.** Somebody quieting a trigger usually
   wants it back, so the switch comes first and removing is separate.

1. A condition: a saved exploration plus a check. **HALF BUILT** --
   `core/count_condition.py` holds the check; the saved exploration
   is what 0.5 is for.

   **IT IS A COUNT, NOT A DIFF**, and researching that made the item
   much smaller. No alerting system worth copying stores last time's
   RESULT SET: Databricks keeps OK/TRIGGERED/ERROR per evaluation,
   Google Cloud compares "the number of rows in the query result"
   against a threshold over a lookback window, and the canonical
   change-detection pattern is a saved watermark.

   **WHICH MAKES PER-RECIPIENT EVALUATION FREE.** Each person's
   previous result set would be tens of thousands of ids times however
   many recipients; an integer each is nothing.

   **LOST ROWS ARE REPORTED, AND THE AMBIGUITY IS RESOLVED RATHER
   THAN AVOIDED.** A count that fell may mean the data moved, or that
   the READER'S GRANTS changed -- and `source_digest` tells them
   apart, because it covers policy.yaml. A count taken under a
   different configuration is not compared at all; the baseline
   resets instead.

   **BOTH DIRECTIONS**, not only the fall: somebody granted a new
   region sees more objects without anything having been added.

   **IT STILL SAYS "3 FEWER", NEVER "THESE THREE"**, and that does
   not change -- knowing which needs last time's result set, which is
   exactly what is not stored. A monitoring tool names the residue: a
   row "disappearing from a result list never becomes
   AD_BECAME_INACTIVE".

   **AND THE BASELINE ANNOUNCES ITSELF.** A first evaluation sends
   "now watching, currently N" -- information rather than an alert,
   because silence is indistinguishable from a condition that never
   ran.
2. A notification effect, evaluated PER RECIPIENT. In-product first;
   email and webhooks later, each a place data leaves the deployment.
3. ~~An action effect~~ **BUILT.** `propose_action_effect` in
   `core/count_condition.py`.

   **AS THE OWNER**, per the permission split above. A notification is
   evaluated per RECIPIENT; an action is not, because an action is a
   write and a write has one author.

   **RE-RUN RATHER THAN REMEMBERED**, which resolves a tension this
   design created. Conditions compare COUNTS, so when one fires
   nothing knows WHICH objects matched. The effect asks again -- and
   the set may differ slightly from the one that tripped the count,
   which is the RIGHT answer rather than a compromise: an action
   should operate on what matches when it RUNS, not on what matched
   when somebody noticed.

   **IT PROPOSES, IT DOES NOT EXECUTE.** The pending write lands in
   the approvals queue with `origin="automation"`, and an action
   declaring `automatable: false` refuses before the queue.

   **AN EMPTY SET PROPOSES NOTHING**, because an action over no
   objects is a decision somebody has to read and dismiss.
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

## A PLUGIN'S DATA SHOULD BE DISCUSSABLE WITH THE AGENT

The natural next question: can a third-party sub-app's data be talked
about in Query, not just rendered?

**YES, AND THE CONSTRAINT ABOVE IS WHAT MAKES IT FREE.** A plugin that
declares object types, actions and functions is already in the
ontology, and the agent's world IS the ontology. Nothing further is
needed: its objects are searchable, its fields readable under MAC, its
actions proposable through the approvals queue.

**FOUNDRY REACHED THE SAME PLACE.** Their chatbots take "context from
the Ontology or tools such as functions", and "can be published as
Functions, which allows them to be used anywhere in the platform where
Functions can be executed" -- so a chatbot is not a special kind of
thing, it is a function. A plugin contributing conversational
behaviour is a plugin contributing a function.

That is the same conclusion reached here from the security side, which
is a good sign: the constraint that keeps plugins safe is also the one
that makes them powerful.

---

# Part three: a help assistant, separate from Query

**What it is**: a chat that answers questions ABOUT ELYSIUM -- how to
use it, how to administer it, how it is built -- rather than about a
deployment's data.

**PRECEDENT: AIP Assist**, "an LLM-powered support tool designed to
help users navigate, understand, and generate value with the Palantir
platform". It has modes: Platform Documentation Assist for the docs,
Developer Assist for APIs and examples, and user-built chatbots.

## THE SECURITY PROPERTY IS THE WHOLE DESIGN

Palantir state it plainly: AIP Assist **"does not access your data"**.

That single sentence is what makes this a small feature rather than a
second Query. A help assistant needs:

- no MAC evaluation, because it reads no objects
- no submission criteria, because it proposes no writes
- no audit of data access, because there is none
- no per-recipient evaluation, because every user may see the same
  documentation

**It is a different product with a different threat model, and it
should be a different sub-app** -- not a mode of Query, where the
distinction would be one wrong branch away from leaking.

## WHAT IT WOULD READ

Generic, non-deployment-specific Elysium documentation: the user
manual, the administration manual, the architecture notes. Everything
in this repository's own documents is already written in that register.

**AND A DEPLOYMENT SHOULD BE ABLE TO ADD ITS OWN.** Foundry allows
"custom content sources" -- an organisation's own markdown registered
into the same assistant. For Elysium that would be a deployment's
runbooks and internal conventions, which is exactly the material a new
user asks about and which no generic manual can contain.

That is a content-source registry, not a code change, and it fits the
`deployment/etc` pattern already used for everything else a deployment
declares.

## CONTEXT WITHOUT DATA

AIP Assist is "aware of what Foundry application you are in". The
equivalent: knowing a user is on the Approvals screen so "how do I
reject this" answers about approvals rather than in general.

**That is navigation state, not data.** Passing the current route is
safe in a way passing the current object would not be, and the
distinction is worth writing into the interface rather than trusting.

## WHY IT MATTERS MORE THAN IT LOOKS

Elysium's operational surface is scripts. check_mirror,
repair_catalog, run_sync, measure_prompts, create_e2e_users -- each
needs a terminal on the host and knowledge of when to use it. A help
assistant that can answer "the mirror is stale, what do I do" is the
difference between a product an administrator can run and one they
need us for.

---

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
