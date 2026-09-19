# What Query should contain — a plan

**The problem**: Query is a text box, an answer, a trace, and sometimes
a pending-write card. Someone opening it for the first time has no
idea what they may ask, and someone who has asked once has no way to
ask *nearly the same thing again*.

Neither gap is ours alone, and both have established answers.

---

## What the research says

**INPUT DISCOVERABILITY IS THE KNOWN, NAMED PROBLEM.** The Snowy paper
puts it plainly: it "has been a long standing challenge for NLIs", and
the established response is "adaptive NL command discovery interfaces
that incrementally expose users to the system features through
contextual suggestions".

Not a help page. Suggestions *beside the results*, "intended to be
used as follow-on queries or reformulations of the present search
query".

**READ THE QUESTION BACK.** A patent on multimodal feedback for
natural-language enquiries states the reason better than I would:

> it is useful for the machine that understands the enquiry to read
> back the understood enquiry to the user in the way the machine
> understood it, perhaps phrased more precisely but also to allow the
> user to correct just one element that perhaps the machine
> misunderstood.

**REFINEMENT IS THE COMMON CASE, not the exception.** The same source:
"if the user is following a train of thought, common in analytics and
hypothesis testing, then the user's next enquiry may be derived from
or only slightly changed from the original" — the example given is
"Okay now show me this for last quarter".

**AMBIGUITY IS WORTH DETECTING.** Enterprise assistants classify a
question as CLEAR or VAGUE before answering, and rewrite or ask rather
than guessing. That is a real technique and a real cost — an extra
model call per question — and it is the one idea here I would defer.

---

## What Elysium already has, and does not use

`deployment/etc/example_queries.yaml` lists real questions against the
real fixture data. **Nothing in the web UI reads it.** It is loaded
only by `scripts/run_deployment.py`.

Its own header says why: "Demo queries for scripts/run_deployment.py",
each paired with a `user_id` because the runner impersonates that
person. So it is not quite a UI affordance — but it is proof that a
deployment can and does state what good questions look like.

## DEFERRED: a starter question can leak what MAC hides

**THE PROBLEM, CONCRETELY.** The examples name specific ids:

    - user_id: user_alice
      query: "What are cust_001's recent transactions?"

Alice can see `cust_001`; Bob cannot. Showing Bob that example tells
him a customer called `cust_001` EXISTS. He cannot read it -- MAC
still refuses -- but he has learned it exists from a system built
specifically to refuse that. `get_field` on a hidden object returns
None, indistinguishable from "no such object", ON PURPOSE.

**THE `user_id` KEY DOES NOT SOLVE IT.** That is the deployment
author's assertion about who should see what, not something
`check_access` enforces. An author adding an example under the wrong
user, or a user's grants changing later, produces a quiet leak that
nothing detects.

**THE CATEGORY IS KNOWN AND THE FIX IS NOT STANDARDISED.** Power BI
states plainly that "RLS filters rows but does not hide the existence
of aggregated data... to completely hide the existence of data,
combine RLS with careful design of DAX measures" -- a mature product
saying row-level security alone cannot do this. The standard review
advice names the same shape: "check through slicers, drillthrough, and
bookmarks thoroughly to ensure that they're not leaking unauthorized
data."

Those are UI affordances that reveal existence, audited by practice
rather than prevented by mechanism. Nobody publishes a canonical fix
for suggested questions.

**THE SHAPE OF AN ANSWER, when this is picked up:** one file, two
sections. `examples:` keeps real ids for
`scripts/run_deployment.py`, which impersonates each user and needs
ids that resolve. A separate `starters:` list carries no ids at all --
"What are a customer's recent transactions?" -- because a starter's
job is to teach the SHAPE of a good question.

That also fixes a second problem: `cust_001` may not exist next month,
and a starter naming a deleted id is broken with nothing to notice.

---

`AnswerTrace` already shows the hops an answer took. That is more than
most systems offer and should stay.

---

## Proposed shape, in the order I would build it

### 1. Example questions, from the deployment

A deployment states what its data is good for; nobody else can. A
generic "Ask a question…" placeholder cannot say "ask about
transactions by category", and a hardcoded list in the UI would be
wrong for every deployment but ours.

**NOT by reusing example_queries.yaml as it stands.** Its entries are
user-paired for the runner, and showing someone a question about an
object they cannot see is worse than showing nothing. Either:

- a separate `ui_examples:` key in the same file, ungated and written
  to be answerable by anyone; or
- a `for_display: true` marker on entries that qualify.

The second is smaller and keeps one list. Either way the decision is a
deployment's to make, not the UI's to guess.

**MAC still applies to the ANSWER.** An example is a suggestion, not a
promise: asking it may legitimately return "no objects you can see".
That is correct behaviour and the example text must not imply
otherwise.

### 2. The question, read back

Elysium's agent resolves a question into hops over the ontology, and
`AnswerTrace` already shows them. What it does not show is what the
agent *understood the question to be*.

The value is correction: a person who sees "transactions, filtered by
category = travel, for customers in us-west" can spot the one wrong
clause and fix it, where a wrong answer alone tells them only that
something is wrong.

**NEEDS A MODEL TO DESIGN AGAINST**, because what the agent can
articulate depends on what it produces internally. This belongs with
the measurement session rather than before it.

### 3. Follow-on questions

"Now the same for last quarter." Refinement is how analysis actually
proceeds, and today every question starts from an empty box.

The cheap version is real: keep the last question in the box after
answering, so editing one clause is the default and starting fresh is
a deliberate clear. No model involvement, no new config.

The expensive version — generated suggestions based on what the answer
contained — is the Snowy approach and wants the measurement session
too.

### 4. History

Asked and answered, this session. Not a feature so much as the absence
of a loss: today an answer disappears the moment the next question is
asked.

**A DECISION FIRST:** how long, and where. In memory for the session
is free and honest. Persisting it means storing the questions people
asked, which is a record of what they were curious about, and that is
a privacy question rather than a storage one.

---

## What I would not build

**Clarifying questions before answering.** An extra model call per
question, on a system where the model is already the slow part, to
solve a problem nobody has reported. Revisit if the measurement
session shows vague questions are a real source of bad answers.

**A conversation thread.** Elysium answers questions about an
ontology; it is not a chat assistant, and the trace is more useful
than a transcript. Threading would also make "which generation
answered this" much harder to state, and that matters here.

---

## Order and dependencies

1 and 3's cheap half need nothing and would help immediately. 2 and
3's expensive half need the measurement session. 4 needs a decision
about persistence.

So: **examples first, retained question second**, and the rest after
there is a model to design against.
