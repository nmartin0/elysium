# Architecture

How Elysium is put together and why. The short introduction is `README.md`; the reasoning behind decisions is `docs/principles.md`; the security model as built is `docs/security/architecture.md`.

Elysium answers questions — and, with permission, makes changes —
against your organization's data through an **ontology**: a semantic
layer of object types, fields, and links, declared once in YAML and
resolved live against your real databases at the moment they're
needed, standing between an LLM and your actual data. The model never
gets direct database access, and is never trusted to judge what it's
allowed to see or do on its own — see "The security model" below for
how that's actually enforced.

**One server instance runs one organization's data.** This is a
single-tenant design: there is no shared store to misconfigure and no
row-level tenancy filter to forget.

## What a question actually does

A question travels down through four stages and comes back as an
answer the asking user was allowed to receive:

```
your databases          primary_sql, risk_db, ... — declared in
    |                   data_silos.yaml. Elysium only ever READS them.
    v
bronze                  one Iceberg table per real source table, 1:1,
    |                   ingested as-is with no preprocessing.
    v
silver                  the same tables at the same grain with the
    |                   source's column names — typed, standardised,
    |                   and schema drift reported.
    v
gold                    THE SHAPE CHANGES. One table per OBJECT TYPE,
    |                   keyed by the object's id, using the ontology's
    |                   property names. A type spanning two silos is a
    |                   declared join. Written to a branch, audited,
    |                   published by one commit — a reader never sees
    v                   half a build.
the ontology            object types, fields, links, and the grant
                        each field requires. This is what a question
                        is asked against, and the only layer you write.
```

A write travels the other way: the model proposes, a person approves,
and the **approver's** own permissions are re-checked at the moment of
approval — not the asker's, and not the ones anybody held when the
proposal was made.

## How the system is organized

```
src/elysium/core/            Generic engine, built around the **ontology** --
                 src/elysium/core/ontology/'s own semantic schema layer (object
                 types, fields, links) resolved live against your real
                 databases, never a materialized copy -- see section
                 3.3 for the full concept, including multi-datasource
                 object types (one object type spanning more than one
                 physical database). No knowledge of any organization,
                 any specific database technology, or any specific LLM
                 backend.
src/elysium/adapters/        Concrete backends -- one file per real technology
                 (SQLite, SQLAlchemy, Ollama, vLLM, the Claude Agent SDK). src/elysium/core/ only ever
                 talks to these through a generic contract.
src/elysium/functions/       Stateless computational capabilities the LLM may
                 invoke (e.g. linear regression) -- zero data access.
src/elysium/api/             The HTTP layer -- session-based auth, user
                 management, the query endpoint, and the two-phase
                 write-confirmation flow. Knows FastAPI exists; src/elysium/core/
                 never does.
deployment/      YOUR organization's configuration and data, for local
                 development -- laid out to mirror a real install
                 exactly:
                   deployment/etc/       config.yaml, data_silos.yaml,
                                         source_bindings.yaml,
                                         ontology_schema.yaml,
                                         policy.yaml, example_queries.yaml
                   deployment/var/lib/   credentials.db, dev_fixtures/
                   deployment/var/log/   audit.log
                 A real install (see install/) uses /etc/elysium,
                 /var/lib/elysium, /var/log/elysium instead -- the SAME
                 three-location model, not a different one. See
                 src/elysium/core/deployment_loader.py's resolve_runtime_paths().
templates/       Copy-and-edit starting points for the five deployment/
                 YAML files, using a realistic Employee/ExpenseReport
                 example -- genuinely runnable, not just illustrative
                 prose. See docs/configuration.md.
ui/              The React + TypeScript frontend -- Query (ask a
                 question), Browse (search + per-object detail view),
                 and Admin (user management), sharing one login/session
                 flow. An npm workspace, one package per real screen or
                 shared concern, not one monolithic app:
                   ui/src/               App.tsx (auth state, routing,
                                         what's fetched once and passed
                                         down), Shell.tsx (what Elysium
                                         hands the shell's frame, in
                                         shell/), main.tsx (entry point).
                   ui/packages/shell-api/  Shared across every screen:
                                         the one place that knows about
                                         fetch/session/CSRF (api.ts),
                                         display-formatting helpers
                                         (format.ts), LoginForm,
                                         PendingWriteCard (the two-phase
                                         write confirmation UI).
                   ui/packages/app-query/    QueryPanel -- the LLM
                                         question/answer screen.
                   ui/packages/app-browse/   ObjectSearchPanel (live,
                                         debounced search) and
                                         ObjectDetailPanel (a real,
                                         bookmarkable per-object page,
                                         with direct action invocation
                                         via forms -- no LLM involved).
                   ui/packages/app-admin/    AdminPanel -- create/
                                         disable/enable/delete users,
                                         inspect a user's own visible
                                         schema.
                   ui/packages/app-schema/, app-inbox/,
                   app-approvals/, app-identity/,
                   app-notifications/  -- the other five screens;
                                         docs/development.md, "The front end", lists all ten
                                         packages.
src/elysium/scripts/         Runnable entry points.
install/         install.sh (fresh-install script) and elysium.service
                 (systemd unit) for a real, running install.
tests/           Unit tests (fast, no LLM) and integration tests --
                 tests/integration/fixtures/ is its OWN, fully
                 independent test deployment, deliberately decoupled
                 from deployment/'s real, shipped demo data.
```

The core idea: **`src/elysium/core/` never changes for your organization, and never
changes based on which database or LLM you use, or whether it's running
from a checkout or a real install.**

---

## The security model, in one paragraph

The LLM is treated as **completely untrustworthy** — a fluent but
unaccountable component that must never be allowed to make a security
decision itself. It cannot check its own permissions, filter its own
output, or decide what it may access. It doesn't even *know* what it
isn't allowed to see: the ontology it's shown is filtered per-user
before it ever reaches the model, so unauthorized object types,
fields, and tools simply don't appear to exist. Every actual decision
— what's visible, what's writable, what's callable — is made by plain
Python code the LLM never touches, checked fresh on every single
access, and logged whether allowed or denied. `docs/configuration.md` explains
exactly how to configure this for your organization; the section
below explains why it's built this way.

---

## Why it's built this way — the untrusted-LLM design, point by point

These same rules generalize past just the LLM boundary into a real,
project-wide security posture -- see `docs/principles.md`'s own "Security
is explicit, fail-safe, and never inferred" section.

- **The LLM never sees a schema element it isn't authorized for.**
- **"Doesn't exist" and "exists but denied" are indistinguishable**, on purpose, everywhere.
- **Error messages never reveal what's actually valid.**
- **Tools require their own explicit authorization**, separate from data access.
- **Every access decision is logged**, allowed or denied, with MAC and RBAC broken out independently.
- **All I/O is gated.** The LLM only ever receives text back from `LLMAdapter.chat()`.
- **No inference of intent.** Malformed or unrecognized model output fails closed.
- **Fail-safe defaults everywhere.** A user with no role, or a role missing a specific grant, is denied — never implicitly allowed.
