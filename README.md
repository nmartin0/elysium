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
                 management, the query endpoint, and the two-phase
                 write-confirmation flow. Knows FastAPI exists; core/
                 never does.
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
templates/       Copy-and-edit starting points for the four deployment/
                 YAML files, using a realistic Employee/ExpenseReport
                 example -- genuinely runnable, not just illustrative
                 prose. See section 8.
scripts/         Runnable entry points.
install/         install.sh (fresh-install script) and elysium.service
                 (systemd unit) for a real, running install.
tests/           Unit tests (fast, no LLM) and integration tests --
                 tests/integration/fixtures/ is its OWN, fully
                 independent test deployment, deliberately decoupled
                 from deployment/'s real, shipped demo data.
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
your organization; section 12 explains why it's built this way.

---

## 3. Prerequisites

- **Python 3.10 or later**
- **Node.js 22.22.2 or later (22.x, 24.15.0+, or 26+)** for the `ui/` frontend -- see `ui/package.json`'s own `engines` field for the exact, binding constraint (driven by `jsdom`'s own requirement). If you use `nvm`, `ui/.nvmrc` picks the right version automatically (`nvm use`, from inside `ui/`).
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

Smaller, "reasoning-flavored" models have generally worked better for
step-selection than larger general-purpose ones — this is genuinely
trial-and-error; try a model, run the test suite, see how it does.

---

## 6. Running the included example

```bash
python3 -m scripts.run_deployment
```

No arguments — config, data, and logs are all resolved automatically.
Runs a few example questions through the full pipeline and prints the
answers.

---

## 7. Running the tests

```bash
# Fast -- no LLM, no network, run these constantly while developing
python3 -m pytest tests/unit/ -v

# Slow -- real LLM calls against tests/integration/'s own isolated fixture
python3 -m pytest tests/integration/ -v -m integration

# api/ layer -- real FastAPI TestClient, mocked LLM, no Ollama needed
python3 -m pytest tests/integration/test_api.py -v
```

---

## 8. Configuring your organization's deployment

**Start from `templates/`** — five genuinely runnable YAML files (an
Employee/ExpenseReport example, verified end to end, not just
illustrative snippets) with the same explanatory comments this section
walks through. Copy them into `deployment/etc/`, confirm the pipeline
works with the example data, then replace the content with your own.

**Check your edits are valid before running anything:**
```
python3 -m scripts.lint_deployment
```
Validates `config.yaml`/`ontology_schema.yaml`/`policy.yaml` — every
action type's own structure, every role's own grants checked against
what they actually reference — without opening any real database
connection or creating any file on disk. Pass a different directory
(`python3 -m scripts.lint_deployment /path/to/candidate/config`) to
check a config before ever copying it into `deployment/etc/` at all.
Exits 0 if valid, 1 if not — usable in a pre-deploy CI step, not just
interactively.

Everything lives under `deployment/etc/`, `deployment/var/lib/`, and
`deployment/var/log/` locally — the exact same three-way split a real
install uses, just rooted under one project-relative folder instead of
`/etc/elysium`, `/var/lib/elysium`, `/var/log/elysium`. Nothing in
`core/` treats one of these as more "real" than the other —
`resolve_runtime_paths()` (in `core/deployment_loader.py`) is the one
place that decides where each actually is.

### 8.1 `config.yaml` — operational settings

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

tools:
  enabled:
    - linear_regression
```

| Field | What it controls |
|---|---|
| `llm.provider` / `llm.connection` | Which LLM adapter, and its own connection details (opaque to `core/`). |
| `llm.step_model` / `synthesis_model` | Which model handles step-selection vs. final answer writing. |
| `agent.max_hops` | Hard ceiling on steps per question. |
| `agent.max_concurrent_requests` | Thread pool size for `api/` and `scripts/serve_requests.py`. |
| `tools.enabled` | Which registered tools the LLM may call, by name. |

### 8.2 `data_silos.yaml` — where your data physically lives

```yaml
data_silos:
  primary_sql:
    adapter: sqlite
    connection:
      path: "dev_fixtures/mediator.db"
```

A separate file from `config.yaml`, deliberately — connection details
(hosts, credentials, paths) are a genuinely different kind of
configuration than operational tuning, and are often owned or secured
differently in a real deployment. Named data-silo instances —
technology + connection details, one entry per silo. `path`-style
connection fields resolve against the DATA directory, never the
config directory. Each object type in `ontology_schema.yaml` declares
which named silo it lives in via its own `silo:` key — this is what
lets a deployment span more than one adapter.

### 8.3 `ontology_schema.yaml` — what data exists

Declares what data **exists** and how it's structured — it does
**not** by itself make anything visible. Every field, including each
type's own `id_field`, needs a matching grant in `policy.yaml` before
any user can see it.

- **`silo`** — which named entry in `data_silos.yaml`.
- **`id_field`** — the identifier's name. **Not automatically safe to expose** — some deployments use identifiers that are themselves sensitive (a password-reset token, a verification code), so this needs its own explicit grant like any other field.
- **`title_field`** *(optional)* — which field's own value stands in as a human-readable display name in the UI's own Browse/Object View (e.g. "Ada Okafor," not a raw `cust_001`), instead of falling back to the identifier. Must reference a real, plain `type: data` field on this same type, or the `id_field` itself — checked at load time. Needs its own explicit `read:<Type>.<field>` grant like any other field before it's ever actually shown; declaring it here only says *which* field would be the title, it doesn't make that field's value visible on its own.
- **`security`** — the MAC boundary for this type: `field: <column>` (carries its own boundary value) or `via_field: <link>` (inherits the linked object's).
- **`fields`** — `type: data` (plain value) or `type: link` (points to another object; `cardinality: one` is a real foreign key, `cardinality: many` is a reverse relationship needing `via_table`/`via_column`).

See `templates/ontology_schema.yaml` for a complete, working example
demonstrating every one of these.

### 8.4 `action_types` — named, independently-governed operations

Declared in the same `ontology_schema.yaml`, alongside the object
types above. Matches Palantir Foundry's own action-type model
directly (verified against their docs, not assumed): a **named**
business operation with its own, independent authorization —
`execute:<ActionName>` — not a generic "update this field" capability
assembled from individual `write:<Type>.<field>` grants. The object(s)
an action touches are always just ordinary parameters, the same as
any other input — never a separate, out-of-band argument.

```yaml
action_types:
  UpdateEmployeeDepartment:
    affected_object_types: [Employee]
    parameters:
      employee_id:
        type: object_reference
        object_type: Employee
        required: true
      new_department:
        type: string
        required: true
    sub_writes:
      - object_type: Employee
        object_id: parameter.employee_id
        operation: update
        mutations:
          - set: {property: department, value: parameter.new_department}
```

- **`affected_object_types`** — every object type this action can
  touch, and **only** those — checked at schema-load time against
  what `sub_writes` actually references, in both directions. A type
  declared here but never touched by a real `sub_write`, or the
  reverse, fails to load at all: this list is read and trusted by
  whoever is deciding a role's real reach, so a stale declaration is
  exactly as misleading as a missing one.
- **`parameters`** — every input this action accepts, by name.
  `type: object_reference` (with its own `object_type`) is the only
  kind schema-load validation actually checks the shape of; `string`
  and `number` are used by this project's own UI to pick the right
  form input, but aren't independently validated beyond that — nothing
  stops a deployer from writing an arbitrary `type` string here today.
  `required: true` is enforced at proposal time: a required parameter
  missing from a real call is rejected before anything else runs.
- **`sub_writes`** — the actual change(s), one entry per object
  touched (see **RBAC** below for what more than one object type
  actually requires). Each needs:
  - **`object_type`** / **`object_id`** — which real object. `object_id`
    is usually `parameter.<name>`, referencing one of this action's
    own declared `object_reference` parameters (checked at load time
    that the reference is real and its own `object_type` matches) —
    but it can also be a literal value, or `user.security_value` (the
    *acting user's own* MAC value, substituted automatically — the
    only safe way for a `create` action to populate a security field:
    a literal would hardcode one tenant's value for everyone, and a
    `parameter.<name>` would let the caller choose any value at all).
  - **`operation`** — `create` or `update`.
  - **`mutations`** — a list of `{set: {property, value}}`. `property`
    must be one of the target type's own real, declared fields (or its
    `id_field`) — checked at load time, so a typo here fails loudly at
    startup, not the first time someone happens to invoke this action.
    `value` uses the exact same vocabulary as `object_id` above
    (literal / `parameter.<name>` / `user.security_value`).
  - **`submission_criteria`** *(optional)* — business-state rules that
    must hold before this specific sub-write proceeds, checked
    **in addition to** RBAC/MAC, not instead of them. Matches Palantir's
    own concept and name directly ("submission criteria... support
    encoding business logic into data editing permissions," verified
    against their docs). A real, working example:

    ```yaml
    submission_criteria:
      - description: "Ticket must currently be closed to reopen it"
        check: current_state
        field: status
        operator: equals
        value: closed
    ```

    `check` is `current_state` (the object's own, *current* value for
    `field`, read fresh from the database — skipped entirely for a
    `create`, since there's no prior object to check) or `parameter`
    (the value supplied for one of the action's own declared
    parameters — skipped if that parameter wasn't supplied in this
    specific call). `operator` is one of `equals`, `not_equals`,
    `greater_than`, `less_than`, `greater_than_or_equal`,
    `less_than_or_equal`, `in` — a small, fixed set, deliberately not a
    general expression language (the same reasoning, and the same
    real-world precedent, as Palantir's own condition-template-based
    UI, not a raw-expression one). The first criterion that fails stops
    the whole action, with its own `description` as the reason — the
    same message a model sees through its own recoverable-mistake
    handling, and the same one a real, human-facing caller would see
    too.

**RBAC**: `execute:<ActionName>` alone is sufficient exactly when every
`sub_write` targets the **same** object type. The moment an action's
`sub_writes` spans two or more *different* types, every role invoking
it additionally needs its own `write:<Type>.<field>` grant, for every
field touched, for **each** type involved — `execute:` alone is never
enough for a genuinely cross-type action, since a single grant on the
action itself shouldn't silently authorize reaching into a second,
unrelated object type just because a later schema edit added a new
`sub_write` to it.

**Discovery** (`GET /me/visible-action-types`, and the equivalent
model-facing prompt vocabulary) is a **separate** axis from execution
— see `discover:action_types` in the grant table below.

See `tests/integration/fixtures/ontology_schema.yaml` for a real,
multi-object cross-type action (`TransferFunds`) and
`tests/unit/test_named_actions.py` for a real, working
`submission_criteria` example (a "reopen a closed ticket" rule) in
context.

### 8.5 `policy.yaml` — who your users are, and exactly what they can do

Two independent, both-required gates, and **everything is fully
explicit — nothing is inherited from anything else**:

| Action pattern | Grants |
|---|---|
| `read:<Type>` | May discover/search objects of this type at all. Does **not** grant seeing any field's value. |
| `read:<Type>.<field>` | May see this **one specific field's** value. Required for every field, including the identifier. |
| `write:<Type>.<field>` | May change this one field on an existing object. All fields in a write need their own grant — missing even one denies the whole write. |
| `create:<Type>` | May bring a new object into existence. Still needs `write:<Type>.<field>` for every field being set. |
| `tool:<name>` | May invoke this specific tool. |
| `execute:<ActionName>` | May invoke this one named, independently-governed action — the mutations it declares apply regardless of any individual `write:<Type>.<field>` grant, as long as every one of its sub-writes targets a single object type. A sub-write spanning more than one object type additionally needs its own `write:<Type>.<field>` grant per field touched, for each type involved. |
| `discover:action_types` | A single, blanket grant (not per-action) — see the whole action-type catalog via `GET /me/visible-action-types`, including actions this role holds no `execute:` grant for. Matches Palantir's own real, documented default (verified directly, not assumed) more closely than this project's own default posture, which is intentionally more conservative absent this grant: an unknown action and a real-but-unauthorized one otherwise look identical, by design (see `api/routes.py`'s own `propose_action_route`). A role holding this can still only *invoke* an action with its own, separate `execute:` grant — discovery and execution are genuinely separate axes here, same as in Palantir's real model. |
| `manage:users` | May create new database-backed users via `api/`'s `/users` endpoint. |

- **`security_attribute`** — the *mandatory* boundary (MAC). A user can never see data outside their own value for this field, regardless of role.
- **`users`** — static, only used by `scripts/run_deployment.py` (a simple demo/dev tool). The real running service (`api/`) never reads this section — see section 9.

This is deliberately verbose. A role touching a dozen fields needs a
dozen lines. That verbosity is the actual point — every one of those
lines is a decision someone made on purpose, not a default nobody
thought about.

### 8.6 `example_queries.yaml` and your database

`example_queries.yaml` is `user_id`/`query` pairs for
`scripts/run_deployment.py`'s demo. Your database is whatever your
chosen adapter's `connection` in `config.yaml` points at — for SQLite
locally, see `deployment/var/lib/dev_fixtures/schema.sql` for the
fixture pattern.

---

## 9. Two ways to run this: `scripts/run_deployment.py` vs. `api/`

These are **intentionally not unified**:

- **`scripts/run_deployment.py`** is a simple demo/dev tool. It reads users directly from `policy.yaml`'s static `users:` section — no login, no password, just a list of example questions run as each named user in turn.
- **`api/`** is the real, running HTTP service. Every user is a real login, created via `core/user_directory.py` (database-backed, runtime-mutable) and authenticated via `core/auth/` (argon2id password hashing, session tokens).

```bash
# Local dev, against the venv from section 4:
uvicorn api.app:app --reload
```

**Writes are real, and genuinely two-phase.** `POST /query` may return
a `202 Accepted` with a `pending_write` reference instead of an answer
— nothing has been written yet. A separate, later request,
`POST /writes/{write_id}/confirm` (`{"approved": true}` or `false`),
is what actually approves or rejects it. This mirrors
`scripts/run_deployment.py`'s terminal confirmation prompt, adapted for
a remote caller — a synchronous "type y/n" pause has no meaning over
HTTP, so proposing and confirming are genuinely separate requests,
possibly minutes apart. Proposed writes expire on their own (15
minutes) if never confirmed.

---

## 10. Installing as a real, running service

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

---

## 11. Extending the system

| To add... | Implement | Register in |
|---|---|---|
| A new database technology | `core/ontology/interface.py`'s `DataSiloAdapter` | `core/deployment_loader.py`'s `_ADAPTER_REGISTRY` |
| A new LLM backend | `core/llm/interface.py`'s `LLMAdapter` | `core/deployment_loader.py`'s `_LLM_ADAPTER_REGISTRY` |
| A new tool | `core/tools/interface.py`'s `Tool` | `core/tools/registry.py`'s `_TOOL_REGISTRY` |

---

## 12. Why it's built this way — the untrusted-LLM design, point by point

- **The LLM never sees a schema element it isn't authorized for.**
- **"Doesn't exist" and "exists but denied" are indistinguishable**, on purpose, everywhere.
- **Error messages never reveal what's actually valid.**
- **Tools require their own explicit authorization**, separate from data access.
- **Every access decision is logged**, allowed or denied, with MAC and RBAC broken out independently.
- **All I/O is gated.** The LLM only ever receives text back from `LLMAdapter.chat()`.
- **No inference of intent.** Malformed or unrecognized model output fails closed.
- **Fail-safe defaults everywhere.** A user with no role, or a role missing a specific grant, is denied — never implicitly allowed.

---

## 13. Known limitations, honestly

- **Memory security infrastructure exists but isn't wired into the live query path.** `core/memory/guard.py`'s `MemoryGuard` is built and tested, but `AgentLoop` doesn't currently construct or use one.
- **Cross-silo links aren't supported.** Linked object types must currently share a data silo.
- **Single OS process.** Concurrency protections coordinate threads within one process, not across separate processes. The pending-write store is also in-process memory — a multi-worker deployment would need a shared store instead.
- **`install.sh` is a fresh-install script, not an upgrade mechanism.**
- **TLS termination is a deployment responsibility, not this application's own code.** A real, production install sits behind a reverse proxy handling HTTPS -- this project's own security headers (`Content-Security-Policy` etc., see `api/app.py`) and cookie flags (`Secure`, see `core/auth/auth_cookies.py`) assume that proxy exists and is configured correctly; neither `Strict-Transport-Security` nor TLS certificate management is set up by this codebase itself.

None of these are silent gaps — each is a deliberate, documented scope
decision.
