# IDEAS.md

Things under discussion, before they are decided.

**HOW THIS DIFFERS FROM ROADMAP.md AND UI_ROADMAP.md.** Those record
work this project has committed to, in an order it has reasoned about.
This file records ideas that have not earned that yet -- proposals with
open questions, measurements not yet taken, and approaches whose cost
is not yet known. An entry graduates to a roadmap when the open
question in it is answered, and is deleted when the answer is "no".

Entries state their confidence and, where the honest answer is "measure
first", say what the measurement is. An idea recorded with a plan for
deciding it is worth more than one recorded with an opinion.

---

## The agent asks too many questions to answer one

**Observed, not inferred.** A real trace of "how many transactions does
Ada Okafor have?" on the CPU-only deployment took six gathered entries
across five model calls, two of which fetched `transaction_date` -- a
field that answers nothing about how many transactions exist. Roughly
75 seconds of a 443-second query spent on data the question did not
need.

This is now the bottleneck, and it is a different one from where the
week started. The loop is cheap per step and wasteful in steps.

**NO DIAGNOSIS YET, and three candidate causes needing different
fixes:** the aggregate guidance may be positioned badly, buried
mid-prompt where it competes with everything else; it may be worded too
weakly; or a 3.8B model may simply not recognise "how many" as an
aggregate at all.

**The measurement, which costs no code.** Take the real system prompt
and make three one-shot calls, no loop: the aggregate section moved to
just before the examples, the section reworded imperatively, and the
question rephrased as "count the transactions". Whichever moves the
result identifies the cause.

**WHY MEASURE FIRST rather than just improve the prompt.** Every
instruction added is prefill paid on every hop of every query, forever.
At the 5.9 tokens/sec measured here, fifty tokens of new guidance costs
~8 seconds per hop. Adding text to fix a case nobody has characterised
is how a prompt bloats, and prompt size is exactly what the last round
of work went into reducing.

**A structural alternative worth weighing before any prompt edit.** The
`transaction_date` fetches suggest the model does not know when it has
enough, rather than that it prefers the wrong step. There is already an
asymmetry nudge at finish; extending that idea -- a "you can answer
now, stop" check -- attacks over-fetching directly instead of steering
toward one particular step type. Cheaper in prompt tokens, and helps
every question shape rather than one.

Confidence: low on any fix, high that measuring first is right.

## Counting across a link, which the model keeps asking for

Three times in one run, qwen2.5:3b emitted:

    aggregate_object(Customer, count, field_name="transactions")

`transactions` is a LINK, so this is refused -- correctly, since a link
is not a column. The supported route is search_around to the far side,
then aggregate there.

**But the INTENT is entirely reasonable**: "count this customer's
transactions" is the obvious reading of the question that was asked.
The model was corrected once, followed the advice and used
search_around at step 4 -- then reverted to the same invalid shape at
step 7 and repeated it until the run stopped.

**A model persistently reaching for the same unsupported shape is
usually a signal about the API, not the model.** Two routes to the same
answer, one of which is refused, and the refused one is the one that
matches how the question was phrased.

Worth considering: allow `count` over a link field, meaning the number
of linked objects on the far side, resolved through the link machinery
rather than as a column. It is a real ontology operation -- link
cardinality -- and it collapses search_around-then-count into one hop,
which on this hardware is ~190 seconds saved per occurrence.

**Open questions before building it.** Whether MAC on the far side is
correctly applied -- counting links must count only objects the caller
may see, or the count itself leaks. Whether it generalises past `count`
(sum over a link's far side is coherent but a bigger change). And
whether Foundry has an equivalent, which has not been checked.

Confidence: medium that this is worth doing, high that the repeated
attempts are evidence and not noise.

## Aggregates are not being chosen when they should be

**AMENDED TWICE, and both amendments are recorded rather than edited
away, because the reversals are the useful part.**

Originally this entry said the model "ignores" the aggregate guidance
and speculated about wording and position. Then a live run surfaced
`unrecognized step 'aggregate_object', finishing` and the conclusion
flipped: the model was not ignoring anything, the parser was silently
discarding it. Then a probe asked three aggregate-shaped questions from
an empty gathered and got `search_object` for all three -- including
"what is the total of all transaction amounts?", where it picked the
wrong OBJECT TYPE entirely.

**So both causes were real and independent.** The parser discarded
aggregates the model did emit (fixed). The model ALSO under-selects
aggregates as an opening move, missing two of three cases where one
would answer in a single hop. Only the first is closed.

The lesson is narrower than "measure first" -- there was a
measurement, and it was over-read. One observation of the model
emitting an aggregate showed that it CAN, not that it reliably does,
and that was generalised into a conclusion about a different
question.

That is not "chose a suboptimal path" -- it is "did not recognise the
question type", which is a different problem.

**Scope it before spending prompt budget.** Ask five or six questions
of different shapes -- "how many", "what is the total", "which ones",
"show me" -- one hop each, checking only whether step 1 is an aggregate
where one would serve. If aggregates are missed across all shapes, it
is systemic and worth real investment. If only "how many" fails, it may
be one example.

**Deliberately NOT the fix: special-casing "how many" in the prompt.**
That teaches a keyword rather than a concept, and the next phrasing
fails identically.

## Approvals step 3, and the landmine already under it

The only item here that is product work rather than maintenance, and
the best specified. Everything else on this list came out of a
performance detour whose purpose was making this testable.

**The blocker: REMOVED.** A criterion's `value:` now resolves
`parameter.<name>` and `user.<attribute>`, the same vocabulary a
mutation's value already used. Four-eyes is expressible:

    check: user
    field: user_id
    operator: not_equals
    value: proposer.user_id

`proposer.`, NOT `parameter.proposed_by`, and the difference is the
security of the rule. A parameter is filled in by whoever PROPOSES the
write, so a four-eyes rule reading `parameter.proposed_by` is trivially
defeated: the proposer passes somebody else's id and approves their own
write. The rule would be present, evaluated, and useless. Same argument
as user.security_value on the mutation side -- the values a rule
depends on for its OWN integrity cannot come from the party the rule
constrains.

An unresolvable reference RAISES rather than resolving to None, and
that direction is the point: a criterion whose expected value silently
became None compares unequal to almost anything, so the rule above
would PASS for every approver INCLUDING the proposer. It would look
present and enforce nothing.

**The vocabulary already exists elsewhere.** `_resolve_mutation_value`
resolves `parameter.<name>` and `user.security_value` today. Extending
that same convention to the criteria `value:` side is consistent rather
than novel, which is the argument that settled `check: user`.

**THE LANDMINE: DEFUSED.** `_collect_parameter_references` read
criteria off `action_def` when they live per sub_write, and found
nothing. Now reads both levels, with tests and a control that
reinstates the original bug.

Demonstrated before fixing rather than assumed: given a criterion
holding `parameter.approver` in the real shape, the collector returned
`{ticket_id}`; given the same criterion in the shape it was looking at,
`{ticket_id, approver}`.

The damage it would have done is the bad kind. A parameter used ONLY by
a criterion gets reported declared-but-unused, so an author deletes the
declaration on the validator's advice and breaks the criterion. A
validator that tells you to remove something load-bearing is worse than
one that says nothing.

**Eligibility: MOVED.** `pop()` became `claim(write_id, may_claim)`,
with the predicate running UNDER THE STORE'S LOCK -- a caller that
looked up, decided, then popped would leave a window where two
approvers both claim one write. Policy is the route's (the grant);
atomicity stays the store's.

Uniform denial is preserved by construction: unknown id, expired id and
ineligible caller all return None and the caller cannot tell which.

The widening is deliberate and the opposite policy is now EXPRESSIBLE
rather than hardcoded -- a criterion of `operator: equals, value:
proposer.user_id` restores owner-only confirmation for a deployment
that wants it.

**Still open:** the decision is audited as an ordinary write, not as an
approval naming BOTH parties. An approvals inbox wants "bob approved
alice's write" as a first-class entry.

## A deliberate security pass over the agent loop

Three security items sit in ROADMAP.md unaddressed, and the pattern
that produced them is the reason to schedule this: every one came from
noticing something sideways while chasing an unrelated problem, and one
of the three came from the user rather than from any audit.

**As a read, not a task list.** Trace one query end to end and ask at
each boundary: where is the authorization decision made, what is it
made AGAINST, and how stale can that be? That framing is what surfaced
the per-query snapshot, and it generalises.

**Specific things to check, none confirmed, all cheap to answer:**

- Does disabling a user invalidate existing SESSIONS, or only block new
  requests? `is_user_disabled` is checked when a request resolves its
  UserRecord. If a session outlives that check, the exposure window is
  not one query but one token lifetime. `session_store` has not been
  read.
- Can `--context-shift` evict the system prompt mid-query, and what
  does the model do then? The guardrails are at the FRONT of the
  prompt, which is what gets discarded first. Not a security boundary
  -- the mediator enforces regardless -- but the failure would look
  like the model forgetting the rules, and nobody has tried it.
- Does any error message leak a field name the acting user cannot read?
  Uniform denial is enforced on DATA; error text is a separate surface
  and has never been audited as one.

**Deliberately not part of it: fixing everything found.** A pass that
produces recorded findings with reproductions is worth more than one
that produces a scattering of partial fixes and no map.

Confidence: high on the method, none on what it finds, which is the
point.

## Do the pre-flight action verdicts earn their keep?

Unresolved from the caching work, and the honest answer is that there
is no evidence either way.

`_sub_write_validity_for_object` annotates whether an action is
currently valid for objects already read. It costs prompt tokens on
every hop and was, until recently, invalidating the cached prefix. The
loop ALREADY recovers from a rejected action without it:
SubmissionCriteriaViolation is caught on its own budget and fed back as
"That action is not currently allowed ... try a different action."
That is the industry pattern -- MCP treats tool availability as dynamic
and failure-driven.

**Why the traces so far prove nothing.** Both were read-only queries
that were never going to write. The verdicts fired and were ignored,
but the mechanism was not under test. Deciding from that would repeat
the mistake of ranking models on a benchmark that did not measure the
thing that mattered.

**The measurement:** log when the verdict returns `(False, ...)`, and
separately whether the agent then avoided proposing that action. Run a
handful of write-intent queries against objects in states that BLOCK
the action. If the verdicts stop doomed proposals, they stay. If the
agent proposes anyway, they are paying tokens for nothing and the
recovery path is doing the real work.

Confidence: high that it is measurable, genuinely open on the answer.

## Which local model, and a recorded failure that predates the fix

A benchmark against the REAL 1,113-token system prompt, five installed
models, two runs each, scoring validity through the loop's own
`next_step()`:

    qwen2.5:3b                  86.4s   2/2   in 8.0 t/s   out 3.55
    phi4-mini                  116.9s   2/2   in 5.9 t/s   out 2.64
    qwen3.5:2b                 122.4s   2/2   in 5.9 t/s   out 2.52
    Mellum2-12B-A2.5B          182.2s   2/2   in 4.4 t/s   out 3.44
    qwen3:4b-instruct          187.7s   2/2   in 3.9 t/s   out 1.09

qwen2.5:3b is 36% faster on PREFILL, which is the axis that matters --
a ~1,100-token prompt re-read per hop dominates everything.

**THE REASON THIS IS NOT ALREADY DECIDED.** deployment/etc/config.yaml
records that qwen2.5:3b was tried as the step model before and reverted
"after it got stuck repeating its first step in every test case, even
with recovery mechanisms in place." The fastest model here has a
recorded history of failing across HOPS -- and this benchmark tests
exactly one step from an empty gathered, the case where that failure
cannot appear.

The benchmark cannot make this call. It was not built to.

**What might have changed since that reversion**, and why the old
result may not hold: the action verdicts moved out of the middle of the
system prompt, `object_ids` batching landed, and duplicate detection
now records a signature per object per field rather than one per set.
The prompt qwen2.5:3b failed against is not the prompt it would see.

**RESOLVED: phi4-mini stays.** The multi-hop run was done and
qwen2.5:3b failed it, reproducing exactly the behaviour the config note
warned about. In one query it emitted the same invalid step it had
already been corrected on, then repeated it until duplicate detection
stopped the run -- eight steps, 643 seconds, NO ANSWER. phi4-mini
answered the same question in 443 seconds.

It also did not use the `object_ids` batching phi4-mini adopted on
first exposure, spending two hops on two amounts where one would do.

The hypothesis that the changed prompt might have rescued it -- the
action verdicts moved, batching added, duplicate detection tightened --
was wrong. Faster per token, worse at everything that decides whether a
query completes.

One thing it did BETTER, worth keeping in view: it reached for
`aggregate_object` at all, which phi4-mini never did in any recorded
trace. The aggregate-selection weakness above may be worse on the model
that won.

**Two things the benchmark could not see, worth stating so nobody
over-reads it.** Every model scored 2/2 valid, so correctness did not
discriminate at all -- one question from an empty state is the easiest
possible step. And with two runs, the median is the mean of a COLD and
a WARM call, so "86.4s" is not a number anyone experiences; the cold
prefill alone is ~150s.

**Mellum's premise did not hold.** 12B total with ~2.5B active did not
buy prefill speed -- 4.4 t/s, second-worst -- and it pays 46 seconds to
load. Its generation is respectable, but generation is not the
bottleneck. Worth recording that the MoE theory was tested and failed
on this hardware, so nobody re-derives it.

## templates/config.yaml still teaches the two-model form

Small, and waiting on the item above. `templates/` is what a new
deployment copies, and it still names a `step_model`/`synthesis_model`
pair -- phi4-mini plus qwen2.5:3b -- so a new deployment would load TWO
models by default, paying an eviction between them on every query. That
is the exact cost `llm.model` was added to remove.

Not fixed yet only because the model choice is unresolved: writing a
default we are about to change would mean editing it twice. Update both
config files together once the multi-hop run decides.

## Should the adapter send think: false by default?

The benchmark sends `"think": false` and production does not. That gap
is currently harmless and would stop being harmless quietly.

**Why it matters.** Reasoning models emit a chain of thought before
answering. Measured on this deployment, asked to reply with one word:
phi4-mini 2 tokens, gemma4:e2b 84, qwen3.5:2b 370. At ~1.5 tokens/sec
generation, that difference is the whole story -- the model with the
better tokens/sec took six minutes and the worse one took under a
second. `--think=false` cut qwen3.5:2b from 370 tokens to 2.

None of the currently configured models reason, so nothing is being
paid today. But the moment someone configures one -- and the newest
small models increasingly reason by default -- they inherit a
several-hundred-token surprise per hop with nothing in the config
mentioning it.

**Three options, undecided.** Send it always from the adapter, on the
grounds that a step must parse as one JSON shape and deliberation
before that is never wanted here. Expose it as a connection option, on
the grounds that it is provider-specific and `llm_connection` is
deliberately opaque. Or leave it, and let a deployment that configures
a reasoning model discover the cost.

**The argument for sending it always** is the same one that makes the
caller's `temperature=0` win over a configured value: the step call has
a required output shape, and this is a property of the call rather than
a deployment preference. **The argument against** is that Ollama-
specific keys in the adapter are exactly what the options passthrough
exists to avoid, and `think` is not universal across providers.

Leaning toward always, with a comment saying why. Not urgent until a
reasoning model is actually configured -- but the cost of finding out
the hard way is a query that silently takes ten times longer.

## Domain neutrality: the engine is clean, the prompts are not

Asked directly -- does the ontology fully decouple from domain at its
core, with data passed in shaping it and the machinery staying neutral?
Audited rather than assumed.

**WHERE IT HOLDS, and it holds well.** FIELD_DATA_TYPES is string,
integer, number, boolean -- no `email`, no `currency`, no domain
semantics. MAC is fully parameterised: `security_attribute` is config
and the word `region` appears nowhere in core/. The step vocabulary is
shape-based rather than domain-based -- search_object, get_field,
get_object, aggregate_object, search_around all describe ontology
STRUCTURE. Actions, criteria, links and aggregates are defined entirely
by the schema a deployer writes.

Every apparent domain noun in core/ is a false positive: "account"
meaning a user account, "transaction" meaning a database transaction,
"customer" meaning the deploying organisation. The `status` and `name`
hits are protocol keys -- a write-log entry's status, a schema entry's
display-name key -- not ontology fields.

**WHERE IT BREAKS: the prompts.** And the two prompts break
differently, which is the distinction any fix should preserve.

**core/llm/agent_step_prompt.py, the few-shot examples.** They hardcode
Customer, Transaction, cust_001, email and amount. NOT OBVIOUSLY A
DEFECT: few-shot examples teach SHAPE, and a model generalises from a
Customer example to a Ship without much trouble. Generating them from
the deployer's real object types would arguably be worse -- brittle,
and it would mean composing examples rather than writing them.

Three real costs though. It is prefill paid on every hop describing a
domain that may not exist. A small model could plausibly treat
`Customer` as an available object type and spend a step on it -- the
mediator denies, but at ~190 seconds a wasted hop is expensive here.
And it is a coupling nobody declared.

**core/llm/synthesis_prompt.py, and this one IS a defect.** The rule
that "if the data contains transactions, treat those as the answer to
'recent transactions' rather than looking for a field named 'recent'"
is not an example -- it is DOMAIN LOGIC, a rule about what a particular
noun means, living in core/. A logistics deployment gets an instruction
about a noun its ontology does not contain, and gets no equivalent help
for its own. The underlying insight is generic -- a plural in the
question may name an object type rather than a field -- but it has been
written domain-specifically.

**The fix, and the split.** Generalise the synthesis rule: same
guidance, no noun. Small and clearly correct, so do it whenever.

Leave the step-prompt examples until the measurement session. They
interact directly with the over-fetching and missed-aggregate entries
above -- all three are questions about what the prompt teaches, and the
same one-shot harness answers all of them. Replacing them blind would
be exactly the prompt-editing-before-measuring this file argues
against.

Confidence: high that the engine is neutral, high that the synthesis
rule should change, genuinely open on the examples.

**THE FRONTEND WAS NOT AUDITED.** This finding covers core/, adapters/
and api/ only. ui/ has never been checked with the same question, and
domain neutrality is not a property this project can claim end to end
until it has been.

No reason to expect a problem -- UI_ROADMAP.md describes per-object-type
icons and display names coming from the schema, which sounds neutral --
but "sounds neutral" is what was assumed about core/ before the prompts
turned up. The specific things to look for: a React component
switching on a particular object type name, a hardcoded field name in a
formatter or column definition, or a default that assumes a field like
`name` or `status` exists.

Same scan that was run against core/ would do it, and it costs
minutes.

## aggregate_object and search_around are UNREACHABLE

Found while auditing what the LLM decides versus what Python decides.
This is a bug, not an idea, and it should probably graduate straight to
a fix.

AgentLoop._step_handlers() registers seven step types, including
`aggregate_object` and `search_around`. next_step()'s validation in
core/llm/agent_step_prompt.py has branches for `finish`,
`search_object`, `get_field`, `get_object`, `use_tool` and
`propose_action` -- and nothing else. An unmatched step hits:

    logger.warning(f"unrecognized step {step!r}, finishing")
    return _finish_step()

So a model emitting `{"step": "aggregate_object", ...}` has it silently
converted into a finish. Both handlers are dead code reachable only
from tests that call them directly.

**THIS REWRITES THE "AGGREGATES ARE NOT BEING CHOSEN" ENTRY ABOVE.**
That entry speculates about wording and position and proposes a
measurement session. The real explanation may be simply that the
prompt teaches a vocabulary the parser rejects -- the model may have
tried, been turned into a finish, and looked like it ignored the
guidance. Do not run that measurement until this is fixed; it would
measure the wrong thing.

It also explains the hand-rolled link traversal in the trace:
`get_field("transactions")` returning [1, 2] followed by reads of each.
`search_around` exists for exactly that and cannot be reached.

**Two things not established, and worth checking rather than
assuming.** Whether the `logger.warning` actually fired during the
recorded runs -- it is at WARNING level, so it would be in the server
log, and its absence would mean the model never tried. And which side
drifted: whether the handlers were added without validator branches or
the branches were removed.

**The missing gate is the real lesson.** Nothing asserts that every key
in `_step_handlers()` has a corresponding branch in `next_step()`. That
test is three lines and would have caught this the day it happened.
Whatever the fix, add it.

## What the LLM decides, and what Python already decides for it

Asked directly: should the LLM handle only open-ended questions, with
everything else delegated to Python, and is it currently handling
anything it should not?

**The split is mostly right already.** Python owns duplicate detection
(`_step_signature`), the asymmetry nudge at finish, `is_current_object`
parameter filling, the action-validity pre-flight, hop and mistake
budgets, and EVERY authorization decision. The model picks the next
step and writes prose.

**Where the model is doing mechanical work: link traversal.** The
recorded trace read `transactions` off a Customer to get [1, 2], then
read each one. The schema DECLARES that link -- Python knows
`transactions` points at Transaction. That is precisely what
`search_around` is for, and it is unreachable (above). This is the
clearest case of the model re-deriving something the schema already
answers.

**Where it is tempting but wrong to move work to Python:** routing on
question keywords, e.g. detecting "how many" and forcing an aggregate.
That is brittle NLP -- the next phrasing fails identically, and it puts
a second, worse language model in front of the real one. Make
`aggregate_object` reachable and re-measure before considering it.

**Where the model should stay:** deciding which object type a vague
question means, deciding when enough has been gathered, and synthesis.
Those are genuinely open-ended and have no mechanical answer.

## Does the LLM reading the schema escalate privilege?

Asked directly. Audited: **no**, and the reason is worth recording so
it is not re-litigated.

`DataMediator.visible_schema()` filters per user at BOTH levels -- an
object type appears only with `read:{object_type}`, a field only with
`read:{object_type}.{field_name}`, and `id_field` gets no special case
and needs its own grant. The model is shown exactly the acting user's
own view, which `/me/visible-schema` already returns to that user's
browser and the Schema app already renders.

The model also holds no authority of its own. Every step goes back
through the mediator against the HUMAN's UserRecord, so knowing a field
name buys nothing: `get_field` on an ungranted field is denied
identically whether the model read it in the prompt, guessed it, or
hallucinated it. PRINCIPLES.md section 4's "partial, adversarial trust"
is doing exactly its job, and nothing rests on the model not knowing
things.

## Should the schema be in the prompt at all?

The instinct behind the escalation question lands on something real one
layer over, and it is the largest open architectural question here.

The schema is MOST of the ~1,113-token prompt. Moving it out -- behind
a `describe_schema` step the model calls when it needs it -- would give
a tiny prompt, better cache behaviour, and genuine domain neutrality.
It is also by far the biggest available prefill saving, which makes it
tempting for the wrong reason.

**THE SECURITY INTERACTION, which pulls the other way.** The per-user
schema sitting at the HEAD of the prompt is currently the only thing
preventing cross-user prefix alignment: two users with different access
diverge within the first hundred tokens, so neither can align a probe
against the other. ROADMAP.md's KV-cache side-channel entry records
this and notes the defence is accidental.

Take the schema out and every user's prompt starts identically. The
shared alignable prefix goes from ~100 tokens to the entire instruction
block -- precisely the condition PROMPTPEEK and InputSnatch need. The
change that improves domain neutrality DEGRADES cache isolation.

Not fatal. If the schema moves out, something user-specific has to stay
at the head, or cross-request cache reuse has to be disabled. But it
must be decided deliberately rather than discovered afterwards.

**The other risk, and it is not small:** a 3.8B model would have to
call `describe_schema`, hold the result across hops, and not
re-request it. The model in the recorded trace already re-fetched
fields it had. Measurable in the same one-shot session as the other
prompt questions -- but only after the unreachable-step bug is fixed.

**Keep these three separate**, because they have been sitting under one
label and only one has a security dimension: generic few-shot examples
(prompt quality), the synthesis domain rule (a small clear defect), and
whether the schema belongs in the prompt at all (architecture, with a
real security interaction, and the largest of the three).

## Calibration probes: what else can drift the way the steps did

The unreachable-step bug has a general shape worth naming, because the
fix for one instance is worthless and the fix for the class is cheap. A
REGISTRY and its CONSUMER declared in different files, with nothing
asserting they agree. Both sides were individually tested. The pair was
not.

**The probes worth adding, in rough order of what they would catch:**

- **Three-way step consistency.** Every key in
  `AgentLoop._step_handlers()` has a branch in `next_step()`, AND every
  step name the PROMPT teaches has both. Three sources, currently
  agreeing on four of six. The prompt is the third leg and the one
  nobody thinks of -- teaching a vocabulary the parser rejects is
  exactly what happened.
- **Adapter registries.** `_READ_ADAPTER_REGISTRY`,
  `_WRITE_ADAPTER_REGISTRY` and `_LLM_ADAPTER_REGISTRY` in
  deployment_loader.py are hardcoded dicts. An adapter class that
  exists but is not registered is invisible; a registry key nothing
  implements fails only when a deployment names it. Assert every
  adapter module's class appears in exactly one registry.
- **Every shipped config key is actually read.** Walk
  templates/config.yaml and deployment/etc/config.yaml, assert every
  key is consumed by deployment_loader. This catches a documented key
  that silently does nothing -- a live risk now that
  `llm.connection.options` is an opaque passthrough where a typo like
  `num_threads` for `num_thread` is accepted and ignored by Ollama.
  The passthrough's own contents cannot be validated, but the keys
  AROUND it can.
- **Every grant verb in code appears in README's grant table**, and
  vice versa. `read:`, `execute:`, `discover:action_types`,
  `manage:users` are a vocabulary a deployer must get exactly right,
  and the table is how they learn it.
- **Every vulture whitelist entry is still needed.** Entries outlive
  the code that justified them, and a stale one silently permits real
  dead code later.

**The general test, if one is wanted instead of five:** for each
registry, assert `set(registry) == set(consumer)`. It is the same three
lines each time.

**What makes these different from ordinary tests.** They assert nothing
about behaviour -- they assert that two declarations agree. That is
precisely the class of bug unit tests cannot catch, because each side
passes its own tests. Cheap, fast, and they fail the day the drift
happens rather than the day a user hits it.

## An admin view of live performance metrics

Proposed directly, and the right design criterion is unusually clear:
**instrument the failure modes this project actually hit**, not the
metrics a dashboard usually shows. Every question that cost real time
this week has a number that would have answered it instantly.

**What it should show, each tied to a question that was genuinely
hard:**

- **Rejected step names, counted.** `next_step()` already logs
  "unrecognized step {step!r}, finishing" at WARNING. A counter would
  have read `aggregate_object: 47` and the unreachable-step bug would
  have been found in a glance rather than by a code audit. THIS IS THE
  STRONGEST ARGUMENT FOR THE WHOLE FEATURE.
- **Per-call model durations within a query**, as a series. First call
  against later calls IS the prefix-cache indicator -- the 8.8x ratio
  in the last trace is what proved the prompt split worked. A live
  version would show a cache regression the day it appears.
- **Step-type distribution.** Are aggregates ever chosen? Is
  `search_around` used, or are links traversed by hand? This directly
  answers two open entries above.
- **Gathered entries per query against hops used.** The over-fetching
  measure: six entries from five calls is fine, six entries where two
  were never needed is not.
- **Hops used against max_hops**, and the three mistake counters
  (duplicate, invalid, business-rule). A model looping shows here
  first, which is exactly the qwen2.5:3b risk.

**Where the data would come from, and this is the real work.** Nothing
query-level is persisted today. AuditLog has `log_pre`/`log_post`
around writes with a `request_id`, but no timing, and scripts/
agent_trace.py measures in-process and throws it away.

**DECIDED: a separate store from the audit log.** Not a preference --
the two records have opposite properties in four ways, and merging them
would mean one of the two gets the wrong behaviour:

- **Opposite failure semantics.** The audit log fails CLOSED: if an
  access cannot be recorded, the access should not happen, because an
  unrecorded access is exactly what the log exists to prevent. Metrics
  must fail OPEN: telemetry must never break a query. A store cannot do
  both, and putting metrics behind audit's semantics would let a full
  disk stop the product for the sake of a dashboard.
- **Opposite retention.** The audit log is a security record and is
  kept. Metrics can be summarised, downsampled and deleted, and should
  be -- a per-hop timing series grows fast and is worthless after a
  release.
- **Opposite content rules.** The audit log MUST hold query_text; the
  metrics store must never contain it (see security, below). One store
  with a column that is mandatory for one reader and forbidden for
  another is a rule nobody will hold.
- **Opposite mutability.** Audit entries are append-only. Metrics are
  naturally aggregated in place -- counters incremented, series rolled
  up -- which is a schema shape the audit log should not learn.

Practically: its own SQLite file in data_dir, alongside write_log.db
and credentials.db, following the pattern already established rather
than inventing a new one. Writes must be cheap enough to sit in the
request path, or moved off it -- but "cheap enough" should be measured
on the CPU-only deployment, where everything is slower than it looks.

**SECURITY, and it is not an afterthought here.** Metrics are the first
cross-user surface this project would have. Three specific concerns:

- **Query text must never appear.** `log_pre` stores it today for the
  audit trail. A metrics view must project timings and counts ONLY --
  another user's question is potentially as sensitive as the data it
  returns.
- **Per-user attribution is a surveillance surface.** "Who ran how many
  queries" is a different product from "how fast is the loop". Default
  to aggregate; if per-user is ever wanted, it needs its own grant and
  its own argument.
- **MAC does not apply.** Metrics are not ontology objects, so the
  per-object boundary that protects everything else is simply absent.
  RBAC is the only gate, which makes it a new CATEGORY of thing rather
  than another screen -- worth stating plainly before it is built.

**Fit.** The admin app already has AdminPanel, DeploymentConfig and
Silos, so a fourth view is not a new app. UI_ROADMAP.md's build order
should decide where it sits -- it is developer-facing, which is
unusual for this product, and that may be an argument for keeping it
behind a flag rather than shipping it to operators.

**Cheapest useful subset, if the full thing is too much:** the rejected
step counter alone, exposed as a number. It needs no store, no graph
and no new screen -- a process-lifetime counter on an existing admin
endpoint would have caught the bug that prompted this entry.

## Host metrics, correlated with hops -- NOT a resource analyzer

Proposed as IO, RAM, per-CPU and per-thread activity in the style of a
system resource analyzer. Worth doing, but narrowly, and the
distinction matters more than it sounds.

**WHY NOT A RESOURCE ANALYZER.** htop, glances, node_exporter and
Grafana already do per-CPU, IO and memory better than this project
would, need no building, and an operator running Elysium next to a
production database almost certainly already has one. Rebuilding that
inside the app is a large surface -- sampling, storage, charts -- for
something already solved.

**WHAT NO EXTERNAL TOOL CAN DO** is correlate host state with AGENT
state, because nothing outside Elysium knows what a hop is. "CPU at
80%" is not useful. "This hop's prefill ran at 2.1 tokens/sec instead
of the usual 5.9, and the machine was swapping at the time" is, and it
is unobtainable from any general tool.

So: sample a handful of host numbers AT HOP BOUNDARIES and attach them
to the hop's own metric row. The unit is the hop, not the second.

**The specific questions this would have answered this week**, which is
the test of whether it earns its place:

- **Is llama.cpp using both cores?** An early hypothesis, never
  confirmed -- `journalctl -u ollama` came back empty and the thread
  count was inferred from the absence of a `--threads` flag. Per-CPU
  utilisation during a hop answers it directly. If prefill is running
  on one core, that is a 2x fix sitting untouched.
- **Was the machine swapping?** 16GB, with an 8.1GB model (Mellum) and
  a 2.5GB one both potentially resident. Swap during prefill would
  destroy throughput and look exactly like a slow model. Days were
  spent on model choice; if swap was ever involved, that was the wrong
  investigation entirely.
- **Did another process steal the cores?** With 2 vCPUs, uvicorn, the
  benchmark and ollama contend directly. A benchmark run alongside an
  agent_trace would corrupt both, and nothing would say so.
- **Is the model still resident?** `keep_alive: -1` was set and its
  effect inferred from call 2 being 10x faster than call 1. A resident
  check confirms it rather than inferring it.

**Design constraints, each for a reason:**

- **Sample at hop boundaries, synchronously, never on a timer.** A
  background sampling thread is a new concurrency surface in a project
  that is careful about those, and it would sample points nobody can
  correlate to anything. Hop boundaries are already interesting moments
  and the code is already there.
- **Read /proc directly rather than adding psutil.** /proc/stat,
  /proc/meminfo and /proc/<pid>/status give per-CPU jiffies, swap
  in/out and process RSS with no dependency at all. Linux-only, which
  the deployment already is -- INSTALL.md targets Debian and ships a
  systemd unit.
- **Deltas, not absolutes.** Swap pages in/out BETWEEN hop start and
  end is the signal; total swap used is not.
- **It must cost microseconds.** Reading four /proc files per hop is
  fine. Anything that needs a subprocess is not.

**Security.** Host metrics are not user data, so the per-object
boundary is irrelevant -- but they are infrastructure disclosure:
process names, memory sizes, core counts, and by inference what else
runs on the machine. Same RBAC gate as the rest of the metrics view,
and the same reason it is a new CATEGORY rather than another screen.

**Honest doubt.** This is diagnostic tooling for a deployment whose
performance problems may be temporary. If the VM gets more cores, most
of the questions above stop mattering and this becomes maintenance
nobody reads. The counter-argument is that "the box is slow" will
recur on any CPU-only deployment, and the correlation is the only way
to tell a slow MODEL from a slow MACHINE -- a distinction this project
got wrong once already.

## What Foundry users are asking for, and what it means here

Researched directly in Palantir's developer community and issue
tracker. Their users have hit problems this project has not reached
yet, which makes their feature requests a cheap source of validated
need -- someone else already discovered which gaps hurt.

**Ordered by how well they fit, not by how loud the request is.**

### Shared, reusable submission criteria -- the best fit

A direct product-feedback request: when setting up actions, submission
criteria become complex, "especially when being deployed to support
multiple actions for a specific use case. Right now, user would have to
enter the same submission criteria for X actions." They ask at minimum
for cloning, and ideally for defining a criteria set once and
referencing it.

**This lands squarely on work just finished.** Criteria live per
sub_write in ontology_schema.yaml, so a deployment with five actions
guarded by the same rule writes it five times -- and the five copies
drift. A named criteria block referenced by name is a small YAML
change with a validated need behind it.

Worth pairing with the check already recorded above: nothing validates
that a `current_state` criterion's field is real. Duplicated criteria
multiply that exposure by five.

### "Why can this user see X" -- permissions explainability

Foundry ships a Security tab showing "the required permissions to view
and edit an object type, and the required permissions to see instances
or run actions." Separately, a community request asks for a way to test
whether a given user plus a given parameter set satisfies an action's
submission criteria, noting it gets cumbersome once permissions depend
on group memberships AND object properties together.

**Elysium needs this MORE than Foundry does, because of uniform
denial.** An unknown object type and a forbidden one are deliberately
indistinguishable, which is right for the user and brutal for whoever
configured the deployment: "alice cannot see Transaction" has at least
four causes -- no `read:Transaction`, no field grants, a MAC mismatch,
or a typo in policy.yaml -- and the product is designed to tell them
apart for nobody.

An ADMIN-ONLY explainer -- given a user and an object type, show which
grant is missing or which MAC value mismatched -- would close that. It
must be admin-only and deliberately so: it is the exact inverse of
uniform denial, and exposing it to ordinary users would undo the
property on purpose.

Not present today. Checked.

### Action revert

Foundry supports undoing an action immediately after it is applied,
with real limits: only by the user who applied it, only for their newer
storage, and toggled per action type. Their docs are also blunt that
there is otherwise "no mechanism to directly undo a single user edit."

Elysium has a write_log recording every applied write with before and
after values, so the DATA to revert exists -- but no revert path does.
Checked.

**The interesting question is whose authority a revert runs under**,
and it is the same question the approvals work just answered for
elevation: a revert is a new write, so it should pass RBAC, MAC and
criteria as itself rather than inheriting the original's permission.
Foundry's "only the user who applied it" rule is one answer; ours could
be better, since an approvals inbox makes "someone else reverts it"
coherent.

### Bulk approve in the approvals inbox

Foundry's proposals UI lets a reviewer "approve or reject tasks on a
task-level, or in bulk for all eligible tasks", with per-task comments.

Worth recording for the inbox design, but with a caution: bulk approve
is where four-eyes quietly becomes rubber-stamping. If it exists, the
audit record must distinguish a bulk approval from an individual one,
or the trail says something it does not mean.

### Infrastructure-as-code -- ALREADY WON, do not lose it

Their loudest structural complaint: object types, action types and link
types can only be created by clicking through the Ontology Manager UI,
which "prevents full automation of Foundry deployments." An open GitHub
issue and a community request both ask for it; a Palantir engineer said
endpoints were "in progress" in August 2025.

**Elysium has this by construction.** ontology_schema.yaml,
policy.yaml, data_silos.yaml and config.yaml ARE the ontology, in
version control, diffable, reviewable, and validated at load by
scripts/lint_deployment.py. There is no clicking path and no drift
between UI state and committed state.

Recorded not as work but as a property to protect. Any future admin UI
that EDITS the ontology rather than displaying it would trade this
away, and it would look like a feature while doing so.

### Runtime schema introspection -- also already won

A user building directly on the Foundry API rather than the generated
SDK, so they need not redeploy when the ontology changes, asks for
better runtime ontology metadata. `/me/visible-schema` is exactly that,
and it is per-user filtered as well.

## What current LLM research says that applies here

Surveyed 2026 work on agent security, structured output and inference
performance, filtered for direct applicability. Three findings, and one
of them REVERSES a recommendation made earlier in this file's own
history.

### Elysium has half of CaMeL, and the missing half is a risk class

CaMeL (Google DeepMind / ETH Zurich) is the architecturally sound
defence against indirect prompt injection, and the field has converged
on its shape: rather than training the model to refuse malicious
instructions, ENFORCE SECURITY OUTSIDE THE MODEL with a deterministic
policy mediating the agent's actions. CaMeL, FIDES, Progent, RTBAS and
FORGE all do this with capabilities, information-flow labels and
reference monitors.

**Elysium already has the reference monitor.** The mediator enforces
RBAC and MAC deterministically on every call, outside the model.
PRINCIPLES.md section 4 states this principle, arrived at
independently and before the literature converged on it.

**What is MISSING is CaMeL's other half: separating control flow from
data flow.** In CaMeL a privileged LLM plans from the TRUSTED query
while a quarantined LLM reads untrusted data WITHOUT tool access, so
retrieved content can never influence which action is taken. Here,
`gathered` -- real ontology data -- enters the same prompt as the
instructions, and the same model picks the next step. Untrusted data
CAN steer program flow.

**THIS EXPOSES A RISK CLASS THIS FILE HAD WRONG.** The existing
auto_execute entry argues the blast radius is bounded by three gates:
the execute: grant, per-sub_write MAC, and a human at confirm. That is
true FOR WRITES. It says nothing about the READ path, where there are
no gates of that kind, because reading is what the user is allowed to
do anyway.

An injected field value can steer which objects get read, and -- more
seriously -- shape what SYNTHESIS TELLS THE USER. RBAC and MAC protect
against unauthorised access. They do not protect against being LIED
TO. A malicious string in a customer record could make the answer
state something false, entirely within the acting user's own
permissions, with every authorization check passing correctly.

Not a sharper version of a recorded risk. A different one.

**What is worth considering, and what is not.** Full CaMeL -- dual
models, a custom interpreter, capability metadata per value -- is far
too heavy for a deployment that cannot afford ONE model. But the cheap
part may be the valuable part: mark which parts of the prompt came
from ontology data rather than from the schema or the question, and
treat synthesis output derived from marked values with more suspicion.
Even just recording it would make an injection visible after the fact,
which is currently impossible.

### Constrained decoding: the earlier recommendation was wrong

An earlier doubt in this file suggested passing a JSON SCHEMA to
Ollama's `format` (rather than the current `"json"`), so a smaller,
faster model could not emit malformed steps. The 2026 literature says
that trade is considerably worse than presented.

Measured: hard schema decoding raises schema validity from 61.5% to
100%, but LOWERS answer accuracy from 19.7% to 11.0% and raises
wrong-but-valid outputs from 49.5% to 88.9%. In a calendar tool-call
analogue, prompt-only JSON reached 91.5% executable accuracy while the
same hard tool-call schema reached 48.0% -- both 100% schema-valid.
The error moves from STRUCTURAL to SEMANTIC, which is strictly worse
here: a malformed step is caught by next_step() and retried, while a
well-formed step that means the wrong thing is executed.

There is a documented "constraint tax" at the 3B boundary --
precisely this deployment's size class -- and a 3.6x to 8.2x latency
overhead, which on CPU-only hardware is disqualifying by itself.

The recommended pattern is "reason free, constrain late". The useful
discipline for us is separate metrics: schema validity, answer
accuracy, executable accuracy and wrong-valid rate reported
INDEPENDENTLY. The model benchmark run in this session collapsed all
of that into one `valid` column, where every model scored 2/2 and the
column discriminated nothing.

### Small-model structured output is a named problem with a known fix

Naive prompting reaches up to 85% task accuracy but 0% OUTPUT accuracy
across all models and datasets tested; a minimal hand-written JSON
format prompt still yields 0% for two of four models. The intervention
that worked was ITERATIVE SYSTEM-PROMPT OPTIMISATION, reaching 84-87%
output accuracy at near-baseline latency, without fine-tuning and
without constrained decoding.

Directly encouraging for the measurement session already planned: for
models this size, prompt iteration is the high-leverage lever, and
constraint machinery is not. It also suggests the session should
optimise iteratively rather than test three hand-written variants
once.

### Noted and NOT applicable

Speculative decoding, the 2026 default for large open-weight serving,
needs a draft model meaningfully weaker than the target. At under 7B,
target and draft are too close in capability for it to pay. Recorded
so nobody re-derives it.

Engine-level prefix caching (RadixAttention in SGLang, structured
decoding in vLLM) is real and relevant in shape, but both target GPU
serving. llama.cpp's single-slot prefix reuse is what this deployment
has, and it is already working -- measured at an 8.8x first-call to
later-call ratio.

## Is SQLite running in WAL mode, and should it be?

Surfaced by a question about readers-writer locks, and it is the one
place a genuine readers-writer problem exists in this system -- inside
SQLite rather than in our code.

`grep` finds NO `journal_mode` anywhere. SQLite therefore defaults to
rollback journal, in which **a writer blocks all readers** for the
duration of its transaction. WAL mode removes that: readers proceed
against the last committed state while a writer works. It is SQLite's
own implementation of the MVCC property Iceberg already gives the
mirror for free.

**Not obviously a bug, and possibly deliberate.** WAL does not work
over network filesystems and creates extra files a backup has to
account for. The write path is already serialised per object, so
contention may be low in practice. But no comment records it as a
decision anywhere, which usually means it is a default rather than a
choice -- and this project's habit is to state why a default was kept.

**Measure before changing.** Whether reads actually block during a
write on a real deployment is answerable with a test that holds a
write transaction open and times a concurrent read. Changing journal
mode blind, on the store holding credentials and the write log, is not
the shape of change this project makes.

Independent of hot-reloading, and of the PostgreSQL question, which
ROADMAP.md has already settled: Postgres does solve concurrent writes
better -- true row-level MVCC where SQLite allows one writer
database-wide even in WAL -- but the recorded position is that neither
justifying condition has been MEASURED because neither exists yet. WAL
is a one-line change to databases we already have; Postgres is a
migration. They are not the same question.

---

## Suggested order

**Blocking everything below it:**

00. **aggregate_object and search_around are unreachable.** A bug, not
    an idea. It likely explains the missed aggregates AND the
    hand-rolled link traversal, which means the prompt-quality
    measurement session would measure the wrong thing until it is
    fixed. Add the three-way consistency probe with it -- handlers,
    validator branches, and the step names the PROMPT teaches -- since
    fixing one instance of a drift class is worth much less than
    catching the class.

**RESOLVED, no longer blocking:**

0. ~~The model decision.~~ Done. phi4-mini stays; qwen2.5:3b
   reproduced its recorded looping failure on a multi-hop run and
   never reached an answer. templates/config.yaml is unblocked.

**Then, in this order:**

1. **Approvals step 3.** The only product work here. Everything else on
   this list came out of a performance detour whose purpose was making
   this testable.
2. **The security pass.** The findings pattern is the signal: three
   items, all found sideways, one of them by the user rather than by
   any audit.
3. **The prompt-quality items as ONE measurement session** -- the
   over-fetching, the missed aggregates, the pre-flight verdicts, and
   whether a small model can work without the schema in the prompt.
   ONLY after item 00: three of the four would measure the wrong thing
   while aggregate_object and search_around are unreachable.
   They share a harness (one-shot calls against the real prompt,
   varying one thing at a time), so together they cost about an hour of
   machine time and answer all three.

   **Two changes to how this session should run**, both from the 2026
   research above. ITERATE rather than testing three hand-written
   variants once -- iterative system-prompt optimisation took small
   models from 0% output accuracy to 84-87% at near-baseline latency,
   which is the single highest-leverage intervention documented for
   this size class. And report FOUR metrics separately -- schema
   validity, answer accuracy, executable accuracy, wrong-valid rate --
   rather than the single `valid` column the model benchmark used,
   where every model scored 2/2 and the column discriminated
   nothing.

**Fold into work already scheduled, rather than scheduling
separately.** Each of these is cheaper done alongside its neighbour
than as its own piece of work:

- **Shared/named submission criteria** -- with approvals step 3, which
  is already editing the criteria vocabulary. Validated by a real
  Foundry product-feedback request, and the duplication it removes
  multiplies the unvalidated-field exposure recorded above.
- **Bulk approve, and how the audit records it** -- with the approvals
  inbox design, not after it. Retrofitting "was this approved
  individually or in bulk" onto an existing audit schema is worse than
  deciding it once.
- **Permissions explainability, admin-only** -- with the security
  pass, which is already reasoning about where each authorization
  decision is made and against what. The explainer is that reasoning
  made visible.

**Its own piece of work, unscheduled:**

- **Action revert.** The write log already holds before-and-after
  values, so the data exists; the design question is whose authority a
  revert runs under, and that answer should follow elevation rather
  than precede it.
- **Counting across a link in one step.** Two routes to the same
  answer today, one refused, and the refused one matches how the
  question is naturally phrased -- which a model demonstrated three
  times in a single run. Needs the MAC question answered first:
  counting linked objects must count only those the caller may see, or
  the count itself leaks.
- **Marking which prompt content came from ontology data.** The cheap
  half of CaMeL's control/data separation. Full CaMeL is far too heavy
  here, but recording provenance within the prompt would make an
  injection visible after the fact, which is currently impossible.
  Belongs with the security pass if that happens first.
- **The metrics store and admin view**, including host metrics
  correlated at hop boundaries. Largest of the unscheduled items, and
  the only one that introduces a genuinely new category -- a
  cross-user surface with no MAC boundary. Its cheapest useful subset
  (a rejected-step-name counter) could be done today and would have
  caught item 00.

**Cheap and independent, do whenever:** the ui/ domain-neutrality scan,
which costs minutes and either closes that question or opens a new one,
templates/config.yaml once the model is chosen, the `think: false`
decision, which needs no measurement -- only a choice between three
stated options -- and generalising synthesis_prompt.py's
domain-specific rule, which is the one domain-neutrality finding that
does not need a measurement first.

**CLOSED -- decided against, do not revisit without new evidence.** A
list that only ever grows is a list nobody reads, and both of these
look like obvious wins to anyone who has not read the measurements:

- **Passing a JSON schema to Ollama's `format` for constrained
  decoding.** Proposed earlier in this file and now withdrawn. Hard
  schema decoding takes schema validity to 100% but halves answer
  accuracy and nearly doubles wrong-but-valid outputs -- moving the
  error from structural to semantic, which is strictly worse here,
  because a malformed step is caught and retried while a well-formed
  wrong one is executed. There is a documented constraint tax at
  exactly the 3B boundary, plus a 3.6x-8.2x latency overhead that
  settles it alone on this hardware. Revisit only if the deployment
  leaves CPU-only inference, or if wrong-valid rate is ever measured
  here and comes out low.
- **Speculative decoding.** The 2026 default for large open-weight
  serving, and inapplicable below ~7B: target and draft are too close
  in capability to pay for themselves.
- **Depending on pyiceberg `main` for `fast_forward_branch`.** Asked
  directly -- why not just upgrade? Because there is nothing to
  upgrade TO. 0.12.0 is the latest RELEASE and is what we already run;
  `ManageSnapshots.fast_forward_branch` merged to pyiceberg's main on
  10 September 2026 and has shipped in no release. Getting it means a
  git dependency.

  **The cost is specific, not general caution.** requirements.lock
  installs with `--require-hashes`, and a git dependency has no PyPI
  artifact to hash -- so it means abandoning hash-pinning for that
  package or for the whole file. The lock's own preamble says why that
  matters: a pinned version still fetches whatever PyPI serves under
  that name, while a hash fails the install if the artifact changed,
  and Elysium runs next to a customer's databases where a compromised
  transitive package is a real threat.

  **AND WE DO NOT NEED IT, which is the stronger half.** The
  generation-swap design in HOT_RELOAD_PLAN.md step 5 is not a
  workaround for the missing method -- it is better than the method.
  Publishing via a config generation is ONE atomic swap covering both
  the ontology definition and the data snapshot. Fast-forward would
  move only the data half, leaving the definition half to a generation
  swap anyway: two publish mechanisms, and a window where they
  disagree. The design would stay the same with the feature in hand.

  **Revisit when**, and these are different triggers. (1) A release
  carrying it ships -- then it is an ordinary version bump with a hash
  and no principle traded, worth re-reading this entry but probably
  not worth changing anything. (2) THE REAL ONE: if sync ever stops
  being a full `overwrite()` and becomes incremental. Merging a
  backfill branch into main is a genuine operation that generation
  swapping does not express well, and that is the case where branch
  merge semantics start earning their keep.

  Note that `pyiceberg[sql-sqlite,pyarrow]<1.0` in requirements.txt
  means a 0.13 would be adopted automatically on the next lock
  regeneration. That is the right posture for a pre-1.0 library only
  because regenerating the lock is a deliberate, separately reviewable
  commit gated by scripts/check_lockfiles.py -- not because loose
  pinning is safe in itself.

**NOT work, but a property to protect.** Infrastructure-as-code and
runtime schema introspection are both things Foundry users are actively
asking Palantir for and Elysium already has. Neither needs doing.
Both are losable -- an admin UI that EDITS the ontology rather than
displaying it would trade the first away while looking like a feature.
Recorded here so that the next admin-screen proposal is weighed against
it.

**What to resist:** editing the prompt before that measurement session.
There are two traces, one question, and one model behind every
prompt-quality observation above. That is the thinnest evidence base
any decision this week has rested on, and two decisions made from
exactly that position were wrong -- recommending two reasoning models
on a benchmark that measured tokens/sec without measuring tokens, and
calling a caching hypothesis a hardware wall before instrumenting
anything.
