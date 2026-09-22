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

---

# 9. Type, density and the rest of the foundations

Chosen September 22 from the labelled specimens, on the owner's stated
criteria: EASY ON THE EYES FIRST, presenting a lot of data without
strain SECOND, and commercially usable.

## 9.1 Typeface — IBM Plex Sans, with IBM Plex Mono (specimen A2)

Both are SIL OFL 1.1, which permits bundling, embedding, redistributing
and SELLING the fonts as part of software. The only conditions: they
may not be sold on their own, and a derivative may not reuse the
reserved name "Plex". Inter (also OFL) was the runner-up.

WHY PLEX OVER INTER: it was drawn for interfaces where data accuracy
matters, and it separates 1 / l / I and 0 / O at 13px, which is the
size our tables actually run at. Inter's taller x-height packs
marginally more in, but its 1 and l are closer together -- a bad trade
in a product whose whole job is identifiers and amounts.

  --font-sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI",
               Roboto, Helvetica, Arial, sans-serif
  --font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo,
               monospace

SELF-HOSTED, NOT FROM A CDN. Elysium runs on the customer's own
infrastructure, sometimes with no outbound internet; a CDN font is an
external dependency AND a privacy leak on every page load. The OFL
permits bundling, and the licence file ships beside the woff2 files.
Weights kept to three -- 400, 500, 600 -- because each one is bytes an
operator waits for.

WHERE MONO IS USED: identifiers, hashes, paths, code, and anything a
person might copy. NOT amounts -- those use the sans with tabular
numerals, since a column of mono numbers beside mono ids turns the
whole table into a terminal.

## 9.2 Type scale — 1.2, base 14px (specimen B2)

    28px  600  page title           (1.2^5, rounded)
    20px  600  section
    17px  600  panel heading
    14px  400  body, table cells
    13px  400  dense table cells
    11px  600  uppercase labels, +0.06em letter-spacing

Capped deliberately: nothing above 28px. A tool that shows tables does
not need display type, and every heading step costs rows.

LINE HEIGHTS BY CONTEXT, which is the part most systems get wrong by
using one number: 1.5 body, 1.4 table rows, 1.25 headings. Tabular
numerals globally (font-variant-numeric: tabular-nums) so columns of
figures align without manual work.

## 9.3 Density — middle as the default, compact one click away (C2)

Row heights: compact ~30px, middle ~38px, roomy ~48px.

MIDDLE IS THE DEFAULT because the owner's first criterion is eye
comfort, and 38px is the height at which a 13.5px row has air without
halving what fits on screen. COMPACT IS ONE CLICK AWAY and persisted
per user, because the person scanning two hundred rows a shift should
not pay for the comfort of the person reading ten.

Roomy stays available for touch. WCAG 2.2 sets 24x24 CSS px as the
floor for an interactive target, so even in compact a checkbox or a
row action keeps its hit area regardless of the row's height.

## 9.4 Row separation — hairlines and hover (D3)

Rules at 45% of the border colour, plus a hover wash of the accent at
7%. Full rules (D1) fence every row and make a long table feel like a
grid of cells; zebra (D2) adds a second background that muddies a navy
canvas and fights the surface steps that carry elevation.

Sticky header, always. Left-align text, RIGHT-ALIGN NUMBERS, centre
status. Sort indicator on the active column, subtle on the other
sortable ones. Pagination rather than infinite scroll, because this is
data people refer back to -- "page 3, row 7" has to mean something.

## 9.5 Spacing, radius, elevation

SPACING: one 4px scale -- 4, 8, 12, 16, 24, 32, 48 -- used for padding,
margin and gap alike. No value outside it; a 13px padding is not a
decision, it is a slip.

RADIUS: 6px controls (buttons, inputs, chips), 10px panels and cards,
999px tags and pills. Small radii read as precise, which suits a tool;
large ones read as soft, which suits marketing.

ELEVATION: by LIGHTNESS STEP, not shadow -- canvas, surface, raised.
Shadows barely register on a dark canvas, which the specimen showed
directly. The one exception is genuinely floating layers -- menus,
popovers, dialogs -- which get a step AND a shadow, because they must
read as detached from everything beneath.

## 9.6 Motion

Durations 100 / 200 / 300ms only; ease-out entering, ease-in leaving;
at most two properties animated. Anything longer is a progress
indicator's job, not an animation's.

prefers-reduced-motion is respected everywhere, and specifically kills
the skeleton shimmer, which is the canonical vestibular trigger.

## 9.7 The four states (specimens E1-E4)

  LOADING, chosen by expected wait, not by taste:
    under 100ms   nothing. An indicator that flashes is worse than none.
    100ms - 1s    an inline cue: the button itself, no layout change.
    over 1s       a skeleton IN THE SHAPE OF THE INCOMING LAYOUT when
                  it is known; a spinner only when it is not.
  Skeletons are aria-hidden; a polite live region says "loading".

  EMPTY: icon, title, the REASON it is empty, and an action. "No
  objects match these filters" with a clear-filters button, never a
  blank panel.

  ERROR: plain language, what is unchanged, and a way out. Never a
  code, never a stack trace.

  PARTIAL -- the state that is ours alone (E4). "Not permitted",
  "restricted" and a real NULL must look like three different things.
  A hidden field is not an empty field, and neither is an absent one.
  Plain words chosen over a hatched chip: at 13px the hatching reads
  as a rendering fault.

## 9.8 The agent surface (specimen G2, and G3 for writes)

STEPS VISIBLE AS IT WORKS, with the answer beneath and a quiet readout
of steps, tokens and elapsed time against the deadline. The steps are
collapsible but shown by default: an agent that traverses an ontology
is making claims about YOUR data, and the traversal is the evidence.
Hiding it by default (G1) makes the answer look like an oracle's.

AND A PROPOSED WRITE IS NEVER SHOWN AS DONE (G3). Most applications
apply a change optimistically and reconcile later. Elysium's writes
are proposed, reviewed and approved, so the interface shows the field,
its current value, the proposed value, and the approval state -- and
nothing moves until the write is applied.

---

# 10. Ergonomics: how it should feel to use

Researched September 22. The question is not "is it usable" -- it is
whether somebody doing this eight hours a day gets faster or gets
tired.

## 10.1 Speed is a feature, and the keyboard is where it lives

The precedent is unanimous for tools where people repeat a task:
enterprise interfaces need keyboard-first workflows because for a
daily user "saved seconds compound into saved hours". Superhuman
holds its command palette under 100ms and reports users hitting inbox
zero 40% faster after about two weeks of muscle memory.

A COMMAND PALETTE, ON Cmd/Ctrl-K, which is what Linear, Slack and
Superhuman all use -- so it is already in the hands of anyone who
would use Elysium. Superhuman's own guidance: pick a binding that does
not clash with typing, and make the palette available EVERYWHERE.

WHY IT MATTERS HERE SPECIFICALLY: menus do not scale. Elysium has
object types, saved views, actions per type, admin functions and an
agent. A sidebar cannot hold that, and a submenu tree is a memory
test. A palette turns the whole product into search -- and people
prefer search to menus, which only help if you already understand how
the menus were organised.

THE REGISTRY PATTERN, from a keyboard-first design done properly: ONE
command registry as the single source of truth for id, label, default
binding, availability and help text. Buttons, shortcuts and the
palette all invoke the SAME command. Then shortcut help is generated
and cannot drift, and a command that is unavailable is shown disabled
WITH THE REASON rather than hidden.

  RULES THAT COME WITH IT:
    - never fire a global shortcut while the person is typing;
    - never override a browser or system binding without an
      alternative;
    - multi-key sequences only with a visible timeout;
    - the palette opens in under 100ms or it will not be used;
    - every destructive command needs confirmation or a documented
      undo.

## 10.2 Error prevention beats error messages

Nielsen's fifth heuristic, and the one Elysium's domain makes
load-bearing: the best interface eliminates the error-prone condition
rather than apologising afterwards. Constraints first -- disable what
is invalid, validate inline, make the wrong thing unavailable rather
than merely regretted.

CONFIRMATION DIALOGS ARE A LAST RESORT, NOT A DEFAULT. NN/g is blunt:
too many dialogs paradoxically INCREASE errors, because people learn
to dismiss them without reading. The guidance worth following:

    - reserve heavy confirmation for genuinely serious, rare actions;
    - do not give a confirmation a default "yes";
    - make the dialog say what will happen, specifically -- "delete 92
      objects" not "are you sure?";
    - use progressive disclosure for the detail, so the dialog stays
      scannable;
    - keep confirmatory and destructive actions FAR APART on screen,
      with redundant visual signals, because consequential options
      placed next to benign ones is a known error generator.

AND PREFER UNDO WHERE THE ACTION PERMITS IT. NN/g's own example is
Gmail's undo after deleting 92 emails: a safety net makes people
confident enough to work quickly, which is the whole point of
ergonomics.

## 10.3 What Elysium's own shape changes

UNDO IS OFTEN NOT AVAILABLE HERE, and pretending otherwise would be
worse than a dialog. A write goes to the customer's real database
through an approved action; there is no universal reverse. So:

    - APPROVAL IS THE SAFETY NET, and it is already built. The
      proposal step is where a mistake is caught, which is why the
      proposed-write view (specimen G3) shows current value, proposed
      value and state rather than applying anything.
    - WHERE A REVERSE ACTION EXISTS, offer it as an action, named
      honestly -- "create the compensating change", not "undo".
    - WHERE NOTHING CAN BE REVERSED, say so IN the confirmation.

BULK ACTIONS NEED A COUNT AND A SAMPLE. Acting on a set is the point
of object sets, and it is also where one mis-clicked filter becomes
200 changes. The confirmation names the number, shows a few of the
objects, and states what cannot be undone.

RECOGNITION OVER RECALL, which in a product with a declared ontology
means the interface should never ask somebody to remember a field
name, an object type or a filter operator that it could offer.

PROGRESSIVE DISCLOSURE, because the surface is genuinely large: a new
person should see search, results and an object. Quarantine rules,
lineage, snapshots and policies appear where they are relevant, not on
the first screen.

## 10.4 The ergonomics test for any screen we build

  1. Can a daily user do the common thing without the mouse?
  2. Does the command that does it appear in the palette, with the
     same label as its button?
  3. If it is destructive, is it prevented, undoable, or confirmed
     with specifics -- in that order of preference?
  4. Does the screen ask the person to remember anything it knows?
  5. Does it stay legible at compact density after an hour?
  6. Does every wait, empty and failure have a designed state?
