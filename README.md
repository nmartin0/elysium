# Elysium

An LLM-driven system for answering questions — and, with permission,
making changes — against your organization's data, without giving the
model direct database access, and without trusting the model's own
judgment about what it's allowed to see or do.

**One server instance runs one organization's data.** This is a
single-tenant system.

---

## 1. How the system is organized

```
core/            Generic engine. No knowledge of any organization, any
                 specific database technology, or any specific LLM
                 backend.
adapters/        Concrete backends -- one file per real technology
                 (SQLite, Ollama, an in-memory cache). core/ only ever
                 talks to these through a generic contract.
tools/           Stateless computational capabilities the LLM may
                 invoke (e.g. linear regression) -- zero data access.
api/             The HTTP layer -- session-based auth, user
                 management, the query endpoint. Knows FastAPI exists;
                 core/ never does.
deployment/      YOUR organization's configuration and data, for local
                 development -- laid out to mirror a real install
                 exactly:
                   deployment/etc/       config.yaml, ontology_schema.yaml,
                                         policy.yaml, example_queries.yaml
                   deployment/var/lib/   credentials.db, dev_fixtures/
                   deployment/var/log/   audit.log
                 A real install (see install/) uses /etc/elysium,
                 /var/lib/elysium, /var/log/elysium instead -- the SAME
                 three-location model, not a different one. See
                 core/deployment_loader.py's resolve_runtime_paths().
scripts/         Runnable entry points.
install/         install.sh (fresh-install script) and elysium.service
                 (systemd unit) for a real, running install.
tests/           Unit tests (fast, no LLM) and integration tests (slow,
                 real LLM calls, or the api/ layer via a real
                 TestClient).
```

The core idea: **`core/` never changes for your organization, and never
changes based on which database or LLM you use, or whether it's running
from a checkout or a real install.**

---

## 2. The security model, in one paragraph

The LLM is treated as **completely untrustworthy** — a fluent but
unaccountable component that must never be allowed to make a security
decision itself. It cannot check its own permissions, filter its own
output, or decide what it may access. It doesn't even *know* what it
isn't allowed to see: the schema it's shown is filtered per-user before
it ever reaches the model, so unauthorized tables, fields, and tools
simply don't appear to exist. Every actual decision — what's visible,
what's writable, what's callable — is made by plain Python code the LLM
never touches, checked fresh on every single access, and logged whether
allowed or denied. Section 8 explains exactly how to configure this for
your organization; section 11 explains why it's built this way.

---

## 3. Prerequisites

- **Python 3.10 or later**
- **[Ollama](https://ollama.com)** installed and running locally
- Enough free RAM for whatever model you choose to run

---

## 4. Installation (local development)

```bash
git clone <your-repo-url>
cd <repo-directory>

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

For a real, running production install, see section 10 instead.

---

## 5. Setting up Ollama

```bash
ollama pull phi4-mini      # example: step-selection model
ollama pull qwen2.5:3b     # example: answer-synthesis model
```

The included example uses two different models for two different jobs.
Smaller, "reasoning-flavored" models have generally worked better for
step-selection than larger general-purpose ones — this is genuinely
trial-and-error; try a model, run the test suite, see how it does.

---

## 6. Running the included example

```bash
python3 -m scripts.run_deployment
```

No arguments — config, data, and logs are all resolved automatically
(see section 8's note on `resolve_runtime_paths()`). Runs a few example
questions through the full pipeline and prints the answers.

---

## 7. Running the tests

```bash
# Fast -- no LLM, no network, run these constantly while developing
python3 -m pytest tests/unit/ -v

# Slow -- real LLM calls against the real deployment, run before trusting a change
python3 -m pytest tests/integration/ -v -m integration

# api/ layer -- real FastAPI TestClient, mocked LLM, no Ollama needed
python3 -m pytest tests/integration/test_api.py -v
```

---

## 8. Configuring your organization's deployment

Everything lives under `deployment/etc/`, `deployment/var/lib/`, and
`deployment/var/log/` locally — the exact same three-way split a real
install uses, just rooted under one project-relative folder instead of
`/etc/elysium`, `/var/lib/elysium`, `/var/log/elysium`. Nothing in
`core/` treats one of these as more "real" than the other —
`resolve_runtime_paths()` (in `core/deployment_loader.py`) is the one
place that decides where each actually is, defaulting to the
`deployment/` layout, overridable via `ELYSIUM_CONFIG_DIR`,
`ELYSIUM_DATA_DIR`, `ELYSIUM_LOG_DIR` (which is exactly what a real
install's systemd unit sets — see section 10).

### 8.1 `deployment/etc/config.yaml` — operational settings

```yaml
llm:
  provider: ollama
  connection:
    base_url: "http://localhost:11434/api/chat"
    request_timeout_seconds: 240
  step_model: "phi4-mini"
  synthesis_model: "qwen2.5:3b"

agent:
  max_hops: 8
  max_consecutive_duplicates: 2
  max_consecutive_invalid_steps: 2
  max_concurrent_requests: 4

data_silos:
  primary_sql:
    adapter: sqlite
    connection:
      path: "dev_fixtures/mediator.db"

tools:
  enabled:
    - linear_regression
```

| Field | What it controls |
|---|---|
| `llm.provider` / `llm.connection` | Which LLM adapter, and its own connection details (opaque to `core/`). |
| `llm.step_model` / `synthesis_model` | Which model handles step-selection vs. final answer writing. |
| `agent.max_hops` | Hard ceiling on steps per question. |
| `agent.max_concurrent_requests` | Thread pool size for `scripts/serve_requests.py`. |
| `data_silos` | Named data-silo instances — technology + connection details. `path`-style connection fields resolve against the DATA directory (`deployment/var/lib/` locally, `/var/lib/elysium/` under a real install), never the config directory. |
| `tools.enabled` | Which registered tools the LLM may call, by name. |

### 8.2 `deployment/etc/ontology_schema.yaml` — what data exists

```yaml
object_types:
  Employee:
    silo: primary_sql
    id_field: employee_id
    table: employees
    id_column: employee_id
    security:
      field: department
    fields:
      department:
        type: data
      full_name:
        type: data
      expense_reports:
        type: link
        target: ExpenseReport
        cardinality: many
        via_table: expense_reports
        via_column: employee_id
```

This declares what data **exists** and how it's structured — it does
**not** by itself make anything visible. Every field here, including
each type's own `id_field`, needs a matching grant in `policy.yaml`
before any user can see it. A field declared here with no matching
grant anywhere simply never appears to the LLM at all.

- **`silo`** — which named entry in `config.yaml`'s `data_silos`.
- **`id_field`** — the identifier's name. **Not automatically safe to expose** — some deployments use identifiers that are themselves sensitive (a password-reset token, a verification code), so this needs its own explicit grant like any other field.
- **`security`** — the MAC boundary for this type: `field: <column>` (carries its own boundary value) or `via_field: <link>` (inherits the linked object's).
- **`fields`** — `type: data` (plain value) or `type: link` (points to another object; `cardinality: one` is a real foreign key, `cardinality: many` is a reverse relationship needing `via_table`/`via_column`).

### 8.3 `deployment/etc/policy.yaml` — who your users are, and exactly what they can do

Two independent, both-required gates, and **everything is fully
explicit — nothing is inherited from anything else**:

```yaml
security_attribute: department

roles:
  admin:
    allowed_actions:
      - manage:users
  analyst:
    allowed_actions:
      - read:Employee
      - read:Employee.employee_id
      - read:Employee.full_name
      - read:Employee.department
  hr_admin:
    allowed_actions:
      - read:Employee
      - read:Employee.employee_id
      - read:Employee.full_name
      - read:Employee.department
      - read:Employee.ssn
      - write:Employee.department
      - create:Employee
      - tool:linear_regression

users:
  alice:
    department: engineering
    role: analyst
  bob:
    department: hr
    role: hr_admin
```

- **`security_attribute`** — the *mandatory* boundary (MAC). A user can never see data outside their own value for this field, regardless of role.
- **`roles`** — the *role-based* layer (RBAC), always static and human-authored here — see the table below. `manage:users` (the `admin` role above) is what lets someone create real, database-backed logins via `api/`'s `/users` endpoint — see section 9.
- **`users`** — this static section is what `scripts/run_deployment.py` (a simple demo/dev tool) uses directly. The real, running service (`api/`) never reads this section at all — see section 9 for why.

| Action pattern | Grants |
|---|---|
| `read:<Type>` | May discover/search objects of this type at all. Does **not** grant seeing any field's value. |
| `read:<Type>.<field>` | May see this **one specific field's** value. Required for every field, including the identifier. |
| `write:<Type>.<field>` | May change this one field on an existing object. All fields in a write need their own grant — missing even one denies the whole write. |
| `create:<Type>` | May bring a new object into existence. Still needs `write:<Type>.<field>` for every field being set. |
| `tool:<name>` | May invoke this specific tool. |
| `manage:users` | May create new database-backed users via `api/`'s `/users` endpoint. |

This is deliberately verbose. That verbosity is the point — every one
of those lines is a decision someone made on purpose, not a default
nobody thought about.

### 8.4 `deployment/etc/example_queries.yaml` and `deployment/var/lib/`

`example_queries.yaml` is `user_id`/`query` pairs for
`scripts/run_deployment.py`'s demo. `deployment/var/lib/dev_fixtures/`
holds the local SQLite fixture — see `schema.sql` there for the
`CREATE TABLE`/`INSERT` pattern to follow for your own data.
`credentials.db` (real login credentials, real sessions) lives here
too, created fresh the first time anything writes to it — never
shipped, never copied between environments (see section 10's note on
why the install script is careful about this specifically).

---

## 9. Two ways to run this: `scripts/run_deployment.py` vs. `api/`

These are **intentionally not unified**:

- **`scripts/run_deployment.py`** is a simple demo/dev tool. It reads
  users directly from `policy.yaml`'s static `users:` section — no
  login, no password, just a list of example questions run as each
  named user in turn.
- **`api/`** is the real, running HTTP service. It never reads
  `policy.yaml`'s `users:` section at all — every user is a real
  login, created via `core/user_directory.py` (database-backed,
  runtime-mutable) and authenticated via `core/auth/` (argon2id
  password hashing, session tokens). See section 10 for how the very
  first user gets created.

```bash
# Local dev, against the venv from section 4:
uvicorn api.app:app --reload
```

Writes are **not** wired up in `api/` yet — a real HTTP write flow
needs its own two-phase design (propose, then a separate confirm
step), deliberately deferred rather than improvised on top of a
terminal `input()` prompt that has no meaning for a remote caller.

---

## 10. Installing as a real, running service

`install/install.sh` (run as root, from a checked-out copy of this
repository) sets up a genuine production install:

- A dedicated **system user and group** (`elysium`), no login shell —
  the service runs unprivileged, under its own identity, never as the
  human who ran the install. That human is added to the `elysium`
  *group* instead, so they can inspect logs/config without being the
  service account.
- The **FHS layout** — `/opt/elysium` (code + venv), `/etc/elysium`
  (config), `/var/lib/elysium` (data — `700` permissions, no group
  access at all, since this is where `credentials.db` lives),
  `/var/log/elysium` (logs).
- A **systemd service** (`install/elysium.service`) running
  `uvicorn api.app:app` under the `elysium` user, bound to
  `127.0.0.1` by default (put a real reverse proxy in front for
  anything beyond localhost).
- **Root bootstrap** — since there's no existing user who could call
  the `/users` endpoint to create the first one, the install script
  runs `scripts/bootstrap_root.py` once, generating a real,
  cryptographically random password (never a hardcoded default) and
  printing it exactly once.

```bash
sudo ./install/install.sh
sudo systemctl start elysium.service
```

### Where this deviates from POSIX, explicitly

This install script's **shell syntax** is POSIX `sh` throughout — no
bash-only features — but several of the **commands** it calls are
Linux-specific, with no POSIX equivalent:

- **systemd** — not part of POSIX at all; other Unix-likes use
  entirely different service-supervision mechanisms.
- **The FHS layout itself** — a Linux Foundation convention, not a
  POSIX-mandated directory hierarchy.
- **`useradd`/`groupadd`/`getent`** — from `shadow-utils`/glibc,
  near-universal on Linux, but not POSIX-specified; BSD and macOS use
  different tools entirely (`pw`, `dscl`).
- **`$SUDO_USER`** — a `sudo`-specific mechanism, absent under `su`/`doas`.

Porting this install to a non-Linux POSIX system means rewriting these
specific sections, not just adapting syntax.

---

## 11. Extending the system

| To add... | Implement | Register in |
|---|---|---|
| A new database technology | `core/ontology/interface.py`'s `DataSiloAdapter` | `core/deployment_loader.py`'s `_ADAPTER_REGISTRY` |
| A new LLM backend | `core/llm/interface.py`'s `LLMAdapter` | `core/deployment_loader.py`'s `_LLM_ADAPTER_REGISTRY` |
| A new tool | `core/tools/interface.py`'s `Tool` | `core/tools/registry.py`'s `_TOOL_REGISTRY` |

Tools must be strictly stateless — pure data in, data out, zero access
to the database, network, or filesystem.

---

## 12. Why it's built this way — the untrusted-LLM design, point by point

- **The LLM never sees a schema element it isn't authorized for.** `DataMediator.visible_schema()` filters every object type and every field, per user, before the prompt is even built. An unauthorized field isn't marked hidden — it's absent.
- **"Doesn't exist" and "exists but denied" are indistinguishable**, on purpose, everywhere.
- **Error messages never reveal what's actually valid.**
- **Tools require their own explicit authorization**, separate from data access — a user lacking it sees the identical error a genuinely nonexistent tool would produce.
- **Every access decision is logged**, allowed or denied, with MAC and RBAC broken out independently.
- **All I/O is gated.** The LLM only ever receives text back from `LLMAdapter.chat()`.
- **No inference of intent.** Malformed or unrecognized model output fails closed.
- **Fail-safe defaults everywhere.** A user with no role, or a role missing a specific grant, is denied — never implicitly allowed.

---

## 13. Known limitations, honestly

- **Memory security infrastructure exists but isn't wired into the live query path.** `core/memory/guard.py`'s `MemoryGuard` is built and tested, but `AgentLoop` doesn't currently construct or use one.
- **Cross-silo links aren't supported.** Linked object types must currently share a data silo.
- **Single OS process.** Concurrency protections coordinate threads within one process, not across separate processes.
- **Writes aren't wired up in `api/` yet.** See section 9.
- **`install.sh` is a fresh-install script, not an upgrade mechanism.** Re-running it will not corrupt existing data, but it isn't designed to migrate an existing install.

None of these are silent gaps — each is a deliberate, documented scope
decision.
