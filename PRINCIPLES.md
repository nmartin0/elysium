# Elysium: project principles

*Why the code is the way it is. Operational instructions -- exact
commands, the patch workflow, commit format, files not to hand-edit --
live in `AGENTS.md`, which is the how to this file's why.*

This is not a style guide. It's a record of the real, recurring
decisions this project has already made, over and over, across both
the backend and the frontend — written down so they stop being
tribal knowledge one person (or one AI session) has to rediscover
each time. Every principle here is backed by a real, specific place
in this codebase that already lives by it; none of this is
aspirational or copied from a generic best-practices list.

Written for two audiences equally: the person working on this
project, and any future Claude session picking it up cold, with no
memory of the conversations that shaped it. When in doubt about how
to approach a new piece of work here, this is the first place to
check — before README.md's own architecture, before INSTALL.md's own
tooling, this is the *why* behind both.

---

## 1. Verify directly. Never assume.

The single most consistently enforced habit in this codebase: before
writing code against a library, an API, or a piece of behavior,
*confirm it directly* — read the real type definition, run the real
function, inspect the real DOM output, check the real HTTP response
— rather than trust memory, training data, or "how it probably
works."

This isn't caution for its own sake. It has caught real, concrete
bugs every single time it's been applied seriously:

- Blueprint's `NumericInput` does **not** render `type="number"` —
  confirmed by rendering it and reading its actual DOM output, not
  assumed from the name. A test written against the assumed behavior
  would have been subtly wrong forever.
- A `Card` that's `CardList`'s own direct child silently gets
  `display: flex` from Blueprint's own shipped CSS — found only by
  inspecting a real, live element's own `getComputedStyle()`, after
  an isolated reproduction *outside* a `CardList` wrapper first,
  misleadingly, worked fine.
- `Drawer`'s own backdrop dismissal responds to `mousedown`, not
  `click` — confirmed only because a `fireEvent.click()` in a real
  test genuinely failed to trigger dismissal, not inferred from
  Blueprint's own docs alone.
- `ruff format --diff` was actually run against this real codebase
  before deciding not to adopt it (see `pyproject.toml`'s own
  comment) — the decision is backed by a real diff someone looked at,
  not a general opinion about auto-formatters.

The practical form this takes: before using any third-party
component's prop, grep its real `.d.ts` in `node_modules` first.
Before asserting what a rendered component looks like, render it and
read the real output (`screen.debug()`, a throwaway probe test, or a
live browser). Before claiming a fix works, reproduce the *original*
failure first, then confirm the fix against that same reproduction —
never trust that a plausible-looking diff did what it was supposed to.

## 2. Real tests, not shallow ones — and real negative controls.

Every test in this codebase exercises real behavior through real
interfaces: `React Testing Library` (typing, clicking, waiting for a
real async response) on the frontend, a real `FastAPI TestClient`
issuing real HTTP requests on the backend — never shallow rendering,
never mocking so deep that the test just checks its own mock was
called.

A new test is not trusted until it's been *proven* meaningful, not
just written and left to pass. The standard technique: temporarily
break the real behavior the test claims to protect, confirm the test
— and specifically that test, not some other one — fails, then
restore the fix and confirm it passes again. This has caught real,
otherwise-invisible problems more than once: a test asserting
`toHaveValue(250)` looked correct but was silently checking the wrong
thing (a numeric-input convention that didn't apply, since the real
component under test renders `type="text"`), caught only because a
negative control was run and the test kept passing when it shouldn't
have.

Tests that can't be proven meaningful this way are a real signal
something is wrong with the test itself, not a formality to skip.

## 3. jsdom cannot see CSS. Live-verify anything visual.

`jsdom` — what every frontend unit test actually runs against — never
applies real CSS layout at all. A test suite can be 100% green while
the actual, rendered page is visually broken. This has happened for
real, more than once: 20 passing `ObjectSearchPanel` tests, the whole
time a `display: flex` override silently broke the card layout, none
of them able to see it.

The rule this produces: any change that touches layout, color,
spacing, animation, or interactive visual state gets a real,
live-browser check before it's trusted — a real running server, a
real Playwright session, real screenshots and real computed styles,
not just "the code looks right" or "the unit tests pass." This is
not optional polish; it's the only verification method that can
actually see the class of bug jsdom is structurally blind to.

## 4. Security is explicit, fail-safe, and never inferred.

The backend's own defining constraint — an LLM-driven agent with
partial, adversarial trust — produces a small set of non-negotiable
rules that generalize past just the LLM boundary:

- **Nothing is implicit or inherited.** Every grant a role has is
  spelled out in `policy.yaml`, including field-level detail (even an
  object's own id field needs its own explicit `read:` grant). RBAC
  and MAC are two independent, both-required gates — never one
  standing in for the other.
- **"Doesn't exist" and "exists but you can't see it" are always
  indistinguishable**, everywhere, on purpose — same shape, same
  status code, same generic message. A more specific error, anywhere
  in this system, is a real information leak, not a UX nicety worth
  adding back later.
- **Fail-safe defaults, always.** A user with no role, or a role
  missing one specific grant, is denied — never implicitly allowed
  because a check was skipped or a condition wasn't anticipated.
- **Every access decision is logged**, allowed or denied, with which
  gate (MAC/RBAC) actually decided it broken out independently — the
  one place this system *is* allowed to be specific is its own,
  private audit trail, never the response handed back to a caller.
- **A UI-level filter is a display decision, not a new security
  decision**, and must never be treated as one. `ObjectDetailPanel`'s
  own `availableActions` filtering is real code that decides what to
  *show*, built entirely on facts the backend already, independently
  decided (`executable`, computed server-side) — it is not itself
  where authorization happens, and must never become the only place
  a check exists.
- **A question does not leave the VM** (the owner's decision, 26
  October). No query, and nothing read to answer one, is escalated to
  a hosted model, and Elysium does not fine-tune on its own traces,
  which hold customers' data. A deployment may still run a whole
  different model, which is that deployment's own choice and its own
  risk; what is not built, and not to be built without the owner
  reopening this, is a path that sends *one question* elsewhere.

## 5. Nothing ships without an honest account of what's still open.

Every non-trivial file in this codebase carries its own **AI-only
notes** section at the bottom — not user-facing documentation, but a
direct, honest handoff to whichever session (human or Claude) picks
this file up next without today's conversation in memory:

```
// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// RESOLVED (kept for history): ...
// DEFERRED (known, intentional, not yet built): ...
```

A `DEFERRED` entry is not a hidden gap — it's a *found*, considered,
and deliberately postponed decision, with the real reason written
down (a missing backend prerequisite, a UX call made once and worth
revisiting under different conditions, a second real use case not
yet in hand to design against). The test: could someone reasonably
ask "why isn't this built yet?" and find the honest answer already
sitting right there, instead of having to reconstruct it? A real,
recurring proof this works: this exact file caught its own, real gap
during a later review — `PendingWriteCard`'s own notes already
documented "no semantic From/To labeling for a sub_write" as a known,
deferred limitation, *before* it was independently rediscovered as a
real, live UX rough edge.

`RESOLVED` entries are kept, not deleted once done — they're the
project's own memory of *why* something is the way it is, which
matters exactly as much after the fact as before it.

## 6. DRY — for real, non-trivial duplication. Not everything.

Shared logic gets extracted when it's substantial enough that two
copies could silently drift apart from each other — a real
correctness or security property, not just a repeated shape.
`useLatestRequestGuard` is the clean example: a genuine
race-condition guard, independently duplicated in two files, one of
which had *already, explicitly* commented "same pattern as the
other" without ever actually being pulled out — a real, live risk
that a fix to one copy could be missed in the other.

What does **not** get extracted: a two-prop pattern like `text={x ?
'Loading…' : 'Label'} loading={x}`, repeated across half a dozen
buttons. That's not duplicated *logic* at risk of drifting — it's a
simple, direct expression of one boolean, and wrapping it in its own
abstraction would trade a small amount of repetition for a layer of
indirection that pays for itself nowhere. The question is never
"does this text look similar elsewhere" — it's "could these two
copies quietly stop agreeing with each other, and would that be a
real problem if they did."

## 7. No speculative code.

Nothing gets built for a need that isn't concrete yet. `UserMenu`
deliberately has no "Settings" entry, because there is no settings
feature anywhere in the app to open — adding the menu item first
would be exactly the kind of speculative UI this project has
consistently avoided. `AdminPanel`'s own role field stays a plain
text input, not a `Select`, because no backend endpoint exists yet to
list valid role names for it — and role names are genuinely
deployment-specific, so hardcoding a guessed list would be actively
wrong, not just premature.

The same discipline applies to abstractions: a second, real use case
is required before a pattern gets generalized, not assumed in
advance. `PendingWriteCard`'s own multi-object confirmation UI was
deliberately deferred until `TransferFunds` existed as a real,
second, multi-object action to design *against* — building it earlier
would have meant guessing at a shape with only one data point.

## 8. Breaking changes are the default while there is no deployment.

Nobody has an Elysium deployment, so nothing is kept for compatibility
(owner rule, 3 November 2026). Break freely when it makes Elysium more
usable and maintainable, or simpler without losing power. A change
replaces what it replaces **in place**: the old code, its callers, its
tests and its controls are deleted in the same change, with no shim, no
migration, no deprecation period, no freeze and no transition window
(BLOCKING.md "Converge on precedent" is the roadmap that applies this).

Two things do not bend. Each change still lands with its tests, and
the commit message records what broke. And the security invariants
(uniform denial, authorization in one place, MAC and RBAC on every
read, writes only through actions, re-authorisation at approval,
erasure completeness, read-only source access, no question leaving the
machine) are never relaxed without the owner.

This replaces an earlier rule that every backward-incompatible change
needed explicit authorization. That rule protected deployments that do
not exist, and made every break a conversation.

## 9. Research real precedent before inventing a pattern.

When adopting an established UX or API pattern, find the real,
existing thing being emulated and confirm the design against it
directly, rather than improvise something plausible. `GET /me` was
built after confirming how OpenID Connect's own UserInfo endpoint and
the precedent's own documented `getCurrent` route actually shape
this exact "who am I" response. The sidebar's own collapsed/expanded
defaults were checked against a real reference platform's own actual
behavior, detail by detail, with the deliberate departures (a
different keyboard shortcut, hidden instead of icon-strip collapse)
each justified against *why* the original pattern works the way it
does, not copied blindly at a scale this project doesn't operate at.
The sub-app priorities the (since consumed) roadmap set were this same
principle applied at a larger scale -- a real, structured research pass against
the precedent's own documentation, translated deliberately, feature by
feature, into what a smaller, single-tenant architecture actually
needs, not a wishlist of what a bigger platform happens to have.

## 10. Architecture: explicit layers, enforced, not aspirational.

Package and module boundaries in this codebase are real, checked
contracts (`import-linter`'s own contracts, `ui/`'s own npm workspace
split — one package per real screen or shared concern, not one
monolithic app) — not conventions that happen to be followed today.
`core/` never reaches into `adapters/` or `api/`; authentication
(`core.auth`) and authorization (`core.intermediate_layer`) stay
fully independent of each other; these are enforced on every run of
`./lint.sh`, not just documented intentions someone could quietly
drift away from.

## 11. Third-party code: install and import, never modify. Permissive licenses only.

A real, hard rule, decided directly, not a default assumption: this
project never modifies a third-party dependency's own source --
never patches it, never vendors a locally-edited copy into this
repository. Every real dependency is installed unmodified, from the
real package index (PyPI, npm), and used only through its own,
public, documented API -- extending a library via its own documented
extension point (a subclass, a callback, a plugin interface -- the
same real pattern already used for SQLite's own `set_authorizer`)
is normal, expected use, not modification, and creates no obligation
under any license at all. If a real, genuine need to modify a
dependency's own source ever arises, that is a rare, serious
decision requiring real, explicit authorization first -- never done
quietly, as a small fix, in passing.

This rule is *why* license choice is simpler than it might first
appear, not a way of avoiding the question: the one real clause that
distinguishes a permissive-but-not-minimal license like Apache 2.0
from MIT/BSD -- disclosing that you modified a file, if you modified
AND redistributed it -- can never actually trigger under this rule,
for any dependency, on any license. Confirmed directly, not assumed,
before adopting PyIceberg specifically: every mature, real "table
format" library in that entire space (Apache Iceberg, Apache Hudi,
and Delta Lake's own tooling) converges on Apache 2.0 by structural,
Apache-Software-Foundation governance necessity, not project-by-
project preference -- so treating Apache 2.0 as unacceptable here
would have meant either building real, equivalent functionality from
scratch for no real reason, or ruling out an entire, mature category
of tooling over a clause this project's own "never modify" rule
already makes moot.

The real bar this project actually applies -- and the distinction
that matters is MODIFICATION, not dependency:
- **Using a third-party library is fine regardless of its license**,
  copyleft included. Importing it, linking against it, calling its
  public API, running it as a separate process -- none of that
  triggers any license's modification obligations, because no
  modification occurs. A copyleft dependency (GPL, LGPL, MPL) placed
  no requirement on Elysium's own source simply by being depended on.
  This is a real, deliberate correction of an earlier, overcautious
  version of this principle, which wrongly barred copyleft
  dependencies outright: the line was never "what may we depend on."
- **Any code this project actually MODIFIES must be permissively
  licensed** -- MIT or BSD preferred, Apache 2.0 and equivalent
  permissive licenses genuinely acceptable. This is the real line,
  and the real reason the "never modify" rule above carries so much
  weight: modifying copyleft code is precisely what pulls its
  obligations onto the modified work. As long as this project never
  modifies a dependency's own source, the question stays moot for
  every dependency regardless of license -- which is why the two
  rules belong together, not as separate concerns.

A practical consequence worth stating, since it is easy to get
backwards: an automated license scan that FAILS the build on any
copyleft license anywhere in the dependency tree would enforce the
wrong rule entirely -- it would block dependencies that are
completely fine to use. Any real tooling here should check what this
project actually modifies (which is nothing, by rule), not what it
merely depends on.

---

If a future session — human or Claude — is unsure how to approach a
new piece of work on this project, the fast version of everything
above: verify the real thing directly before building against it;
write tests that exercise real behavior and prove themselves with a
negative control; check anything visual in a real, live browser,
since the unit suite structurally cannot; keep security explicit and
fail-safe, never inferred; leave an honest, findable trail of what's
still open and why; extract only real, at-risk duplication; build
only what's concretely needed now; never invent a new pattern from
scratch without checking real precedent, and never relax a security
invariant without the owner; and never modify a third-party
dependency's own source, ever, without treating it as a rare,
serious decision in its own right.

## 12. Powerful and plain: hide steps, not concepts.

Decided 27 October, by the owner: Elysium should be fully capable and
should not feel like rocket science. Both, not a trade. These are the
rules that follow, each already true somewhere in the code.

1. **Four ideas, one name each.** Things (objects), relationships
   (links), doing (actions), watching (triggers); permissions answer
   "who". A screen or an error uses these words and no others for them.
2. **One flow everywhere:** pick from what exists, read a plain-English
   preview, apply. Add-a-field, add-a-type and add-a-link are the
   pattern. A preview also says what the change affects and who.
3. **One engine, a simple door and a full door.** The guided builder
   writes the same configuration an expert would write; "show the
   lines" reveals it. Nothing is lost by being simple, because nothing
   else is underneath.
4. **Reduce steps, never merge concepts.** Merging a link with a grant
   would make adding a link a permission change (it is access-neutral
   today, which is why it applies at once). Shortcuts and chained
   guidance, not fused meanings.
5. **Permissions as questions.** "Who can see this?" and "What can
   she do?" are answered directly, and every grant reads as a sentence.
   Impact is shown before a change applies.
6. **Mistakes are cheap.** Preview, history to put a version back, a
   second person for anything that widens, and "used by" before any
   removal. A trigger shows how often it would have fired.
7. **Say the next step.** After a type is added: "Nobody can see this
   yet. Who should?" Recipes ("notify me when...") fill in an ordinary
   trigger and action; they are never a second engine.
8. **Measure it.** A written first-hour walkthrough (connect a source,
   make a type, link it, grant access, add a trigger, using only the
   screens). Where someone stalls is the next thing to fix.

## 13. How the AI and the engineer work together.

Written 31 October 2026 after reading what the people who build these
tools, and the people who measure them, say works. Each point is here
because it matches a mistake this project already made, or fixes one.

1. **Give the AI a way to check itself, and ask for the evidence.** A
   pass/fail check (a test, a command, a script) is the single
   highest-leverage thing, and the answer to "is it done" is the
   command and its output, never "I believe so". Anthropic's own
   best-practices guide says this first
   (https://code.claude.com/docs/en/best-practices).
2. **Test first, and watch the test fail before the code exists.**
   A test that was never seen failing may not test anything. This is
   Willison's red/green rule
   (https://simonwillison.net/guides/agentic-engineering-patterns/red-green-tdd/)
   and is why every guarantee here has a negative control.
3. **A second reader that has not seen the work reviews it.** The
   author is the worst judge of its own change. Review is done by a
   fresh agent given the diff and the agreed design, told to report
   correctness gaps only and to skip style (practitioner pipeline:
   https://dev.to/teppana88/how-i-validate-quality-when-ai-agents-write-my-code-481c).
4. **A rule that has no exceptions is a script or a hook, not a
   sentence.** Prose in CLAUDE.md is guidance and gets skipped under
   pressure; a script refuses. `scripts/make_patch.sh` and
   `scripts/apply_patch.sh` exist because the patch rules were prose
   and four rounds were lost to them.
5. **Keep the instructions short.** Anthropic recommends a CLAUDE.md
   of under about 200 lines holding only what cannot be learned from
   the repository; long files make the important lines get ignored.
6. **Small batches, frequent commits.** DORA's 2025 findings: AI
   raises throughput and also raises instability unless the batches
   stay small and the tests stay strong
   (https://www.infoq.com/news/2025/09/dora-state-of-ai-in-dev-2025).
7. **Write the spec, then build from it, in notes that outlive the
   conversation.** `BLOCKING.md` holds agreed designs. A compacted
   conversation summary is a claim to re-check against the code, not a
   fact (https://anthropic.com/engineering/effective-harnesses-for-long-running-agents).
8. **End-to-end over mocks.** Mocked tests pass while the screen is
   wrong; the browser tests and a person clicking have found what the
   unit suites could not.
9. **AI amplifies the practice it finds.** Good tests and small
   changes get faster; none of them gets faster without. Speed claims
   are mixed: METR measured experienced developers 19 per cent slower
   in 2025 and called its 2026 follow-up unreliable
   (https://metr.org/blog/2026-02-24-uplift-update/). So this project
   measures quality and rework, not typing speed.
