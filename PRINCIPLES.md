# Elysium: project principles

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

## 8. Backward-incompatible changes need explicit authorization.

This project has made real, deliberate breaking changes — replacing
a top nav bar with a sidebar, moving the session from a JS-readable
token to an `httponly` cookie, rebuilding nav from three hardcoded
links to a real, permission-driven list. Every one of them happened
*because* it was discussed and explicitly authorized first, not
because it seemed like an improvement in isolation. "Little to
nothing important enough to preserve" is a real, quoted decision that
licensed a full rebuild — the license came from the conversation, not
from Claude's own judgment that the change was good.

## 9. Research real precedent before inventing a pattern.

When adopting an established UX or API pattern, find the real,
existing thing being emulated and confirm the design against it
directly, rather than improvise something plausible. `GET /me` was
built after confirming how OpenID Connect's own UserInfo endpoint and
Palantir Foundry's own documented `getCurrent` route actually shape
this exact "who am I" response. The sidebar's own collapsed/expanded
defaults were checked against a real reference platform's own actual
behavior, detail by detail, with the deliberate departures (a
different keyboard shortcut, hidden instead of icon-strip collapse)
each justified against *why* the original pattern works the way it
does, not copied blindly at a scale this project doesn't operate at.
`ROADMAP.md`'s own sub-app priorities are this same principle applied
at a larger scale -- a real, structured research pass against
Foundry's own documentation, translated deliberately, feature by
feature, into what a smaller, single-tenant architecture actually
needs, not a wishlist of what a bigger platform happens to have.

## 10. Code-quality tooling: several genuinely different questions, not one.

Both halves of this codebase run a small set of tools chosen because
each one catches something structurally different from the others —
never redundant, never decorative:

**Backend** (`./lint.sh`): Ruff (is this file well-formed, locally?),
MyPy (do the types actually agree with each other — the only one of
the four that understands data *shape*?), Vulture (does anything in
the rest of the codebase still use this, at all — whole-program dead
code analysis Ruff structurally cannot do per-file?), Import Linter
(is X even *allowed* to import Y, regardless of whether it compiles?).

**Frontend** (`cd ui && npm run lint / knip / format:check`): oxlint
(style/correctness), `tsc --noEmit` (do the types agree), knip (does
anything still use this file/export/dependency at all), oxfmt
(formatting). The same four-way split as the backend, deliberately.

`ruff format` is deliberately never run — not an oversight, a real,
checked decision (`pyproject.toml`'s own comment has the specifics):
it would rewrite genuine, deliberate, hand-placed formatting choices
already established throughout this codebase into its own generic
style, on every file, forever. A tool earns its place here by
catching something objectively wrong; overriding a real, considered
authorial choice is not that.

## 11. Commit discipline: one real, coherent change, honestly explained.

A commit is one logical unit of work, not a batch of whatever
happened to be edited in the same sitting. When two genuinely
separate concerns end up touching overlapping work, they get split
into separate commits even after the fact — confirmed real and
practiced, not just stated: an early commit combining a test-mock fix
with an unrelated type-safety change was deliberately un-committed
and re-split into two, once it was noticed the two file sets never
actually overlapped.

A commit message explains *why*, not just *what* — the real
motivation, the real alternative considered and rejected, the real
verification performed (which tests, which negative control, what a
live browser check actually showed), not a changelog-style summary
of the diff. Every commit is verified clean (the full relevant test
suite, lint, build) *before* it's made, never after, and every commit
this project hands off across the sandbox/real-machine boundary gets
its own patch, generated against its own real, explicit parent
commit, and round-trip tested by applying it to a completely fresh
clone before it's ever handed over — confirming the patch is correct
in isolation, not just "worked when I had all my other context still
loaded."

## 12. Architecture: explicit layers, enforced, not aspirational.

Package and module boundaries in this codebase are real, checked
contracts (`import-linter`'s own contracts, `ui/`'s own npm workspace
split — one package per real screen or shared concern, not one
monolithic app) — not conventions that happen to be followed today.
`core/` never reaches into `adapters/` or `api/`; authentication
(`core.auth`) and authorization (`core.intermediate_layer`) stay
fully independent of each other; these are enforced on every run of
`./lint.sh`, not just documented intentions someone could quietly
drift away from.

---

If a future session — human or Claude — is unsure how to approach a
new piece of work on this project, the fast version of everything
above: verify the real thing directly before building against it;
write tests that exercise real behavior and prove themselves with a
negative control; check anything visual in a real, live browser,
since the unit suite structurally cannot; keep security explicit and
fail-safe, never inferred; leave an honest, findable trail of what's
still open and why; extract only real, at-risk duplication; build
only what's concretely needed now; and never make a breaking change,
or invent a new pattern from scratch, without checking real precedent
or getting real authorization first.
