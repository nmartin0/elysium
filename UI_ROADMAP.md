# Elysium UI roadmap

The backend phase is complete: every endpoint the near-term sub-apps
need exists, is tested, and is reachable. This file plans the work
that consumes it.

Written after the backend list was settled, so it inherits that
list's discipline: every item states what it needs, what it does NOT
need, and how it can be verified. An item without a verifiable outcome
is a wish, not a plan.

---

## What exists today

Four packages, roughly 6,300 lines:

| Package | Size | What it is |
|---|---|---|
| `shell-api` | ~3,000 | The shared client, auth, layout and routing |
| `app-browse` | ~2,100 | Object search and `ObjectDetailPanel` |
| `app-admin` | ~850 | User management |
| `app-query` | ~370 | The agent query view |

Single-hop link navigation already works in `ObjectDetailPanel`, which
is the foundation item 4 builds on.

## What the UI can already reach

Every one of these is tested backend-side and unused by any screen
today, which is the gap this roadmap closes:

```
GET  /health
GET  /me, /me/visible-schema, /me/visible-action-types, /me/visible-apps
GET  /objects/{type}/search        paged, sorted, opaque tokens
GET  /objects/{type}/{id}
GET  /objects/{type}/{id}/history  paged
POST /objects/{type}/count
POST /objects/{type}/aggregate
POST /objects/{type}/search-around
POST /actions/{name}, /writes/{id}/confirm
POST /query
```

Plus rendering metadata on every object type and field: display name,
plural, description, icon, colour, field visibility
(prominent/normal/hidden) and status (active/experimental/deprecated).

**`visibility: hidden` is cosmetic, never security.** It tells a screen
not to show a field; it does not withhold one. Field-level RBAC does
that, in the mediator, before a value is produced. A UI that treated
`hidden` as a permission would be wrong about what it is protecting.

---

## Build order

The order is from the original research: lowest-risk and
highest-precedent first, highest-effort last. Item 3 sits out of order
because its backend prerequisite is a design question, not a feature.

### 1. Read-only ontology schema viewer

Browse object types, fields, link types and cardinality, filtered
through the same RBAC and MAC the API already enforces -- restricted
fields hidden or marked, never a second permission model.

Deliberately NOT an editor. Editing a live ontology has separate
security implications and belongs in the far-later Ontology Manager
item.

**Needs:** `/me/visible-schema` only. Everything it renders --
display names, descriptions, icons, colours, field visibility and
status -- is already in that response.

**Why first:** it is read-only, single-endpoint, and it exercises the
display metadata end to end. If icons or humanised labels are wrong,
this is where it shows, before four other screens depend on them.

**Verifiable:** a role with fewer grants sees strictly fewer fields,
and the same schema rendered for two roles differs.

### 2. Object Explorer — see OBJECT_EXPLORER_PLAN.md

Expanded into its own file: it is the largest piece of this phase, it
needs backend work that does not exist yet, and nine design questions
were settled before starting rather than during.

THE BLOCKER, stated here so nobody starts the UI first: our filter is
equality only -- one value per field. Clicking two bars on a chart
means "these two values", which needs IN. The central interaction is
blocked on the query model, not on the UI.

Summary of what changed from the sketch below: charts are the FILTER
mechanism rather than a report; saved artifacts are re-authorized on
every open and say what was disabled; ownership is by ROLE rather than
by user; and the vocabulary is ours rather than the reference
implementation's -- Charts/Table, value counts, saved search, saved
selection.

Three separable pieces, in this order:

**Paged, sorted result tables.** `search` already returns
`next_page_token`, `total_matches` and accepts `order_by`. No screen
uses any of them. Treat the token as opaque -- it is versioned and
will change.

**Saved Explorations vs Saved Lists, kept distinct.** An Exploration
persists a filter and re-runs live; a List persists a frozen set of
object ids. Foundry's own users conflate these when the distinction is
not explicit in the UI, so name them differently and never offer to
convert one silently into the other.

**Filter-capable charts**, from `/objects/{type}/aggregate`: single
statistic, histogram, listogram. Nothing fancier until these are used
-- maps and grid plots are a different kind of work.

**Bulk actions** reuse the existing propose/confirm flow with a real
batch cap. The cap is not a nicety: an action over an unbounded result
set is how someone edits ten thousand objects by accident.

**Needs:** `search` (paged/sorted), `aggregate`, `count`, `actions`,
`writes/{id}/confirm`.

**Verifiable:** paging a changing result set is documented to possibly
duplicate or miss rows -- the UI must not present its row count as
authoritative during a live sort.

### 3. Pending changes / approvals inbox — BLOCKED, and on a decision

The two-phase propose/confirm mechanism exists. This gives it a queue
view across the org rather than only inline.

**Blocked on a backend design question, not a migration.** Today only
the PROPOSING user may confirm their own pending write, the store is
in-memory, and it expires in 15 minutes. The first of those is a
security property in the current model -- it stops a second user
completing a write the first abandoned -- so an approvals inbox is a
SECOND model, not a repair of the first.

The questions to answer before any UI work: who may approve what (a
reviewer grant, distinct from `execute:`), whether a proposer may
approve their own write, what expiry means when a human is expected to
be slow, and what the audit trail records about both parties.

**Not blocked on PostgreSQL.** SQLite already backs the write log and
credential store under concurrent writers; that framing was wrong and
has been corrected in `ROADMAP.md`.

**When it is unblocked:** reviewer eligibility derives from the SAME
RBAC and MAC check that gates the underlying action, never a separate
ACL. The field-level before/after diff is itself filtered through MAC,
so a reviewer never sees a field they could not otherwise read.

### 4. Vertex-lite: a read-only link explorer

Extends `ObjectDetailPanel`'s single-hop navigation into an explicit
"explore related" view.

**Show link-type counts BEFORE expansion**, so fan-out is never a
surprise. `/objects/{type}/count` and `search-around` make this cheap
to do honestly rather than by guessing.

Read-only to start: no drag-to-rearrange, no styling, no editable
canvas. Those are a different project.

**Needs:** `search-around`, `count`, and the link metadata from
`visible-schema` -- every generated link field carries `link_type`,
so both directions of one relationship can be grouped rather than
shown as unrelated columns.

**One known gap:** a link and its reverse are two entries. Presenting
them as a single relationship is display work over existing data, not
a backend change -- see the object-backed link types entry in
`ROADMAP.md`.

---

## Cross-cutting, and worth deciding once

**Error shape.** The API returns 400 with a real message for caller
mistakes -- an unknown aggregate names the valid ones. Surface those
messages rather than replacing them with a generic failure; they were
written to be read.

**`/health` is unauthenticated** and reports only whether subsystems
answer. Useful for a connection indicator; it deliberately carries no
counts, names or paths.

**Paging consistency is documented, not guaranteed.** Default paging
returns the latest results and may duplicate or miss rows if data
changes between pages. Fine for browsing, wrong for an export. A UI
offering an export should read once rather than page a moving target.

**The agent's step vocabulary** is `search_object`, `get_field`,
`get_object`, `aggregate_object`, `search_around`, `use_tool`,
`propose_action`, `finish`. A query view showing what the agent did
should render these; `scripts/agent_trace.py` already does exactly
that and is the reference for the shape.

---

## Conventions, so there is one way to do each thing

Found by auditing the four sub-apps for needless variety. Recorded
because the rules were real and followed, but written down nowhere --
which made correct differences look like inconsistency.

**Where data comes from.** Shell-held and passed as a prop when most
pages need it: the visible schema, visible apps, identity. Fetched by
the panel, through a cached helper in `shell-api`, when specific
screens need it: action types. The split tracks a real difference --
the schema has three consumers on nearly every page, action types have
two that a user reaches deliberately -- and putting the second in the
shell would cost every login a request most users never use.

**Caching lives in `shell-api`, not in a component.** Two components
need action types; caching in either would leave the other paying, and
caching in both is two caches. A third consumer should get the sharing
rather than invent a third.

**Guarding a stale response.** A refetching effect uses
`useLatestRequestGuard` -- an old response must not overwrite a newer
one. A fetch-once-on-mount effect uses NOTHING, because there is no
second request to race. Both patterns are correct for their case, and
a third (a `cancelled` flag) was removed rather than kept alongside
them.

**Errors.** `handleIfSessionExpired` first, then `getErrorMessage`,
and show the API's own message rather than a generic one -- the
backend writes real ones, and an unknown aggregate names the valid
ones.

## Sub-app layout: what is shared, and what is not yet

**Shared.** `Workspace` and `WorkspaceFilter` in shell-api give a
sub-app the two-pane shape -- configuration left, content right, both
filling the shell and scrolling independently -- or a single pane when
there is nothing to configure. Browse uses it.

**Not yet migrated: Query, Schema and Admin.** Each renders its own
top-level div and has NO stylesheet rules at all, so they inherit only
the canvas padding. That is not automatically wrong -- Query is a
prompt and an answer, and a configuration column would be an empty box
-- but Schema's tab filters and Admin's user controls are exactly what
a config pane is for.

Deliberately not forced. Migrating all three to two panes would be
shaping the apps to the layout rather than the reverse, and the layout
is new enough that Browse is the only evidence it is right.

**The error and loading pattern is NOT one pattern.** Seven places use
Callout and Spinner, in two genuinely different shapes: an early
return that replaces the whole screen when there is nothing to show,
and an inline banner above content that still renders. Extracting one
component for both would conflate "this failed" with "this failed and
there is nothing else". Counted before concluding: two of each, plus
three that only spin.

## Known inefficiencies in the shell

**The session probe fetches the whole ontology to ask a yes/no
question.** On mount, `App.tsx` calls `/me/visible-schema` purely to
see whether it gets a 401, DISCARDS the response, and a separate hook
then fetches the same endpoint again for real. That is the entire
ontology -- every object type, every field, with per-field RBAC
applied -- to answer "am I logged in?", which `GET /me` answers
directly.

Found in a real server log while testing the schema browser: three
requests for one page load. Two are the probe and the real fetch; the
third is React StrictMode double-invoking effects in development, so
production sees two rather than three.

NOT changed on the spot, deliberately. The comment above that effect
is unusually careful -- it explains why this one has a different shape
from the others -- which suggests someone hit a real bug arriving at
it. Swapping the endpoint without reading that reasoning properly is
how the bug comes back.

The fix is likely one line. The reading is not, and this belongs in
shell work rather than tacked onto a sub-app.

## Not in scope, recorded so they are not rediscovered

A full Ontology Manager (self-service schema editing), point-and-click
analysis beyond the three basic charts, trigger-based automations, and
a full editable graph canvas. Each is real and each is a separate
project; the near-term four do not depend on any of them.
