# Elysium: sub-app roadmap

This tracks planned, future sub-apps for this project, modeled on
Palantir Foundry's own ontology-aware application suite but scoped
down to Elysium's actual architecture: a single ontology per
deployment, no multi-tenancy, no code-customization layer, a
YAML-defined schema, server-enforced field-level RBAC+MAC, a
two-phase propose/confirm writeback, and an LLM agent that queries
the ontology through tools rather than a full enterprise platform.

The comparison this is based on came from a real, structured research
pass against Palantir's own current documentation (plus third-party
critique where it existed) — see `PRINCIPLES.md`'s own "Research real
precedent before inventing a pattern" principle for why that mattered
here specifically, not just generally. This file is the durable
record of that research's conclusions; the research itself, if it
needs revisiting, should be redone rather than assumed still current
-- Foundry's own graph/branching UX was already mid-change (Quiver's
graph mode redesigned, ontology branches being sunset for Global
Branching) at the time this was written.

---

## Near-term (prioritized, in build order)

Recommended order, from the original research: lowest-risk and
highest-precedent first, highest-effort/lowest-immediate-ROI last.

1. **Read-only Ontology schema viewer.** Browse the existing YAML
   schema (object types, properties, link types, cardinality) filtered
   through the same RBAC+MAC checks the API already enforces --
   restricted fields hidden or marked, never a separate permission
   model. Modeled on Swagger UI / GraphQL introspection / DBeaver's
   read-only schema navigator, deliberately NOT an editor -- editing
   the live ontology has real, separate security implications (see
   "Future / later horizon" below).
2. **Object Explorer parity for Browse.** Saved Explorations (persist
   filter/search state, re-run live) as a genuinely separate primitive
   from Saved Lists (persist a frozen set of object ids) -- Foundry's
   own users conflate these if the distinction isn't explicit. Bulk
   Actions on a result set, reusing the existing propose/confirm flow,
   with a real batch cap. A small set of filter-capable charts
   (Listogram, Histogram, Single Statistic) before anything fancier
   (maps, grid plots).
3. **A Pending Changes / Approvals inbox.** The two-phase
   propose/confirm mechanism already exists (`write_log.db`,
   confirm/reject); this is giving it its own queue view across the
   whole org instead of only inline, per-submission. Reviewer
   eligibility derived from the SAME RBAC+MAC check that gates the
   underlying action -- never a separate ACL. A field-level
   before/after diff (Foundry's own convention: changed value
   highlighted, prior value muted), itself filtered through MAC so a
   reviewer never sees a field they couldn't otherwise access.
4. **Vertex-lite: a minimal, read-only link explorer.** The schema
   already has real `link` fields (confirmed: 5 in the test fixtures,
   2 in the real deployment config) and single-hop link navigation
   already works in `ObjectDetailPanel`. This extends that to an
   explicit "Explore related" action showing link-type counts BEFORE
   expansion (so fan-out is never a surprise), starting read-only (no
   drag-to-rearrange, no styling) before ever considering an editable
   canvas.

---

## Future / later horizon

Raised directly, once the near-term list above is in place --
"those will integrate perfectly into our system once we have the
basic parts in order." Listed here honestly at different levels of
research depth, not all equally ready to scope:

- **A full Ontology Manager** (self-service schema editing, not just
  the read-only viewer above). Deliberately sequenced after the
  read-only viewer is in real use, and after a real, separate design
  conversation about who is allowed to edit the ontology itself --
  this has genuine security implications beyond the RBAC+MAC model
  covering DATA access today (indexing, backing-datasource
  permissions, and policy composition all become live concerns the
  moment schema itself is editable through the app, not just
  deployment config).
- **Quiver/Contour/Insight-style point-and-click analysis.**
  Structured, non-LLM charting/aggregation over ontology data,
  complementing `Query`'s own natural-language analysis with a
  deterministic "build me a chart" tool that doesn't depend on the
  LLM at all. Noted directly in the original research as real,
  existing Foundry capability, but NOT yet given the same close,
  structured research pass Vertex and Ontology Manager received --
  worth a dedicated, focused research pass of its own (chart types,
  aggregation UI, how results interact with the existing RBAC+MAC
  filtering) before this gets its own scoped build plan.
- **Automate.** Trigger-based automations when ontology data changes
  -- notifications, or auto-proposing actions when a condition is
  met. Not present in Elysium at all today, and like Quiver/Contour/
  Insight above, named directly in the original research as a real
  gap without yet having its own deep, structured research pass --
  needs one (trigger/condition model, how it interacts with the
  existing two-phase writeback and RBAC+MAC, notification delivery)
  before a real build plan exists.
- **Full Vertex** (beyond the near-term Vertex-lite item above).
  Styling (node fill/badges/layouts), grouping and grouping-into-
  edges for fan-out, saved/parameterized graph templates, and
  eventually simulations. Foundry's own users cite this as one of the
  platform's weaker areas ("the visualizations are poor" -- a
  recurring, if broad, third-party complaint), so this is deliberately
  the last, highest-effort item on the whole roadmap, not started
  until the minimal, read-only version has real, demonstrated use.
