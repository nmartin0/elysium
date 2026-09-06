# Installing and running Elysium

Setup, running it locally, running the test suites, code quality
tooling, and a real production install — in that order. See
`README.md` for the architecture, the security model, and how to
configure it for your own organization; see `PRINCIPLES.md` for the
real, recurring engineering discipline behind how this project is
actually built and reviewed; this file is purely operational.

---

## 1. Prerequisites

- **Python 3.10 or later**
- **Node.js 22.22.2 or later (22.x, 24.15.0+, or 26+)** for the `ui/` frontend -- see `ui/package.json`'s own `engines` field for the exact, binding constraint (driven by `jsdom`'s own requirement). If you use `nvm`, `ui/.nvmrc` picks the right version automatically (`nvm use`, from inside `ui/`).
- **[Ollama](https://ollama.com)** installed and running locally
- Enough free RAM for whatever model you choose to run

---

## 2. Installation (local development)

```bash
git clone <your-repo-url>
cd <repo-directory>

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1

pip install -r requirements.txt

cd ui && npm install && cd ..
```

For a real, running production install, see section 7 instead.

---

## 3. Setting up Ollama

```bash
ollama pull phi4-mini      # example: step-selection model
ollama pull qwen2.5:3b     # example: answer-synthesis model
```

Smaller, "reasoning-flavored" models have generally worked better for
step-selection than larger general-purpose ones — this is genuinely
trial-and-error; try a model, run the test suite, see how it does.

---

## 4. Running the included example

```bash
python3 -m scripts.run_deployment
```

No arguments — config, data, and logs are all resolved automatically.
Runs a few example questions through the full pipeline and prints the
answers.

---

## 5. Running the tests

```bash
# Fast -- no LLM, no network, run these constantly while developing
python3 -m pytest tests/unit/ -v

# Slow -- real LLM calls against tests/integration/'s own isolated fixture
python3 -m pytest tests/integration/ -v -m integration

# api/ layer -- real FastAPI TestClient, mocked LLM, no Ollama needed
python3 -m pytest tests/integration/test_api.py -v
```

The `ui/` frontend has its own, separate suite — real user flows
through React Testing Library (typing, clicking, waiting for a real
async response), not shallow rendering:

```bash
cd ui && npm test
```

---

## 6. Code quality: linting, type checking, dead code, import boundaries

```bash
pip install -r requirements.txt -r requirements-dev.txt

./lint.sh
```

Four separate tools, each catching something genuinely different — see
`lint.sh`'s own top comment for why each one earns its place, and
`pyproject.toml`'s `[tool.ruff.lint]`, `[tool.mypy]`, and
`[tool.importlinter]` sections for the specific configuration and
reasoning behind each. In short: Ruff (style, real Python gotchas,
import order), MyPy (does the types agree), Vulture (does anything
still use this), Import Linter (is this module even allowed to import
that one — the real, current architectural contracts live in
`pyproject.toml`'s own `[tool.importlinter]` section, mapped directly
against this project's real import graph, not designed from
assumption).

`ruff format` is intentionally never run by `./lint.sh` or anywhere
else — see `pyproject.toml`'s own `[tool.ruff]` section for why.

The `ui/` frontend has its own, separate tooling — a real, standing
`tsc --noEmit` type check (not optional or best-effort; TypeScript
throughout, `strict: true`), style/correctness (`oxlint`), dead-code
detection for files/exports/dependencies (`knip`), and formatting
(`oxfmt`):

```bash
cd ui
npm run lint          # oxlint, then tsc --noEmit
npm run knip
npm run format:check  # verify without changing anything
```

See `ui/README.md`'s own "Testing, linting, and type checking" section
for the full breakdown, and `ui/tsconfig.json`'s own comments for the
specific compiler options chosen and why.

---

## 7. Installing as a real, running service

`install/install.sh` (run as root, from a checked-out copy of this
repository) sets up a genuine production install:

- A dedicated **system user and group** (`elysium`), no login shell —
  the service runs unprivileged, under its own identity, never as the
  human who ran the install.
- The **FHS layout** — `/opt/elysium` (code + venv), `/etc/elysium`
  (config), `/var/lib/elysium` (data — `700` permissions, no group
  access at all, since this is where `credentials.db` lives),
  `/var/log/elysium` (logs).
- A **systemd service** (`install/elysium.service`) running
  `uvicorn api.app:app` under the `elysium` user, bound to
  `127.0.0.1` by default.
- **Root bootstrap** — a real, cryptographically random password,
  generated once, printed once (never a hardcoded default).

```bash
sudo ./install/install.sh
sudo systemctl start elysium.service
```

### Where this deviates from POSIX, explicitly

This install script's **shell syntax** is POSIX `sh` throughout, but
several **commands** it calls are Linux-specific, with no POSIX
equivalent: **systemd** (not part of POSIX at all), **the FHS layout
itself** (a Linux Foundation convention, not POSIX-mandated),
**`useradd`/`groupadd`/`getent`** (from `shadow-utils`/glibc, not
POSIX-specified), and **`$SUDO_USER`** (`sudo`-specific).

## 8. Keeping the local mirror in sync

Elysium can serve reads from a local mirror of your data rather than
querying your databases on every request. The mirror is populated by
a sync, which you run on a schedule.

```bash
python3 -m scripts.run_sync
```

One run copies every table your ontology references — across every
silo — into Elysium's own local storage, then exits. It is a
deliberately separate process, not something the web server does in
the background: a sync copies whole tables, and running that inside
the request-serving process would make it compete with real user
requests for the same CPU.

**Schedule it however you already schedule things.** A cron entry, a
systemd timer, a Kubernetes CronJob — Elysium has no opinion, and no
scheduler of its own. Running the command by hand is also the "sync
now" escape hatch; there is no separate mechanism for it.

**What it syncs is derived from your ontology**, not from a separate
list you maintain. Add a field or an object type, and the next sync
picks it up. There is nothing to keep in step by hand.

**It cannot write to your data.** The sync reads through the same
structurally read-only connection described in the next section.

**Failures are per-table and loud.** If one table fails, the others
still sync, that table keeps its last good copy rather than being
left half-written, the real error is printed, and the process exits
non-zero so your scheduler notices. A silent partial sync is the one
outcome this is designed to prevent.

```
synced  primary_sql.customers: 4 rows at 2026-01-15T09:00:01+00:00
FAILED  risk_sql.customer_risk: no such table: customer_risk
4/5 tables synced successfully.
```

**Anyone can check how current the data is.** `GET /api/data-freshness`
reports whether reads are live or mirror-backed and, if mirrored, when
the last sync completed. It needs a login but no particular permission,
since it exposes no business data. Elysium also shows a warning
directly on any pending change awaiting approval when reads come from
the mirror, so nobody approves a write without knowing how fresh the
values they are looking at actually are.

**Overlapping runs are handled for you.** If a sync is still running
when the next one is triggered, the second exits immediately with a
message on stderr and a success code — it does not queue, and it does
not fail your scheduler. This matters because the mirror's storage
format rejects two simultaneous writers to the same table by design,
so without this guard an overlapping run would fail partway through.

**Do not run Elysium with `-O` or `PYTHONOPTIMIZE`.** Several
data-integrity checks are enforced by Python assertions, which those
options strip. Elysium refuses to start if they are set, and tells you
so — but it is worth knowing why before you reach for them: the
failures those checks catch do not get louder without them, they get
silent.

**A note on paged results.** Endpoints that return lists are paged:
the response carries a `next_page_token`, and you pass it back to get
the next page. Treat the token as opaque — its format will change, and
anything that parses it will break. Results reflect the data as it is
at the moment each page is fetched, so if rows are being written while
you page through them, you may see an item twice or miss one. That is
fine for browsing and wrong for an export; for an export, read the
data once rather than paging a moving target.

### Choosing a sync interval

There is no correct default, because the right answer depends on your
data rather than on Elysium. What follows is the actual trade-off, so
you can decide rather than guess.

**Reads served from the mirror are only as fresh as the last sync.**
If you sync hourly, someone reading at 10:59 may be looking at data
from 10:00. Whether that matters depends entirely on the field: a
customer's name changing an hour late is usually fine; an account
balance is often not.

**Writes are unaffected.** They always go to your real database,
live, and a confirmed write is visible immediately even from the
mirror — Elysium overlays recently-applied writes on top of mirror
reads until the next sync catches up. So the interval affects how
quickly you see changes made *outside* Elysium, not changes made
through it.

**The cost of syncing more often** is load on your database and the
time each sync takes. A sync reads every row of every table your
ontology references, so the duration scales with your data size, and
running it every minute against a large table is real, repeated work.

A reasonable way to decide: start with an interval you are confident
is safe (many deployments find 15 minutes to an hour comfortable),
watch how long a sync actually takes from the output, and shorten it
only if genuine staleness complaints appear. Lengthening it later is
easy; discovering that hourly was too slow after someone acted on
stale data is not.

**If any field genuinely cannot tolerate staleness**, the honest
answer is to leave `read_from_mirror` off for that deployment rather
than sync aggressively. Live reads have no staleness at all, and the
mirror's benefits — speed, and surviving a database outage — may not
be worth it for your case.

## 9. Data-access security: what Elysium guarantees, and what you must configure

Elysium reads from *your* databases. This section states plainly what
the software guarantees on its own, and what it cannot guarantee
without configuration on your side. Both halves matter; neither alone
is the whole picture.

### What Elysium guarantees in code, with no configuration from you

**The read path cannot write to your data.** Elysium's read path
(everything the LLM does, all browsing and search) uses a connection
that is structurally incapable of writing. This is enforced by SQLite
itself, not by convention: an `UPDATE`, `DELETE`, or `DROP` issued
through that connection is refused by the database engine, even if it
somehow originated from a bug inside Elysium's own code. See
`tests/unit/test_external_read_adapter_is_read_only.py`, which proves
this directly by attempting raw writes and confirming they are
refused.

**Writes only happen through an explicit, human-approved path.** The
only code that can write to your data is the action system, and every
write goes through a two-phase propose/confirm flow: the LLM can
*propose* a change, but nothing is applied until a human with the
right permissions approves it. Permission checks (RBAC and MAC) run
in Python before either phase.

### What you must configure, because Elysium cannot enforce it alone

**Use a read-only database account for the read connection, if your
database supports one.** SQLite has no concept of database users or
`GRANT`s at all — a "connection" is just a file path — so for SQLite
silos, the code-level guarantee above is the whole story. For any
server-backed database (PostgreSQL, MySQL, and similar), the account
Elysium connects with should be granted `SELECT` only, and nothing
else, on exactly the tables your ontology references.

This is not redundant with the code-level guarantee — it is the more
important of the two. A database-enforced permission holds regardless
of what any application does, including one with a bug. Application
code is the second layer, not the first. This mirrors the practice
Palantir documents for Foundry, whose own documentation warns plainly
that a sync "can change the source system if the source credentials
allow it — for instance... dropping data from a database via
arbitrary SQL." The credential is the real boundary.

**A note on scope:** Elysium currently ships a SQLite adapter only.
When a server-backed adapter is added, its configuration in
`data_silos.yaml` will accept real connection credentials, and this
is the point at which the guidance above becomes directly actionable.
Until then it is recorded here so the requirement is not discovered
late.
