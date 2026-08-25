# LLM Data Mediator

An LLM-driven system for answering questions — and, with permission,
making changes — against your organization's data, without giving the
model direct database access, and without trusting the model's own
judgment about what it's allowed to see or do.

**One server instance runs one organization's data.** This is a
single-tenant system — the `deployment/` folder described below holds
exactly one organization's configuration, not a directory of many.

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
deployment/      YOUR organization's configuration and data. No code
                 here at all -- YAML plus your actual database.
scripts/         Runnable entry points.
tests/           Unit tests (fast, no LLM) and integration tests (slow,
                 real LLM calls).
```

The core idea: **`core/` never changes for your organization, and never
changes based on which database or LLM you use.** Everything specific —
which fields exist, which model you run, who your users are, which
database technology backs your data — lives in `deployment/` as plain
YAML, or as a named, swappable adapter.

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
allowed or denied. Section 7 below explains exactly how to configure
this for your organization; section 10 explains why it's built this
way.

---

## 3. Prerequisites

- **Python 3.10 or later**
- **[Ollama](https://ollama.com)** installed and running locally
- Enough free RAM for whatever model you choose to run

---

## 4. Installation

```bash
git clone <your-repo-url>
cd <repo-directory>

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

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

No arguments — there's only ever one `deployment/` folder. Runs a few
example questions through the full pipeline and prints the answers.

---

## 7. Configuring `deployment/` for your organization

### 7.1 `config.yaml` — operational settings

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
| `data_silos` | Named data-silo instances — technology + connection details, one or more. |
| `tools.enabled` | Which registered tools the LLM may call, by name. A tool being enabled here is necessary but not sufficient — see section 7.3 for the per-user grant it also needs. |

### 7.2 `ontology_schema.yaml` — what data exists

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
before any user can see it (section 7.3). A field declared here with no
matching grant anywhere simply never appears to the LLM at all — not
"exists but hidden," genuinely absent from what the model is ever told.

- **`silo`** — which named entry in `config.yaml`'s `data_silos`.
- **`id_field`** — the identifier's name. **Not automatically safe to expose** — some deployments use identifiers that are themselves sensitive (a password-reset token, a verification code), so this needs its own explicit grant like any other field.
- **`security`** — the MAC boundary for this type: `field: <column>` (carries its own boundary value) or `via_field: <link>` (inherits the linked object's).
- **`fields`** — `type: data` (plain value) or `type: link` (points to another object; `cardinality: one` is a real foreign key, `cardinality: many` is a reverse relationship needing `via_table`/`via_column`).

### 7.3 `policy.yaml` — who your users are, and exactly what they can do

Two independent, both-required gates, and **everything is fully
explicit — nothing is inherited from anything else**:

```yaml
security_attribute: department

roles:
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

- **`security_attribute`** — the *mandatory* boundary (MAC). A user can never see data outside their own value for this field, regardless of role. Could be `department`, `region`, `tenant_id` — the system has zero built-in understanding of what the value *means*, it's pure string equality.
- **`roles`** — the *role-based* layer (RBAC), and this is the part worth reading carefully:

| Action pattern | Grants |
|---|---|
| `read:<Type>` | May discover/search objects of this type at all (`search_object`). Does **not** grant seeing any field's value. |
| `read:<Type>.<field>` | May see this **one specific field's** value. Required for every field, including the identifier — nothing is inherited from the `read:<Type>` grant above. |
| `write:<Type>.<field>` | May change this one field on an existing object. A write touching multiple fields needs a grant for **every** field being changed — missing even one denies the whole write. |
| `create:<Type>` | May bring a new object of this type into existence. Separate from field grants — a create still needs `write:<Type>.<field>` for every field being set, so creating can never be used as a backdoor around a field's write restriction. |
| `tool:<name>` | May invoke this specific tool. |

- **`users`** — each user's boundary value and role. **A user with no `role` key is denied every access, even within their own department** — RBAC and MAC are both required, never either/or.

This is deliberately verbose. A role touching a dozen fields needs a
dozen lines. That verbosity is the actual point — every one of those
lines is a decision someone made on purpose, not a default nobody
thought about.

Every access decision — allowed or denied, read or write or tool —
is logged to `deployment/logs/audit.log`, with the MAC and RBAC results
broken out independently, so a denial's real cause is always visible in
the log, even though it's never visible to the LLM itself.

### 7.4 `example_queries.yaml` and 7.5 your database

Unchanged in shape from previous versions — `example_queries.yaml` is `user_id`/`query` pairs for the demo script; your database is whatever your chosen adapter's `connection` in `config.yaml` points at. For SQLite locally, see `deployment/dev_fixtures/schema.sql` for the fixture pattern.

---

## 8. Running your configured deployment

```bash
python3 -m scripts.run_deployment
```

Same command as the built-in example. For proposed writes, this script
shows a real terminal confirmation prompt with the exact fields and
values about to change — nothing is written until a human approves it.

---

## 9. Extending the system

| To add... | Implement | Register in |
|---|---|---|
| A new database technology | `core/ontology/interface.py`'s `DataSiloAdapter` | `core/deployment_loader.py`'s `_ADAPTER_REGISTRY` |
| A new LLM backend | `core/llm/interface.py`'s `LLMAdapter` | `core/deployment_loader.py`'s `_LLM_ADAPTER_REGISTRY` |
| A new tool | `core/tools/interface.py`'s `Tool` | `core/tools/registry.py`'s `_TOOL_REGISTRY` |

Tools must be strictly stateless — pure data in, data out, zero access
to the database, network, or filesystem.

---

## 10. Why it's built this way — the untrusted-LLM design, point by point

Worth stating explicitly, since these are load-bearing design decisions,
not incidental details:

- **The LLM never sees a schema element it isn't authorized for.** `DataMediator.visible_schema()` filters every object type and every field, per user, before the prompt is even built. An unauthorized field isn't marked hidden — it's absent.
- **"Doesn't exist" and "exists but denied" are indistinguishable**, on purpose, everywhere — `search_object`/`get_field` never raise a distinguishing error for either case, both look like an ordinary empty result. Without this, an attacker could reconstruct a hidden schema by testing names and watching which ones raise.
- **Error messages never reveal what's actually valid.** An invalid search filter gets a generic error, not a list of real field names.
- **Tools require their own explicit authorization**, separate from data access — `tool:<name>` — and a user lacking it sees the identical error a genuinely nonexistent tool would produce.
- **Every access decision is logged**, allowed or denied, with MAC and RBAC broken out independently — a denial's real cause is always reconstructable from the log, never from what's shown to the LLM.
- **All I/O is gated.** The LLM only ever receives text back from `LLMAdapter.chat()` — never a database connection, file handle, or network socket.
- **No inference of intent.** Malformed, ambiguous, or unrecognized model output fails closed (treated as "finish," never guessed at).
- **Fail-safe defaults everywhere.** A user with no role, or a role missing a specific grant, is denied — never implicitly allowed.

---

## 11. Known limitations, honestly

- **Memory security infrastructure exists but isn't wired into the live query path.** `core/memory/guard.py`'s `MemoryGuard` (live, per-access re-validation) is built and tested, but `AgentLoop` doesn't currently construct or use one.
- **Cross-silo links aren't supported.** Linked object types must currently share a data silo.
- **Single OS process.** Concurrency protections coordinate threads within one process, not across separate processes.
- **No real HTTP server yet.** `scripts/serve_requests.py` proves concurrent request handling is safe, but isn't itself network-facing.

None of these are silent gaps — each is a deliberate, documented scope
decision.
