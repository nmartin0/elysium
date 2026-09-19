# Third-party extensions — a design

**The goal**: a third party ships a sub-app with its own backend, its
own adapter to an external source, and a UI inside Elysium. Their data
reaches the mirror and becomes available system-wide. They can ask the
Elysium agent questions.

**The constraint**: every third-party component is treated as
UNTRUSTED, and therefore as potentially HOSTILE. So is every
first-party component, because a privileged path that exists for
"our" code is a privileged path.

Nothing in this file is built.

---

## What Elysium already has, measured

**THE DATA BOUNDARY ALREADY EXISTS AND IS CLEAN.** 117 imports from
`@elysium/shell-api` across the five panels, and NOTHING else reaches
past it for data -- no direct `fetch`, no shared state, no back
channel.

**NO PANEL IMPORTS ANOTHER.** Zero. Cross-panel interaction today is
navigation -- a URL, not a function call. The discipline already holds
by accident; this design makes it hold by construction.

**THE COUPLINGS THAT REMAIN ARE UI, NOT DATA:**

    @elysium/shell-api   117 imports   the channel, already the only
                                       data path
    @blueprintjs/core     27           shared component library
    react                 19           shared runtime
    react-router-dom      42 uses      NAVIGATION IS DIRECT --
                                       Link (29), useNavigate (4),
                                       useLocation (4), useParams (3)

The API surface is 49 exports; panels use about 40.

**AND A SILO IS ALREADY JUST A DECLARATION:**

    primary_sql:
      adapter: sqlite
      connection: { path: "..." }

That last fact decides most of this document.

---

## MODULE FEDERATION IS OUT, and this is the most important finding

A federated module runs **in your page, in your origin**. It gets the
same DOM, the same cookies, the same `localStorage`, and the same
authenticated access to every `/api/*` route as Elysium itself.

The federation frameworks say so themselves -- they "do not claim that
same-realm JavaScript is a security sandbox". Their own comparison:

    DOM          no JS isolation    TRUSTED apps sharing a design system
    Shadow DOM   no JS isolation    TRUSTED code needing style containment
    iframe       separate realm     LOWER-TRUST applications

A real project shipping exactly this -- plugin bundles `import()`-ed
into the host origin -- has it filed as sev:high, noting "app UI code
gets the same DOM, the same document.cookie... as the dashboard
itself".

**Federation is the mechanism for code you trust.** It is disqualified
by the premise, not merely risky.

**AND THE IFRAME TRAP IS WORTH KNOWING NOW:** `allow-scripts` together
with `allow-same-origin` is a documented NO-OP -- the framed document
can reach its parent and remove its own sandbox attribute. Several
projects have shipped that pair believing it isolated something.

---

## The pattern to copy: JSON-RPC 2.0 over postMessage

Three independent major implementations converged on the same shape:

- **MCP Apps** (SEP-1865, stable 2026-01-26, official in the
  2026-07-28 release): "JSON-RPC 2.0 over postMessage for iframe-host
  communication".
- **Salesforce UI Embedding**: handshake over `window.postMessage`,
  host transfers a `MessagePort`, everything after is JSON-RPC 2.0.
- **Google embedded checkout**: the same two-phase shape.

The two phases matter: the handshake is public, then the host hands
over a PRIVATE port. And every implementation says the same thing --
"you must validate the origin of every message".

---

## The principle, and its name

**"No ambient authority anywhere in the system, by construction."**

The underlying rule is the **principle of least authority**: every
process holds the minimum authority required to do its job and nothing
more. The critique of how everyone else does it is blunt -- "modern
runtimes turn that principle on its head, making authority the default
and restriction the exception".

Capability systems go further: "the only access logic is 'does the
process have the capability'. There is no ambient authority, and thus
no global name spaces."

**AND AN HONEST WARNING FROM THE SAME LITERATURE:** doing this right
is "a difficult design/research problem". This is a multi-session body
of work.

---

# The design

## Data IN: a third-party adapter is a SILO

**THE MIRROR PIPELINE IS ALREADY THE SANDBOX FOR FOREIGN DATA.**

Bronze takes anything, as strings. Silver refuses anything that does
not match the declared ontology, keeping its previous snapshot. MAC
governs who sees the result. The drift policy reports what was
refused, and the mirror panel shows it.

That is the pipeline Elysium built for data it does not control, and
**a hostile adapter has no more power than a compromised source
database** -- a threat already modelled thoroughly.

So: do not invent a plugin data path. Their adapter is a silo with a
different transport. Out-of-process, speaking the adapter protocol
(`find_ids`, `read_fields`, `columns_present`), with no reach into the
mediator, the audit log or the approvals queue.

Almost no new machinery, and every existing guard applies unchanged.

## Ontology: declared fragments. DATA, NOT CODE

A plugin contributing object types, actions and links is shipping
YAML. It goes through the same validation a deployment's own config
does -- including the effect-reachability check. **Nothing the plugin
wrote ever runs**, so there is nothing to sandbox.

And per the constraint agreed in SECURITY_ARCHITECTURE.md, this gets
the plugin agent awareness, MAC, approvals and audit for free, with no
second implementation of any of them.

## Data OUT: the channel, and nothing else

Every request an app may make, written down as JSON-RPC methods rather
than function imports. Roughly the 40 calls the panels already make.

- **Every request is authorised by the shell**, not the caller. The
  app says "I want Customer cust_001"; the shell decides.
- **An app declares what it needs** in a manifest. Anything undeclared
  is REFUSED, not ignored.
- **The identical channel serves first-party and third-party.** No
  privileged methods, no bypass, no vetted tier.

## Cross-app: intents, not calls

"Open this Customer in Browse" is a REQUEST TO THE SHELL, not a call
into Browse. Hub, not mesh.

**The precedent is Android intents:** an app declares what it wants,
the system routes it and may refuse. Every cross-app request passes
one place that can check and log it -- strictly more auditable than
today, where a `<Link to="/objects/...">` is invisible.

**WHAT NOT TO OFFER: embedding another app's UI inside yours.** That
is composition, and it means handing over components, which means
sharing a realm, which is where we came in. They can navigate to
Browse, or render their own table from data they asked for.

## The agent: a channel method, running as the user

A sub app may ask the agent questions. The agent runs AS THE USER,
with the user's grants, through `check_access` like everything else,
so a sub app cannot exceed what the user could already do.

**Declared in the manifest, and attributed to BOTH the app and the
user in the audit log.**

---

# Build order

### Step 1 — Define the channel, and make it the only path

Write down the complete set of requests an app may make. Ship it
IN-PROCESS: `shell-api` becomes a thin client over the channel, panels
change almost not at all, nothing is isolated yet.

**NAVIGATION IS THE REAL WORK.** 42 direct router uses become
`navigate` requests the shell decides on. An app that can call
`useNavigate` can send a user anywhere; an app that must ASK cannot.

### Step 2 — Make the channel a contract rather than a convenience

Manifests, refusal of undeclared methods, one vocabulary for everyone.

At this point the principle holds -- no ambient authority, no
privileged path -- with a working UI and no rewrite.

### Step 3 — Isolation becomes a transport switch

`iframe`, `sandbox="allow-scripts"` WITHOUT `allow-same-origin`,
separate origin, `MessagePort` after handshake.

**Because the channel is already the only path, the app does not
change.** First-party panels can stay in-process while third-party
ones are framed, and neither knows the difference.

### Deliberately not first

**Not iframing the first-party panels yet.** The boundary is worth
nothing until the channel exists, and building isolation around an
API that turns out to be inadequate means doing both twice.

---

# What this does NOT protect against

**PLAUSIBLE-BUT-WRONG DATA.** An adapter returning well-typed lies
passes silver. No sandbox fixes that and nothing here should claim to.

**WHAT THE ADAPTER LEARNS.** It sees which ids Elysium asks for, and
when. An adapter with network access could report those patterns
home. A genuine side channel, named here rather than discovered.

**AGENT REACH.** A sub app calling the agent gets everything the user
is entitled to. No escalation, but plenty of reach -- a hostile app
could extract data the user COULD see but never would have asked for.
The mitigation makes it visible and attributable, not impossible.

**VOCABULARY CREEP**, which is the slow one. If "things one app may
ask" grows to cover everything, it becomes a back door by accretion --
not because anyone opened one, but because enough small requests add
up to arbitrary access. The vocabulary should be reviewed AS A WHOLE,
periodically, the way the workaround audit reviews suppressions,
because each addition looks reasonable alone.

---

# Installation

**pip is the package manager.** Python's standard mechanism is entry
points: a plugin declares itself in its own `pyproject.toml`, and the
host discovers it with `importlib.metadata.entry_points()`.

Installation is `pip install elysium-plugin-whatever`. No registry to
build, no installer to write. The advice from the research is blunt:
"you should never design a plugin framework from scratch."

The three hardcoded registries in `deployment_loader.py` become
"hardcoded entries PLUS whatever entry points declare".

---

# The shape, in one line

**They hand us data through the front door and ask us questions
through the letterbox. They never get a key.**
