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

---

# 11. The set — the subject the whole interface is about

Decided September 22. The layout schematics could not be judged
because they were missing the thing a shell exists to carry: the work
in Elysium is not "look at a graph", it is NARROW A SET DOWN,
UNDERSTAND IT, ACT ON IT. Four questions, researched, then AUDITED
AGAINST THE CODE -- which changed two of the answers.

## 11.1 A set exists the moment you search (implicit)

Foundry's object set exists as soon as a query does; saving is a
separate, deliberate act -- "import saved object set" is its own card
in Quiver. Same here: everything on screen IS a set, named by how it
was built (`Customer · 3 filters · 1,284`), so the interface always
has a subject and saving is a PROMOTION rather than a creation.

## 11.2 Following a link produces a NEW set, with provenance

Foundry is explicit: search-around on an object set returns another
OBJECT SET, and traversing from a single object gives a "MultiLink"
that MUST BE CONVERTED to a set before you can pivot again. Sets
compose; single objects do not.

AUDIT FINDING -- THIS IS A CHANGE, NOT A DESCRIPTION. Elysium's
mediator is conditions-in, ids-out: search_around(user, object_type,
conditions, link_field) -> list of ids. There is no set object in the
backend at all. So this decision creates work: a set needs a
REPRESENTATION (object type + conditions + the traversal chain that
produced it), and search_around has to accept and return that shape
rather than a list. The existing LinkTrail in Browse is the UI half of
this already.

## 11.3 Live by default, frozen deliberately -- and both are named

Every mature product that met this shipped two kinds. HubSpot: an
ACTIVE list "updates itself automatically as contacts meet or stop
meeting your criteria"; a STATIC list is "a fixed snapshot of who
matched at the moment you created it". Amplitude: dynamic vs static
cohorts. Foundry: object set vs materialization.

THE TWO FAILURE MODES ARE FAQ ENTRIES, which is how much the naming
matters: "why are contacts dropping off my list?" (it is active) and
"why isn't my list updating?" (it is static). Whichever a person is
looking at must say so on its face.

TWO RULES WORTH INHERITING:
  - YOU CANNOT MANUALLY ADD TO A LIVE SET. HubSpot forbids it, and is
    right: membership is either derived from criteria or it is not.
    Half-and-half is a bug factory.
  - CONVERSION BOTH WAYS. Frozen -> live hands membership back to the
    criteria; live -> frozen can be scheduled, which HubSpot notes is
    "handy for campaign snapshots" -- and here is what an approval or
    a bulk action needs.

AND WHERE ELYSIUM CAN BEAT THE PRECEDENT: HubSpot's static list
freezes MEMBERSHIP and nothing else -- it cannot tell you what those
records looked like then. Because gold pins and tags published
snapshots, a frozen set here is the definition PLUS the gold snapshot
id, so it reproduces not only who matched but the data as it was. That
is an audit artefact the precedent cannot offer.

## 11.4 The words

AUDIT FINDING -- MY FIRST NAMING WAS WRONG. I proposed calling a
frozen set a "snapshot", on the grounds that the word already means
this in the lake. It does -- api/routes.py already exposes Iceberg
table snapshots to the admin UI -- which makes it AMBIGUOUS, not
elegant: "the snapshot" would mean a table version in one screen and a
frozen set in another, and the two appear together in exactly the
place that matters (a frozen set is pinned TO a table snapshot).

  set          the live thing you are looking at; implicit, named by
               how it was built.
  view         a SAVED set definition, still live. AUDITED: this
               matches what saved_views already stores -- object type,
               query text, conditions, presentation -- so the existing
               feature IS this, and no migration is needed.
  frozen set   membership fixed at an instant, pinned to the gold
               snapshot it was taken from. Shown as "frozen 14:22 ·
               publication 7", never as "snapshot".

## 11.5 An open question the audit surfaced

BULK ACTION ON A SET IS NOT A UI FEATURE. propose_action takes an
action type and parameters; the objects acted on are parameters, one
proposal at a time. Acting on 200 objects therefore means either 200
proposals or an action type whose parameter is a list -- and that
decides what the approvals queue shows: one approval covering 200
changes, or 200 rows.

The second is unusable; the first needs a way to review a change that
is stated once and applied many times. That is a WRITE-PATH design
question, not a screen, and it should be answered before the set UI is
built on top of it.

## 11.6 What this settles about the shell

The set is the SUBJECT, so it belongs in the top bar, where a
document's name sits. Everything else is about it: left is ways to
change the set, centre is the set viewed somehow, right is about one
member, the agent is "ask about this set", the bottom is what the
system is doing to the data underneath.

That is what the earlier schematics were missing, and why they felt
interchangeable: they had panels but no subject.

---

# 12. Three canvases, two inboxes, one settings area

Elysium has six apps -- browse, query, approvals, notifications,
schema, admin -- which is a decomposition BY FEATURE, the way software
gets built, not BY WHAT THE USER IS WORKING ON. That is why moving
between them feels like changing tools rather than changing view.

Sorted by SUBJECT there are only three things a person works on:

  1. A SET OF OBJECTS -- instances. Narrow, understand, act. Today
     that is browse, charts, explore-related, saved views and the
     agent's answers: five surfaces over ONE subject. It should be one
     workspace with MODES -- table, graph, chart -- and switching mode
     must not lose the set, which today it does, because they are
     different apps.
  2. THE ONTOLOGY -- types, not instances. What a Customer IS, what
     links to what, which rules apply. Going from "1,284 customers" to
     "the Customer type" is a change of KIND, not of filter.
  3. THE PIPELINE -- the process that produces both.

And two things that are not subjects at all:

  INBOXES. Approvals and notifications are about EVENTS THAT ARRIVED,
  not something being explored. They deserve their own place -- and
  every row in them must be a DOOR into subject 1 or 3, landing on the
  object or the build in question. Today they are terminal: you read
  the notification, then navigate by hand to whatever it was about.

  SETTINGS. Admin is the system's own configuration, visited rarely,
  and fine where it is.

SO THE LEFT RAIL IS NOT AN APP SWITCHER. It is a SUBJECT switcher,
with three entries plus the inboxes -- far fewer than today.

---

# 13. The ontology UI

The pipeline is visual; the ontology should be too. Researched
September 22 against Foundry's Ontology Manager and the academic
lineage (Protégé, VOWL/WebVOWL), and against the very different
tradition of visual POLICY editors -- which turned out to matter more.

## 13.1 The canvas: types and links, not instances

  - TYPES AS NODES, LINKS AS LABELLED EDGES, which is the VOWL
    convention that three user studies found comprehensible. Colour
    carries kind, not decoration.
  - A SCHEMA-ONLY VIEW is the default and the point: this canvas is
    about what a Customer IS, never about the 1,284 of them.
  - SELECT A TYPE, and the inspector holds its identity field, title
    field, properties with their declared types, links, constraints,
    action types -- everything ontology_schema.yaml declares about it.
  - VALIDATION AS CANVAS WARNINGS. Elysium already refuses to load a
    broken ontology; the canvas should show the same findings as
    marks on the node BEFORE the file is saved, which is the
    difference between a linter and a stack trace. Newer ontology
    tools do this as "quality analysis with a score and annotated
    anti-patterns".
  - HEALTH, as Foundry's own Ontology Manager carries -- it exists
    partly for "investigating whether data is updating in user
    applications". A type that no gold table populates is a type
    nobody can query, and the canvas should say so rather than
    leaving it to be discovered.
  - CROSS-LINK TO THE PIPELINE: a type opens its gold node; a
    property shows the silver column it came from, which the lineage
    columns make possible.

## 13.2 Permissions: the EDITOR is the less valuable half

This is the finding that changed the design. AWS ships a visual policy
editor and its own documentation says "always test your policies with
the policy simulator" -- the editor alone is not trusted. Google went
further and built two separate tools:

  POLICY TROUBLESHOOTER: given a principal, a resource and a
  permission, it says whether access is allowed, "lists the relevant
  policies and explains how they affect the principal's access".

  POLICY SIMULATOR: shows how a proposed change WOULD alter access,
  baseline versus simulated -- and can replay recent real access
  against the new policy.

THE ADMINISTRATOR'S BURDEN IS NOT WRITING THE POLICY. IT IS NOT
KNOWING WHAT THE POLICY DOES. So the three screens below matter more
than any editor, and two of them are read-only.

## 13.3 "Who can see this?"

Select a type or a field: which roles hold the grant (or the tag that
carries it), and for MAC, which security value a person must hold --
traced THROUGH THE CHAIN when the type borrows its classification via
a via_field.

Chains are where the surprises live. F-19 was a chain bug that loaded
happily and failed every read; the gold migration's one dangerous line
is a chain comparison that would silently widen. A picture of the
chain is the cheapest defence either would have had.

## 13.4 "What would this person see?"

Pick a user; render the ontology as they see it -- types absent,
fields marked "not permitted", the partial state from the specimens
(E4) applied to the schema rather than to rows. This is Google's
troubleshooter aimed at a person rather than a resource, and it is the
fastest way to answer the question administrators actually get asked,
which is never "what does the policy say" but "why can't Bob see
this".

## 13.5 "What would this change do?" -- the highest-value screen

Before saving, the diff stated in ACCESS TERMS rather than config
terms:

    this newly exposes 412 objects and 3 properties to role analyst
    this removes read of Customer.email from 2 roles

That is Policy Simulator's baseline-versus-simulated, and it converts
an invisible consequence into a sentence. Everything needed to compute
it already exists: the ontology, the roles, the tags and the counts.

## 13.6 Widening access is the rare case for a heavier confirmation

The ergonomics research (section 10) says confirmation dialogs should
be reserved, because too many of them INCREASE errors. This is the
case worth reserving one for -- and possibly the one place Elysium
takes Don Norman's suggestion, quoted by NN/g, of "requiring a
different user to confirm the most dangerous actions".

A change that WIDENS access -- more roles, more fields, a
declassification -- is exactly that shape, and Elysium already has the
machinery: it is a proposal, reviewed and approved, through the queue
that exists. A change that NARROWS access needs no second person.

## 13.7 What the ontology UI edits, and what it must not

It edits the DECLARATION -- the same law as the pipeline builder
(LIVE_UPDATES_AND_PIPELINE_BUILDER.md part 3.1): ontology_schema.yaml
and policy.yaml, round-tripped, validated before landing, recorded as
a generation, rollback-able.

AND IT MUST NOT INVENT MEANING. GOLD-3c already settled that the
ontology is DECLARED and the pipeline is built to match it, not
derived from what the data happens to hold. The canvas is a better
pen, not a different author.
---

# 14. The ontology canvas: layout, and where presentation lives

Researched September 22. Three doubts from the design discussion, each
with precedent, and two with a documented FAILURE attached -- which is
the part worth keeping.

## 14.1 The graph layout itself

WHAT THE STUDIES SAY:

  - FORCE-DIRECTED DEGRADES WITH SIZE. One comparison found it
    "performed better at graphs with 20 nodes but become less readable
    as the amount of nodes increased". The shipped ontology has 2
    types; a real deployment will have 10 to 120. So force-directed is
    fine early and wrong later.
  - FOR ONTOLOGIES, LAYERED WINS: "in ontology graphs, where hierarchy
    and semantic depth are critical, layered or hierarchical layouts
    tend to offer the clearest structure", drawn with ORTHOGONAL EDGE
    ROUTING -- and "edge crossings and poor structural organisation
    can significantly hinder graph comprehension".
  - BUT HIERARCHY COSTS PATH-FOLLOWING. An eye-tracking study found
    that for path-following tasks, orthogonal and force-directed
    layouts need LESS link-tracing effort than hierarchical, because
    hierarchical layouts draw attention to line crossings. Following a
    chain of links is exactly what a person does here.

  SO: layered for structure, orthogonal routing, and crossing
  minimisation treated as a first-class requirement rather than a
  nicety -- because the layout that reads best statically is the one
  that fights the task it exists for.

AND THE FINDING THAT SETTLES A DESIGN DETAIL: a poor layout makes
users spend "up to 25 percent of their time on manual layout
adjustments". So auto-layout must be good, AND once a person moves a
node that position must stick forever. A graph that re-jiggles on
reload destroys spatial memory, which is most of why a canvas beats a
list.

## 14.2 Positions live APART from the declaration -- settled in 2010,
     by people who got it wrong first

BPMN 2.0 "separates the semantic model from its diagrammatic
representation": each visual shape points at a semantic element by id.
The payoff is exactly what we want -- "purely visual changes in the
diagram, such as adjusting the layout of elements, have no impact on
execution behaviour", and engines "will happily execute a BPMN file
that contains no <bpmndi:BPMNDiagram> at all".

THE COUNTER-EXAMPLE IS XPDL, which BPMN replaced: there, each node
represented BOTH the semantic element and its visual one, so the same
element appearing in several views became several XML elements, and
"it is up to the tool -- or the modeler -- to maintain consistency
between their definitions".

  FOR ELYSIUM: a PRESENTATION file, separate from
  ontology_schema.yaml, holding positions keyed by type name. The
  ontology never depends on it. Nothing breaks without it. It matches
  the split this deployment already uses -- one file per concern,
  data_silos.yaml apart from config.yaml apart from policy.yaml.

AND THE WARNING THAT COMES WITH THE PRECEDENT: for UML, "the usage of
Diagram Interchange is almost nonexistent", and in practice a model
imported elsewhere means "the diagram must be reconstructed from
scratch". The separation succeeded; the attempt to STANDARDISE the
presentation format failed. So: separate the file, and keep it small
and private. It is ours, not an interchange format.

THE FALLBACK PATTERN, from a BPMN tool that documents it plainly:
generate a layered layout when none exists, and offer an explicit
auto-layout that regenerates it, where "only shape and edge
coordinates change -- the semantic model is untouched".

AND A CONSEQUENCE WE HAD NOT PLANNED FOR: because presentation is
separate, TWO PEOPLE CAN HOLD DIFFERENT VIEWS OF THE SAME ONTOLOGY --
which BPMN supports by design and XPDL could not.

## 14.3 Action types: on the node, not as nodes

EVENT STORMING PUTS COMMANDS ON THE CANVAS, as their own colour,
attached to aggregates, with bounded contexts drawn as boxes. So
"verbs belong on a model canvas" has standing.

BUT THE CONTEXT DIFFERS, and that is the whole argument: Event
Storming's canvas is about BEHAVIOUR OVER TIME -- commands sit to the
left of the events they cause, arranged on a timeline. An ontology
canvas is about STRUCTURE and has no time axis. Putting action types
on as separate nodes imports a second grammar into a picture that
cannot express it.

  SO: actions appear ON the type node -- a count and a badge, expanded
  in the inspector. That keeps something genuinely useful visible at a
  glance (which types are writable and which are read-only) without
  turning a structure diagram into a process diagram.

## 14.4 Grouping: it is called a SUBJECT AREA, and it is older than
     all of this

From the ER modelling literature: "subject areas help reduce larger
models into smaller, more manageable subsets of entities that can be
more easily defined and maintained", existing "for easier navigation
as well as comprehension of the model". A cited real case: a
healthcare system with OVER 2,000 TABLES broken into subject areas --
members, plan, network providers.

Two details matter for us:

  - ERwin's interface puts a SUBJECT AREAS PANE BESIDE the model pane.
    The grouping is a navigational overlay, not a change to the model.
  - DDD's bounded contexts are the same idea with a stronger claim,
    partitioning the solution space so each context may have its own
    model.

  SO YES, the ontology needs a concept it does not have -- and it is a
  PRESENTATION concept. A subject area is a named subset of types, for
  navigation. It lives beside the positions, not in the declaration,
  so ontology_schema.yaml never acquires a grouping that changes what
  anything MEANS.

AND THE CAVEAT FROM THE SAME SOURCE: "there is no wrong way of
grouping and categorizing". People will regroup constantly, so this
has to be cheap to change and incapable of breaking anything --
which it is, precisely because it is not in the declaration.

## 14.5 What this adds up to

  ontology_schema.yaml   what the types MEAN. Unchanged.
  presentation file      positions, subject areas, collapsed state.
                         Optional, regenerable, per view.
  the canvas             layered, orthogonally routed, crossing-
                         minimised, with saved positions honoured and
                         an auto-layout button that only moves
                         coordinates.
  the node               type name, key, counts, health, security
                         badge, action badge; properties at close
                         zoom.
  the edges              data links in one visual language, SECURITY
                         CHAINS in another, on a layer that can be
                         switched on -- the view that would have made
                         F-19 obvious at a glance.
---

# 15. Proposals and approvals: presence without prompting

The owner asked whether a mailbox for proposal control should be
available on every screen. Researched September 22, and the precedent
splits: enterprise practice says YES to persistent presence, and the
fatigue literature says NO to persistent PROMPTING. Both are right,
about different things.

## 15.1 What enterprise practice does

SAP Fiori is the clearest model: a bell in the shell with a badge, a
notification centre listing items by date, type or priority, and
QUICK ACTIONS inline -- "you might want to quickly approve a low-value
purchase requisition without having to navigate to the approval task
in app My Inbox". Selecting a notification navigates to the relevant
app; workflow items go to My Inbox.

Their hierarchy is worth copying: "the most urgent and most visible
notifications are those that require a response", where "an approver
must approve or reject" -- and for those the launchpad shows them "in
even more places". URGENCY EARNS SURFACE AREA; everything else does
not. ServiceNow, Workday and Concur land on the same shape: one
unified task list, detail enough to decide, action where you are.

## 15.2 And what the fatigue research says, which applies directly
     to an AGENT-DRIVEN write path

APPROVER FATIGUE is "the loss of decision quality that happens when
reviewers face too many requests with too little context", showing up
as rubber-stamping and inconsistent outcomes -- and the phrase that
should worry us, "the control exists but the human decision can no
longer be trusted".

It descends from alert fatigue, where surveys put uninvestigated
alerts between a quarter and two-thirds, and where "when the volume of
alerts outpaces the capacity to evaluate them, teams don't slow down
and miss deadlines. They speed up and miss alerts."

AND THE FINDING THAT IS ABOUT US SPECIFICALLY. If every trivial action
demands confirmation, "you are running thousands of reps that teach
the reviewer one lesson: approving is safe and approving is fast" --
and then an attacker who can influence the agent's output needs only
to BURY ONE CONSEQUENTIAL ACTION INSIDE A STREAM OF ROUTINE ONES. It
arrives "wearing the same dialog box as the four hundred harmless
lookups before it, and it gets the same reflexive click".

Elysium's writes are proposed BY AN AGENT, and prompt injection is
exactly the influence channel that sentence describes. The instinct to
gate everything is what manufactures the inattention the dangerous
approval slips through.

## 15.3 The decisions

  A BADGE ON EVERY SCREEN, NOT AN INBOX. The count is always visible
  in the shell; the queue is one keystroke away; the full review is
  its own place. An inbox rendered on every screen competes with the
  work and teaches people to dismiss it.

  NO QUICK APPROVE FROM THE BADGE -- and this is a deliberate
  departure from Fiori. Their low-value requisition is reversible and
  bounded. AUDITED: Elysium's write path has NO undo -- no revert, no
  rollback, nothing -- because a write goes to the customer's real
  database through an approved action. The guidance for exactly this
  case is that reversible actions deserve one click and an undo, while
  the blocking confirm is "for operations with no undo button".
  Approving requires looking at the diff.

  SORT BY CONSEQUENCE, NOT ARRIVAL. The recommendation across this
  research is to "sort actions by reversibility and impact". Elysium
  has the ingredients already: the action type, the fields touched,
  how many objects, and whether the change WIDENS ACCESS (section
  13.6), which is the one that should always sort to the top.

  SHOW PENDING PROPOSALS IN CONTEXT, which is the part no inbox does
  well. If an object has a pending change, that belongs ON THE
  OBJECT; if a set does, it belongs on the set -- "3 of these 40 have
  pending changes". AUDITED, AND IT IS NEARLY FREE:
  write_log.pending_changes_for_ids(object_type, object_ids) already
  exists. This is also the antidote to context-free approving, since
  the reviewer is already looking at the thing being changed.

  EVERY INBOX ROW IS A DOOR. Consistent with section 12: a proposal
  opens the object or the build it concerns, not a dead-end detail
  page.

## 15.4 Measure the reps, because the failure is silent

The documented early signal of rubber-stamping is that "your average
time per approval keeps dropping even though the changes are not
getting any simpler".

AUDITED: the audit log timestamps every entry, so median
time-to-decision per approver, per action type, is computable today.
It belongs in Admin beside the other metrics -- because this failure
mode has no error, no exception and no alert. The control keeps
looking present while it stops working, and the only way to see it is
to watch the clock.

## 15.5 What this does NOT mean

Not fewer approvals. The gate stays where it is; what changes is that
the gate is not imitated everywhere else. A confirmation that is
everywhere is a confirmation nowhere -- which is the same conclusion
section 10 reached from the error-prevention literature, arrived at
from a second direction.
---

# 16. Alerting on the pipeline

The same question as section 15, pointed at the data: silos going
offline, cleaning and merging going wrong, a stage falling behind.
Researched September 22 -- and AUDITED FIRST, because Elysium already
has more of this than the discussion assumed.

## 16.1 What already exists (audited, not remembered)

  - A NOTIFICATIONS STORE: notify / for_user / mark_seen /
    unseen_count, per user.
  - MIRROR HEALTH ALREADY ALERTS, from core/mirror/health_condition.py
    and run_sync's _notify_mirror_health, on refused syncs and on
    tables that have not changed in over a threshold -- freshness and
    failure, two of the five pillars below.
  - AND TWO DESIGN DECISIONS IN IT THAT THE RESEARCH ENDORSES:
      RECIPIENTS COME FROM A GRANT, not a list: "whoever holds
      manage:deployment can start a sync, so whoever holds it should
      hear that one is needed". A deployment that adds an
      administrator changes the recipient list by doing so.
      REPEATS ARE SUPPRESSED PER RECIPIENT, because "a standing
      condition is true until somebody fixes it, and a notification
      per sync is a channel nobody reads by the time it matters" --
      while a CHANGED summary is news and goes through.
  - IT NEVER RAISES INTO THE SYNC: failing to notice something must
    not turn a successful sync into a failed one.

So this section is about extending a working design, not inventing
one.

## 16.2 The two bodies of precedent

SRE, ON WHAT DESERVES A HUMAN. "Every page should be actionable;
simply noting 'this paged again' is not an action", and "every page
response should require intelligence. If a page merely merits a
robotic response, it shouldn't be a page." The capacity limit is
stated plainly: a responder "can only react with a sense of urgency a
few times a day" before fatiguing.

  AND THE THREE-WAY SPLIT, which is the part worth copying exactly:
  page-worthy alerts go to a person NOW; "important but subcritical"
  ones go to a TICKET QUEUE; "all other alerts should be retained as
  informational data for status dashboards". Email alerts specifically
  "are of very limited value and tend to easily become overrun with
  noise".

  SYMPTOMS, NOT CAUSES: "include cause-based information in
  symptom-based pages or on dashboards, but avoid alerting directly on
  causes", because a rule further up the stack catches more distinct
  problems at once.

  AND ONE ALERT PER INCIDENT: "noisy alerts that systematically
  generate more than one alert per incident should be tweaked to
  approach a 1:1 alert/incident ratio".

DATA OBSERVABILITY, ON WHAT TO WATCH. The five pillars, standard since
2020: FRESHNESS (is data arriving on schedule), VOLUME (are row counts
within expected ranges), SCHEMA (have columns been added, removed or
changed), DISTRIBUTION (are value patterns stable), LINEAGE (which
downstream consumers are affected when something breaks).

## 16.3 The symptom, for Elysium, is not what it first looks like

A silo going offline is a CAUSE. The symptom is that a person reading
an object sees data that is stale, incomplete, or absent -- and
several different causes produce it: the source is unreachable, the
sync refused, the audit failed so gold did not publish, a rule
quarantined half the rows.

  SO THE PAGE-WORTHY RULE IS ABOUT THE SERVED DATA: an object type is
  being served from a publication older than its declared tolerance,
  or is not being served at all. One rule, many causes caught -- and
  the cause named in the alert body, which is exactly the shape the
  SRE guidance describes.

## 16.4 The five pillars, mapped to what Elysium can already compute

  FRESHNESS      publication age per object type against a declared
                 tolerance; source read age per silo. Partly built
                 (STALE_AFTER on mirror tables).
  VOLUME         row count per publication against the last -- and
                 gold's audit ALREADY REFUSES a publication that loses
                 more than half its rows. The alert is the refusal,
                 which is a symptom with a cause attached.
  SCHEMA         drift verdicts already exist and already refuse.
  DISTRIBUTION   the quarantine RATE per rule: 0.1% is a data problem,
                 40% is a pipeline problem (the owner's D4 decision).
                 This is the pillar Elysium is furthest from and the
                 one that catches "cleaning or merging going wrong".
  LINEAGE        which object types a failing source feeds -- which
                 the lineage columns and the gold conform now make
                 answerable, and which turns "primary_sql is down"
                 into "Customer and Transaction are affected".

## 16.5 The rules for Elysium's alerting

  1. THREE TIERS, as the precedent splits them: NOW (served data is
     wrong or absent), QUEUE (subcritical -- a quarantine rate moved,
     a source was slow, a publication was refused but the last one
     still serves), DASHBOARD (everything else, retained and visible,
     never pushed).
  2. ONE ALERT PER INCIDENT. A sync that fails for eight tables
     because one silo is down is ONE alert naming the silo and the
     eight, never eight alerts.
  3. SUPPRESS THE STANDING CONDITION, ANNOUNCE THE CHANGE -- already
     the behaviour of the mirror-health notifier, and the rule the
     rest should follow.
  4. RECIPIENTS FROM GRANTS, never from a configured list -- already
     the behaviour, and it means an alert cannot outlive the
     administrator it was addressed to.
  5. EVERY ALERT IS A DOOR into the pipeline canvas, landing on the
     stage that failed, with its status and its findings (section 12's
     rule, and what the canvas is for).
  6. NO EMAIL BY DEFAULT. The precedent is blunt that email alerting
     becomes noise; in-product first, with email as a declared
     escalation for the NOW tier only.
  7. AND MEASURE THE ALERTS THEMSELVES, as section 15 measures
     approvals: how many fired, how many were acted on, how many
     recurred. An alert nobody acts on is a bug in the rule, and
     without the count nobody ever finds out.
## 16.6 How fresh an object should be -- decided from precedent

The owner asked for the numbers and left the choice to precedent. What
follows is therefore a decision, with the reasoning kept so it can be
argued with later.

### The rule everyone converges on

FRESHNESS IS DERIVED FROM THE DECISION THE DATA FEEDS, not from what
the pipeline can manage -- "a freshness number without a threshold is
trivia" -- and the published tiers are by consequence: HOURS for
things feeding live action, DAILY for dashboards and reporting, WEEKLY
for cohort analyses and anything read monthly.

TWO WINDOWS, NOT ONE. Dagster's policy declares a fail_window and a
shorter warn_window -- 24 hours and 12 in their example -- and the
wider practice agrees: "it is more practical to set two tiers rather
than a single threshold", warning first, then blocking or explicitly
propagating the stale state.

AND ANCHOR TO THE CADENCE, not to a number from nowhere. dbt declares
warn_after and error_after against a source's expected refresh;
Dagster's cron policies declare the schedule the asset is meant to
keep. Datadog's example for a critical table is 6 hours to alert, 4 to
warn -- a tight pair, for a table that loads hourly.

### What is specific to Elysium, and narrows the question

  - YOUR OWN WRITES ARE NEVER STALE. The overlay shows applied
    changes immediately, whatever the sync did. Freshness therefore
    governs only changes made in the SOURCE systems by other people or
    other software -- a narrower question than "how fresh is my data".
  - TWO CLOCKS, AND THE USER-VISIBLE ONE IS THE PUBLICATION. Silver
    records when the source was READ; gold records when a publication
    was MADE. A source read hourly but published daily is a day stale
    to a reader, and no source-side number catches that.
  - 25 HOURS ALREADY EXISTS as the mirror's staleness judgement,
    chosen to catch "the nightly sync did not run" without crying
    wolf on a weekly table.

### The decision

  1. THE DEPLOYMENT DECLARES ITS EXPECTED SYNC INTERVAL -- one number,
     default 24 HOURS, since INSTALL.md leaves scheduling to the
     operator and nightly is what an unattended on-prem deployment
     does. Everything else is derived from it, so an operator who runs
     hourly changes ONE number and every threshold follows.

  2. THRESHOLDS ARE MULTIPLES OF THAT INTERVAL, not absolutes:
         warn  at 1.1 x interval   (26 hours nightly)
         fail  at 2.1 x interval   (50 hours nightly)
     WARN IS ONE LATE RUN; FAIL IS TWO CONSECUTIVE MISSES. That keeps
     the existing 25-hour judgement almost exactly, and it is the
     honest reading of a daily pipeline: a run that slips by an hour
     is not an incident, and two missed nights is.

  3. MEASURED FROM THE PUBLICATION, per object type -- the clock a
     reader actually experiences.

  4. AN OBJECT TYPE MAY DECLARE ITS OWN PAIR, for the handful where
     being a day behind costs something: warn 2 hours, fail 6, on an
     hourly sync -- Datadog's ratio for a critical table.

  5. REFERENCE DATA MAY DECLARE ITSELF EXEMPT. A type that genuinely
     changes quarterly generates nothing but false alarms otherwise,
     and a channel with false alarms in it is a channel nobody reads
     (section 16.2).

  6. AND A TARGET TIGHTER THAN THE SYNC INTERVAL IS REFUSED AT LOAD,
     naming both numbers. A type declaring two hours on a nightly
     deployment is not ambitious, it is guaranteed to alert forever --
     which is a configuration error, and Elysium already refuses
     configuration errors at load rather than discovering them in
     production.

  7. SHOWN, NOT ONLY ALERTED ON. Every object view carries "published
     14:22", so staleness is visible before it becomes an alert. The
     alert fires at the window; the timestamp is always there.

