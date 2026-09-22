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

---

# 8. The palette

Decided September 22, after the owner asked for navy and off-white
rather than black and white, and confirmed it against a rendered
sample. Everything below was measured, not eyeballed, and the
measurements are recorded so nobody has to re-derive them -- or
"correct" them back to a familiar reference that is worse.

## 8.1 Why not black and white

  HALATION. White on pure black bleeds across the corneal lens,
  blurring letterforms. It is worst for readers with astigmatism, and
  it gets worse the longer the session. 21:1 is not a target; it is
  more contrast than reading wants.

  NO ELEVATION. Shadows barely register on black, so the usual way of
  saying "this panel sits above that one" stops working. Dark
  interfaces separate surfaces by LIGHTNESS STEP instead, which needs
  a canvas that is not already at the floor.

  OLED SMEAR. A true black pixel is switched off; scrolling white text
  across it makes pixels switch fully on and off, which smears.

  AND GREY IS FLAT. A blue cast in the darks gives depth that users do
  not consciously notice. Cool, slate-family neutrals are the
  convention for data-heavy interfaces -- which is what Elysium is.

## 8.2 How it was built

ONE HUE SPINE (255°), in OKLCH. OKLCH's lightness channel matches
perceived brightness, so equal numeric steps look equal -- which HSL
does not manage, and which is why hand-picked ramps drift bright and
dark across hues. Every neutral and the accent share the hue; only
lightness and chroma move.

Status colours break that rule deliberately: they are not supposed to
feel like comfortable siblings, they are supposed to be instantly
identifiable. They sit at EQUAL LIGHTNESS to each other so none shouts
louder than its neighbour, with chroma pulled back about 20%, since
saturated colour vibrates on a dark background.

## 8.3 The tokens

  DARK (the default)
    --canvas    #0c1723
    --surface   #182230      one lightness step up
    --raised    #242f3d      two steps up
    --border    #384352
    --text      #eef2f7      Lc 98   16.07:1
    --text-2    #c8d2de      Lc 78   11.81:1   secondary reading
    --text-3    #adb9c8      Lc 63    9.08:1   muted reading
    --dim       #8893a2      Lc 43    5.80:1   ICONS, BORDERS,
                                               DISABLED -- NOT TEXT
    --accent    #5fa1f3               6.78:1   buttons, chips, focus
    --link      #77baff      Lc 62    8.82:1   inline link text
    --success   #66ba7a               7.63:1
    --warning   #c89e3a               7.23:1
    --danger    #e88479               6.89:1
    --info      #6da7f1               7.27:1

  LIGHT (same hues, inverted lightness)
    --canvas    #f8fafd
    --surface   #edf0f4
    --border    #cdd5e0
    --text      #1d2a3a      Lc 98   13.90:1
    --text-2    #525f6f      Lc 79    6.23:1
    --text-3    #6b7787
    --accent    #1762b6      Lc 77    5.81:1
    --success   #1f7a3d
    --warning   #8a6100
    --danger    #b23b2e

## 8.4 Measured BOTH ways, and why that mattered

WCAG 2's ratio OVERSTATES contrast for dark colours -- its own authors
say it "cannot be used for guidance designing dark mode", because 4.5:1
can be functionally unreadable near black. So every pair was measured
again with APCA, the perceptual model behind WCAG 3, which is polarity-
aware and reports Lc rather than a ratio.

THAT CHECK CHANGED THE PALETTE. The first version's supporting greys
passed WCAG comfortably and failed perceptually:

    secondary  #b5bfcb   9.70:1  but Lc 66  -- large text only
    muted      #8893a2   5.80:1  but Lc 43  -- too low for text at all

Both were lifted one step, to Lc 78 and Lc 63. The old muted value
survives as `--dim`, for the roles that are not reading: icons,
borders, disabled states.

FOR REFERENCE, AND AS A WARNING: GitHub's dark theme -- the closest
prior art, and where most of this convention comes from -- has muted
text at Lc 44 and link blue at Lc 37, both below the perceptual
threshold for body text. They pass WCAG. If someone later compares our
greys to GitHub's and finds ours "too light", this is the reason they
are.

  THRESHOLDS USED: Lc 90 preferred for body text, Lc 75 the minimum
  where reading matters, Lc 60 for larger or UI text, Lc 45 for large
  text only, below Lc 30 not text at all.

## 8.5 Precedent

GitHub dark: canvas #0d1117, surface #161b22, border #30363d, text
#e6edf3, muted #8b949e, accent #2f81f7. Cool near-black with a blue
tint; blue reserved for links and navigation; green, red, yellow and
purple used only for semantics. Ours was derived independently and
landed within a few points of every one of those, a little more navy.

The same shape appears across developer tools -- Linear, Supabase,
Sentry all use a near-black canvas with one signature accent. Vercel's
pure black is the outlier, and it is a marketing aesthetic rather than
a data-tool one.

## 8.6 Rules that come with the palette

  1. COLOUR NEVER CARRIES A STATE ALONE. Success and danger collapse
     together under red-green colour blindness (8% of men). Every
     state carries a dot and a word as well as a hue. This matters
     most exactly where Elysium uses colour hardest: quarantine,
     drift, approval states.
  2. ELEVATION BY SURFACE STEP, never by shadow.
  3. --dim IS NOT A TEXT COLOUR. If text needs to recede, use
     --text-3; --dim is for icons, borders and disabled controls.
  4. THE ACCENT IS NOT THE LINK COLOUR. A filled button carries its
     own background, so Lc 49 is fine there; inline link text has to
     stand on the canvas, which is what --link is for.
  5. CHARTS GET THEIR OWN RAMP. Status colours are tuned to be
     unmistakable; series colours must be distinguishable FROM EACH
     OTHER, which is a different job. Same hue spine, higher chroma,
     checked in greyscale and under the three colour-blindness
     simulations.
  6. DARK IS THE DEFAULT, light is a real theme and not an
     afterthought: both were generated from the same hues, and both
     were measured.
