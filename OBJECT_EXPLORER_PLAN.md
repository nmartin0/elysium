# Object Explorer — plan

Item 2 of `UI_ROADMAP.md`, expanded because it is the largest piece of
the frontend phase and because it needs backend work that does not
exist yet.

Written after researching what Object Explorer actually is, and after
settling nine design questions that would otherwise have been decided
mid-implementation. The decisions are recorded here with their
reasoning, not just their outcome — a choice whose justification is
lost gets re-litigated.

---

## What it is

Two views of one object set, switchable, with the URL carrying which:

- **Charts** — and charts are the *filter mechanism*, not a report.
  Clicking values filters; selected values can be kept **or excluded**.
- **Table** — paged, sorted, column-configurable.

The reference implementation defaults to one chart per **prominent**
property, which is metadata we already ship.

## The blocker

**Our filter is equality only.**

```python
where_clause = " AND ".join(f"{key} = ?" for key in criteria.keys())
```

One value per field. So "region is us-west **or** us-east" is not
expressible — which means clicking two bars on a chart cannot be
expressed either. The central interaction of Object Explorer is
blocked on the query model, not on the UI.

Everything in phase 1 below exists to fix that.

---

## Decisions taken, with reasoning

**Saved artifacts are requests, never authorities.** Re-authorized on
every open. If the author has since lost access to a filtered field,
the filter is **disabled and the UI says so** — not dropped silently,
not failed hard.

Silently widening is the worst option: the user sees more rows and
concludes their data changed. Failing hard is unhelpful when the rest
of the search still works. And there is no disclosure risk in naming
the field, because the user wrote the filter — we are explaining their
own query, not revealing something they cannot see.

**Ownership is by ROLE, not by user.** An artifact is private, or
shared with a role. Sharing to individuals would be a second
permission model beside RBAC, and two models is how permission bugs
happen. The reference implementation shares by folder location because
folders are their permission system; ours is roles.

**Expiry belongs to the artifact type, not the store.** A pending
write dies in 15 minutes because it is a session continuation. A saved
search has no such semantics. If the store owns expiry, every future
artifact inherits a policy designed for one of them — so the store
persists and scopes, and each type declares its own lifetime, where
"never" is a legitimate value.

**A filter on an unreadable field is rejected at validation**, before
any query runs, with the same message as an unknown field. Running it
and returning nothing would leak: an empty result for
`region = 'us-east'` tells you the field exists and that value does not
match. Uniform denial means unreadable and nonexistent must be
indistinguishable — consistent with `search_around` returning empty
for ungranted links, and with `visible_schema` omitting rather than
marking.

**Relative dates resolve in UTC**, server-side. A saved search must
mean the same thing to everyone who opens it, and browser-local would
make "last 7 days" differ by timezone.

**Charts cross-filter.** One filter set drives every chart and the
table. Keep/exclude is copied deliberately: "everything except these
three" is what makes chart-filtering more than a fancy dropdown.

**Our own vocabulary, not the reference implementation's.** Their
terms are jargon or ambiguous:

| Theirs | Ours | Why |
|---|---|---|
| Explore / Results perspectives | **Charts** / **Table** | Says what you will see |
| Listogram | **Value counts** | Describes it |
| Exploration | **Saved search** | Implies re-running |
| List | **Saved selection** | Implies a fixed set |

"Saved search" versus "saved selection" carries in the names the
distinction their own documentation warns users conflate.

**Charting: ECharts now, deck.gl only if 3D lands.** Current guidance
describes the field as a ladder — standard charts at the top, deep
interaction in the middle, WebGL at the bottom. ECharts covers
histogram, pie, Sankey, treemap and geo natively, tree-shakes to
~100 KB, and renders on Canvas. Its cost is a React wrapper and a
config-object API rather than JSX, paid once.

visx was reconsidered and declined: its advantage is bespoke shapes
and deep interaction, and click-to-filter is an `onClick` with a datum,
which ECharts does natively. We would pay primitives-level effort for
library-level charts.

**3D is deferred, deliberately.** A 3D ontology graph looks impressive
and is usually *worse* for daily reading — occlusion, no stable mental
map, harder clicking, paid on every interaction. Build 2D properly; if
a question turns out to need a third dimension, that is the moment to
add it, and we will know what it is for.

---

## Build order

### Phase 1 — the filter model (backend) — DONE

Nothing in the UI can start until a filter can express more than
equality.

**1. [done] A filter vocabulary.** `equals`, `in`, `not_in`, numeric
`range` (min/max, either optional), `date_range`, `relative_date`
(sinceDaysAgo/untilDaysAgo, resolved UTC server-side), and
`contains` for text.

Validated against the field's declared `data_type` — a range on a
string field is rejected at load, not at query time. This is the same
machinery the deferred "field-value constraints" item needs, and
should be built once for both.

**2. [done] Pushed into the engine, not applied in Python.** The SQL/Python
alignment rule: set membership and ranges are what a database is for,
and the audit already found one place doing this wrong.

**3. [done] Adapter contract extension.** `find_ids` takes a filter
expression rather than a `dict` of equalities. The mirror adapter
translates what Iceberg can express and falls back to a projected scan
for what it cannot — the same compromise `resolve_reverse_links_batch`
already makes, documented where it happens.

**4. [done] search_object takes a condition list**, rather than a
{field: value} dict it converted itself -- which meant validate_filter
could never reject anything, because every condition was correct by
construction.

Estimated at "114 call sites across nine files" from grep hits
including comments. An AST walk found 67 real calls, five in
production. One session, not several.

The vocabulary also moved to core/filters.py: core.functions sits
below core.ontology in the layering and needs it too, and
lint-imports said so.

**5. [done] The unreadable-field rejection**, with a test that its message is
identical to the unknown-field case.

### Phase 2 — the artifact store (backend) — DONE

**6. [done] A persistent, role-scoped artifact store.** SQLite, alongside the
write log and credential store. Serves saved searches AND the pending
writes the Approvals inbox needs — solved once, as agreed.

Expiry declared per artifact type. Ownership private-or-role.

**7. [done] Re-authorization on open**, returning both the artifact and a
list of what was disabled and why, so the UI can say so rather than
guess.

### Phase 3 — the table (frontend)

**[done] The HTTP surface takes conditions.** /objects/{type}/count,
/aggregate and /search-around accept a `conditions` list alongside the
old `criteria` dict, and reject a request sending both -- merging
would need a rule for what happens when they disagree about one field,
and inventing one silently is how a filter ends up meaning something
nobody asked for.

**8. [done] Paged, sorted results.** `search` already returns
`next_page_token` and `total_matches` and accepts `order_by`, and no
screen uses any of them. Page tokens stay opaque.

**9. [done] Column configuration**, defaulting to prominent properties, with
hidden fields absent — the rendering rule the schema browser already
follows.

**10. Do not present the row count as authoritative while paging a live
set.** Default paging is documented as possibly duplicating or missing
rows.

### Phase 4 — the charts (frontend)

**11. [done] ECharts, wrapped once** in a shared component so no sub-app
touches the config API directly.

**12. Value counts, histogram, pie, single statistic**, from
`/aggregate`. One chart per prominent property by default.

**13. Click-to-filter, with keep/exclude**, cross-filtering every
chart and the table from one filter set.

**14. Measure it.** Charts make the aggregate path hot for the first
time. The shape is known — 2.5s of 3.4s at 200,000 objects is audit
logging, not queries — so this is a measurement against a real
workload, not a redesign in advance.

### Phase 5 — saving and acting

**15. Saved searches and saved selections**, distinct in the UI and
never silently converted.

**16. Bulk actions** through the existing propose/confirm flow, with a
real batch cap. An action over an unbounded result set is how someone
edits ten thousand objects by accident.

---

## Not in scope

Sankey and geo charts are available in ECharts and will be added when a
screen needs one, not before. 3D as above. Comparison views, modules,
and global cross-app search are separate projects.
