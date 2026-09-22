# DEV_UI.md -- what Elysium's interface should be

Written September 22 after the owner said the interface is BOTH
unfinished and disjointed to move through. Those are two different
faults with two different fixes, and treating them as one is how a
redesign fails: new paint on the same dead ends, or a new structure
that still looks like a prototype.

Researched against Palantir's own interfaces, because they are the
closest thing to prior art for an ontology-shaped product.

---

## 1. What Palantir actually ships

FOUR LAYERS, and only two of them matter to Elysium.

  BUILDING THE DATA
    Pipeline Builder   point-and-click ingest and transform; you
                       "start by defining endpoint schema for
                       Ontology object types and properties and
                       describing the pipeline to match inputs".
    Ontology Manager   object types, links, actions, primary keys,
                       display configuration.

  EXPLORING IT
    Object Explorer    "a search and analysis tool for answering
                       questions about anything in the Ontology
                       layer", where users visually compose queries
                       from simple filters up to Search Arounds,
                       then view results as an exploration or a
                       table, compare object sets, take BULK actions
                       on a set, and export it. Needs no
                       pre-configuration.
    Object Views       "a central hub for all information and
                       workflows related to a particular object":
                       its own data, linked objects, key metrics,
                       and links to or embedding of related
                       analyses.
    Vertex             a graph canvas: add objects, click one for
                       its properties, run Search Arounds to pull in
                       related objects, filter the whole graph with
                       property HISTOGRAMS and "filter to / filter
                       out", with applied filters shown at the top
                       and removable individually.

  ANALYSING IT        Contour (tabular), Quiver (charts, time
                      series).
  COMPOSING APPS      Workshop, a widget kit: object table, object
                      list, property list, links, edit history, DATA
                      FRESHNESS, ACTION LOG TIMELINE, filter pills,
                      metric cards.

## 2. The six patterns underneath the product names

  1. THE OBJECT VIEW IS A HUB, not a detail page: properties, links,
     history, metrics and the ACTIONS available, in one place.
  2. OBJECT SETS ARE FIRST-CLASS: built, named, saved, compared,
     bulk-acted on, exported. A set persists; a query does not.
  3. SEARCH AROUND: start from objects, hop along links, filter at
     each hop. This is what an ontology has that a database does not.
  4. FACETED FILTERING WITH VISIBLE PILLS: distributions to filter
     by, filter-to and filter-out, and the applied filters always on
     screen so you know what you are looking at.
  5. PROVENANCE WITHIN REACH: freshness, edit history, lineage, one
     click away from the data they describe.
  6. ACTIONS WHERE THE DATA IS, not in a separate administrative
     corner.

## 3. What Elysium has today, counted

  app-browse         object search, object detail, explore-related
                     (this IS search around), charts, notes, link
                     trail, saved views
  app-query          the agent
  app-approvals      the write inbox
  app-notifications  triggers and alerts
  app-schema         the ontology as a reference
  app-admin          roles, metrics, mirror status, silos,
                     deployment config (read-only)
  shell-api          the shell, auth, fetch-once hook

So the apps are not the gap. Browse already holds four of the six
patterns in embryo.

## 4. The diagnosis: two faults, two fixes

### UNFINISHED is a craft problem

Symptoms: inconsistent spacing and density; tables that are HTML
tables; empty states that say nothing useful; loading that flashes;
errors that appear where the data should be; iconography borrowed
from whatever Blueprint offered. Nothing is wrong, and nothing looks
decided.

THE FIX IS OWNERSHIP OF THE COMPONENTS (UI-KIT in the roadmap): a
small kit in this repository, with deliberate spacing, density and
type, and one answer each for empty, loading, error and partial
states. That is also the honest reason to move off Blueprint --
not vendor risk, which its Apache-2.0 licence already bounds, but
that a borrowed design language cannot be DECIDED.

### DISJOINTED is an architecture problem

Symptoms, and each is a dead end:

  - A search gives rows; the rows do not become a THING. Nothing
    can be saved, compared, acted on as a group, or handed to the
    agent.
  - Explore-related pulls linked objects, and the result cannot be
    filtered further or turned back into a search.
  - The agent lives in its own app, so a question about what you
    are looking at means starting again in another tab, describing
    in words what was already on screen.
  - Charts are a panel, not a lens over a set.
  - Provenance and freshness live in Admin, away from the data they
    are about.
  - Approvals are somewhere else again, so a write you proposed is
    reviewed in a different room from where you proposed it.

THE FIX IS A SPINE: one path -- SEARCH -> SET -> OBJECT -> RELATED
-> ACT -- that every app hangs off, with the set as the thing that
travels along it, state in the URL so any point is a link, and the
agent available at every station rather than at one.

## 5. What to build, in order

  1. OBJECT SETS AS REAL THINGS. Named, saved, compared,
     bulk-actioned, exported, handed to the agent. Saved views are
     half of this already. Biggest multiplier, because every other
     item below gets better once a set exists.
  2. FACETED FILTERS WITH PILLS AND COUNTS, replacing form-style
     filtering: distributions, filter-to and filter-out, applied
     filters always visible.
  3. THE OBJECT VIEW AS A HUB: properties, links, history, notes,
     provenance and the actions available on THIS object, together.
  4. THE AGENT EVERYWHERE: "ask about this set" inside Browse,
     seeded with what is on screen. Elysium's actual edge over the
     prior art, where AI sits alongside rather than inside.
  5. A PROVENANCE PANEL: which source, which bronze snapshot, which
     publication, when. The lineage for this now exists (patch 340).
  6. A DATA HEALTH APP: quarantined rows and the rule that held
     each one, failing expectations, freshness per type, the last
     publication. Quarantine is invisible today, and invisible
     absence reads as data loss.
  7. A GRAPH CANVAS for instance-level exploration -- objects and
     links, expanded by search-around. The resolution exists; this
     is rendering.
  8. A COMMAND PALETTE AND GLOBAL SEARCH. Keyboard-first is most of
     what makes a tool feel like a tool.

  Plus the two already planned: the PIPELINE BUILDER
  (LIVE_UPDATES_AND_PIPELINE_BUILDER.md) and ONTOLOGY VISUALISATION
  -- the type-level map, which is also how the builder draws links.

  And underneath all of it, UI-LIVE: a screen that does not update
  itself feels unfinished no matter how it looks.

## 6. What NOT to build, deliberately

  - An app-building platform (Workshop). An app inside an app.
  - Analysis notebooks (Contour, Quiver). Charts over a set, yes; a
    second analytical language, no.
  - Model management, a marketplace, time-series infrastructure,
    geospatial.

Palantir has thousands of engineers and customers demanding those.
Elysium's edge is the agent, the security model and governed writes.
Every hour on a chart builder is an hour not spent there.

## 7. The order these come in

UI-KIT and UI-LIVE are foundations: the first makes "finished"
possible, the second makes the product feel alive. The spine work
(items 1-4) is what fixes disjointed. The builder and the graph
canvas are large, and both want the kit underneath them first.
