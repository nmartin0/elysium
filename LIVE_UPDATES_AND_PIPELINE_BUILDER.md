# Live updates, and a pipeline builder

Two directions from the owner, September 22. Both are about Elysium
SHOWING what it is doing: the first because it currently does not, the
second because building a pipeline should be something you can see.

---

# Part 1. Live updates

## What it does today, measured

ONE panel polls: MirrorPanel, every 30 seconds. Everything else uses
`useFetchOnce`, which deliberately never refetches -- its own comment
says most callers "have no reason to refetch at all". There is NO
server-side streaming anywhere: no SSE, no websocket endpoint.

So the complaint is accurate and it is by design, not oversight: an
approval raised in another tab, a sync that finished, a gold
publication, a notification, a configuration reload -- none reaches an
open page until someone reloads it.

## The transport: server-sent events

SSE, not websockets. It is one-way, which is exactly the shape here:
the browser already has POST for everything it sends. It is plain
HTTP, so proxies, TLS and the existing cookie auth work unchanged --
no upgrade handshake for a corporate proxy to refuse. The browser's
own EventSource reconnects automatically and resends Last-Event-ID,
which gives replay for free. A websocket would add a bidirectional
channel nothing needs and per-connection state to match.

## The security decision, and it is the important one

EVENTS CARRY NO DATA. An event says "something of this kind changed",
never what changed. The client then refetches through the SAME
authorised endpoints it already uses, so MAC, roles and every
permission check apply exactly as they do now.

The alternative -- pushing the changed object down the stream -- would
put a second, parallel read path beside the mediator, and every
security rule would have to be re-implemented on it correctly, forever.
That is how leaks happen. A hint plus a refetch cannot leak: the
refetch is the existing, tested path.

A hint's SCOPE still needs care: "a Customer changed" tells a user
that SOME customer changed. So hints name a TYPE and a kind of change,
never an id, unless the id is one the stream's own user can already
see.

## Fan-out across workers, without a new dependency

The usual answer is Redis. Elysium already has the pattern it needs:
core/config_history.py keeps a monotonic `reload_epoch` in SQLite that
every worker reads to notice a configuration change. Events work the
same way -- a small table with a monotonic id, written by whatever
changed, and each open stream reading rows after the last id it sent.
Cross-worker by construction, no new process, no new dependency, and
Last-Event-ID resume falls out of it: a reconnecting browser asks for
everything after the id it last saw.

WHAT RAISES AN EVENT: a write applied, a sync finishing, a gold
publication, a notification created, a configuration reload, a
quarantine finding. Each already happens at one place in the code.

## What the client does

  - ONE EventSource per tab, opened by the shell, not one per panel.
    Panels subscribe to the kinds they care about.
  - `useFetchOnce` gains an OPTIONAL revalidation hint -- not a general
    refetch policy, which its comment rightly warns against. A panel
    says which event kinds invalidate it.
  - NO full-page reload, ever. The page state -- scroll, a
    half-written filter, an open inbox item -- survives.
  - MirrorPanel's 30-second timer retires.

## The operational constraints, stated before building

  - A stream must NOT hold a generation reference: a hot reload swaps
    generations, and a long-lived connection holding one would keep the
    old configuration alive for hours. It takes the generation per
    poll.
  - Nor a database connection, for the same reason and for the pool's.
  - It must close on graceful shutdown, within the 30-second grace
    E-12 proved, or a restart waits for idle browsers.
  - Caps: connections per user and in total, because a long-lived
    connection per tab is a resource an unauthenticated flood would
    otherwise multiply. Heartbeat comments keep intermediaries from
    closing an idle stream.
  - The events table is pruned; it is a notice board, not a log. The
    audit log remains the record.

---

# Part 2. A pipeline builder sub-app

The owner: once raw databases are registered, admins should be able to
drag, drop and point-and-click connections between databases and
pipeline stages, with configuration along the way, to build the gold
ontology visually -- and Elysium itself should present the data
visually at every step.

## What it edits: the declaration, through the existing path

The builder writes CONFIGURATION, never data. Its output is a proposed
change to the two files GOLD-3c splits -- the ontology declaration and
the source bindings -- applied through the machinery that already
exists: validation at load, config_history recording every generation,
the reload epoch, and rollback. A builder that wrote its own config
path would bypass the validation that makes a bad ontology impossible
to load.

## The canvas, and what each stage offers

  SOURCES        the registered silos and their tables, with the
                 columns actually present (columns_present already
                 answers this).
  BRONZE         what the source said, unchanged. Sample rows.
  SILVER         per column: the standardisation rules (S1), the
                 expectations and their policy -- warn, quarantine,
                 fail (S2/S3) -- and the table's duplicate-key policy
                 (S4). Sample rows AFTER each rule, and the
                 quarantine count with its reasons.
  GOLD           the object type: its key, its properties, which
                 silver column each comes from, required-ness, and
                 the links drawn as LINES between types on the canvas.
                 The audit's result for a trial build.

## Showing the data at every step is the point

Elysium already holds every layer: bronze, silver, the quarantine
tables, gold and its publication tags. So each stage can show real
rows, not a schematic -- and the difference between two stages (what
standardisation changed, which rows a rule held back, why) is the
thing that makes a pipeline understandable.

## The dry run is already built

Gold writes to an AUDIT BRANCH and publishes only if the audit passes
(patch 341). That is exactly a preview: a proposed pipeline can be
built on a branch, its audit findings and sample rows shown, and
nothing published until a person accepts. The builder does not need a
separate simulation -- it needs to show what the audit branch already
produces.

## What it must not become

  - Not a way to edit data. Writes go through action types.
  - Not a second ontology authority: what it produces is the declared
    ontology, in the same files, reviewable as a diff.
  - Not a place where a source's shape silently becomes the ontology
    (GOLD-3c): it PROPOSES from what it sees, and a person accepts.

---

# Part 3. The pipeline builder, designed (September 22)

The owner's picture: create a database visually, choose its adapter,
give it the details to find it, watch a heartbeat; then click to
create bronze for it, draw arrows, configure cleaning on the way to
silver, and finally connect silvers to gold -- with every
transformation, merge and field resolution possible on the canvas.

Researched before designing, and the research changes the shape in
four useful ways.

## 3.1 The law: the canvas edits DECLARATIONS, never a program

THE DOCUMENTED FAILURE of every visual ETL tool is the same one.
No-code platforms "lack essential software engineering practices such
as version control, modularization, and comprehensive testing", and
what starts easy "can give way to a tangled web of dependencies and
configurations". Matillion's own users name the specific gap: no
version control for the pipeline logic.

ELYSIUM ESCAPES THIS, but only because of a decision already made
(CONFIG_ROUND_TRIP_AND_UI_KIT.md): the canvas writes the same YAML a
person would write, round-tripped byte-identically, validated by the
loader before it lands, recorded as a generation in config_history,
and rollback-able. A drag produces A REVIEWABLE DIFF IN GIT.

  SO THE LAW IS: the canvas is an EDITOR OF DECLARATIONS. The moment
  somebody can draw logic that exists only on the canvas -- a box
  whose behaviour is not in the files -- we have built the thing the
  research warns about.

## 3.2 Draw the topology; CONFIGURE the logic

  DRAWN, because it is genuinely graph-shaped:
    which source tables are ingested at all, and which silvers
    combine into which object type.

  CONFIGURED IN THE INSPECTOR, because it is form-shaped:
    standardisation rules, expectations and their policies,
    duplicate-key policy, field mapping, survivorship.

Per-field logic drawn as boxes on a canvas IS the hairball the
research describes. The inspector already exists in the shell for
exactly this: select a node or an edge, configure it on the right.

## 3.3 MOST ARROWS DRAW THEMSELVES

In Elysium's shape the graph is not free-form:

    source table -> bronze     1:1 BY CONSTRUCTION
    bronze -> silver           1:1 BY CONSTRUCTION
    silver -> gold             many-to-one, and the interesting one

So asking a person to draw the first two is busywork that can only be
done one way, and every hand-drawn arrow is a chance to draw it wrong.
THEY APPEAR AUTOMATICALLY the moment a source table is chosen for
ingestion. What a person actually draws is which tables to ingest, and
how silvers combine into a type -- and every arrow they do draw then
carries a real decision.

## 3.4 Honest status per layer, not theatre

PRECEDENT: Dagster ships asset-graph nodes with health overlays, and
Fivetran-style tooling gates on connector freshness. Live status on
nodes is well trodden.

THE CAVEAT: ONLY A SOURCE HAS A HEARTBEAT. A bronze table is not a
connection; it has a last-written time and a row count. A pulsing
"live" dot on a table would be theatre, and theatre in a status
display is worse than no display, because it is believed.

WHAT EACH LAYER CAN HONESTLY SAY, all of which Elysium already
computes:

    source   reachable now (the startup check, patch 325), and when
             it was last read successfully
    bronze   last written, row count, which snapshot
    silver   rules declared, rows warned, rows QUARANTINED and the
             rule that caught them (OPEN_RISKS.md item 1 -- this is
             the display that makes quarantine visible)
    gold     last publication, the audit's verdict, row count

## 3.5 Credentials: the mechanism already exists, and the canvas must
    use it rather than route around it

AUDITED, AND MY FIRST INSTINCT WAS WRONG. I assumed credentials never
touch the YAML. They do: data_silos.yaml holds "hosts, credentials,
paths", split from config.yaml precisely because connection details
"are often owned or secured differently in a real deployment". The
file is tracked in git.

BUT THE INDIRECTION EXISTS TOO, at deployment_loader.py's one place
where a connection block becomes live: ${VAR} is resolved from the
process environment, because a credential "belongs in the process
environment -- where systemd's EnvironmentFile=, a container's secret
mount and every CI system already put them -- rather than in a file
that lands in every backup and usually in version control".

  SO THE RULE FOR THE BUILDER: it may write an adapter choice, a host,
  a path, a database name and a ${VAR} REFERENCE. It must never write
  a literal secret, because it would be writing it into a tracked
  file. The node shows "credential: configured" or "missing", and
  offers TEST CONNECTION, which proves the secret works without
  revealing it.

## 3.6 Lanes, not a free canvas

The DAG is strictly layered, so position carries no meaning that the
layer does not already carry. Swimlanes -- sources, bronze, silver,
gold -- make the picture legible, make "which layer is this"
unambiguous, and remove the spaghetti a free canvas invites. Semantic
zoom (Dagster's "deeper zoom") shows fewer details as you pull back.

## 3.7 The dry run is already built

Gold writes to an audit branch and publishes only if the audit passes
(patch 341). A proposed pipeline change can therefore be BUILT on a
branch and shown -- sample rows, quarantine counts, audit verdict --
with nothing published until a person accepts. The builder does not
need a simulator; it needs to show what the audit branch produces.

## 3.8 And it stays separate from the ontology

The pipeline's subject is a PROCESS; the ontology's subject is
MEANING. They change at different rates and for different reasons --
a source migration touches one, a business definition the other.
Foundry keeps Pipeline Builder and Ontology Manager apart for the same
reason, with hydration tying them together.

CROSS-LINKED, THOUGH: a gold node opens its object type, and each
property in the ontology shows the silver column it came from -- which
the lineage columns (patch 340) now make possible.

