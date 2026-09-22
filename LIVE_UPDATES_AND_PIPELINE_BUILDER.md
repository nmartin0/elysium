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
