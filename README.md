# LLM Data Mediator

An LLM-driven system for answering questions against your organization's
data **without** giving the model direct database access. The LLM never
sees your database or writes any query — it can only ask for a specific,
pre-approved kind of thing ("find this object," "read this one field"),
and a security layer between the model and your data enforces who's
allowed to see what, on every single request.

This document explains how to install and run the system, and — the
important part — how to configure it for **your own organization**. The
included `acme_corp` deployment is only a worked example; you are not
expected to use it, and your own setup will look different.

---

## 1. How the system is organized

```
core/            Generic engine. No knowledge of any organization.
connectors/      Generic database drivers (currently: SQLite).
deployments/     One folder per organization. Pure configuration/data,
                 no code — everything here is YAML plus your database.
scripts/         Runnable entry points.
tests/           Unit tests (fast, no LLM) and integration tests (slow,
                 real LLM calls).
```

The important idea: **`core/` never changes per organization.** Everything
that makes a deployment "yours" — which fields exist, which model you
use, who your users are — lives entirely in `deployments/<your_org>/` as
plain YAML files. Standing up a new organization means writing
configuration, not code.

---

## 2. Prerequisites

- **Python 3.10 or later**
- **[Ollama](https://ollama.com)** installed and running locally — this
  project uses a local LLM, not a paid API, so there's no API key needed
  to get started
- Enough free RAM for whatever model you choose to run (see step 4)

---

## 3. Installation

```bash
git clone <your-repo-url>
cd <repo-directory>

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

---

## 4. Setting up Ollama

Pull whatever model(s) you plan to use. The included example uses two
different models for two different jobs (explained in section 6), but
you can use the same model for both, or different ones — this is a
config choice, not a code change.

```bash
ollama pull phi4-mini      # example: step-selection model
ollama pull qwen2.5:3b     # example: answer-synthesis model
```

**A note on model choice:** the step-selection model needs to reliably
follow structured instructions (it's choosing between a small set of
valid actions, not writing prose) — smaller, "reasoning-flavored" models
have generally worked better here than larger general-purpose ones. The
synthesis model just needs to write a clear answer from data it's
already been given, which is a lighter lift. Try a model, run the test
suite (section 8), and see how it does — this is genuinely
trial-and-error, and what works well depends on your hardware.

---

## 5. Running the included example

The repo ships with one working example deployment, `acme_corp`, with a
small fake customer/transaction database already set up. Run it to
confirm your installation works before building your own deployment:

```bash
python3 -m scripts.run_deployment acme_corp
```

This will run a few example questions through the full pipeline and
print the answers. Expect this to take anywhere from seconds to several
minutes per question depending on your hardware — local LLM inference on
a CPU is genuinely slow; a GPU will be much faster if you have one
available.

---

## 6. Running the tests

```bash
# Fast tests -- no LLM, no network, run these constantly while developing
python3 -m pytest tests/unit/ -v

# Slow tests -- real LLM calls against acme_corp, run before trusting a change
python3 -m pytest tests/integration/ -v -m integration
```

---

## 7. Building your own deployment

This is the main event. Create a new folder:

```bash
mkdir -p deployments/your_org_name/dev_fixtures
```

Everything below goes inside `deployments/your_org_name/`. Five things
need to exist: four YAML files and a database.

### 7.1 `config.yaml` — operational settings

```yaml
ollama:
  base_url: "http://localhost:11434/api/chat"

llm:
  step_model: "phi4-mini"
  synthesis_model: "qwen2.5:3b"
  request_timeout_seconds: 240

agent:
  max_hops: 8
  max_consecutive_duplicates: 2
  max_consecutive_invalid_steps: 2

database:
  path: "dev_fixtures/your_database.db"
```

| Field | What it controls |
|---|---|
| `ollama.base_url` | Where your local Ollama server is listening. `http://localhost:11434/api/chat` is Ollama's default — only change this if you've configured Ollama differently. |
| `llm.step_model` | The model that decides each step of the search (which object to look up, which field to read next). |
| `llm.synthesis_model` | The model that writes the final answer once all the data has been gathered. |
| `llm.request_timeout_seconds` | How long to wait for a single model response before giving up. Local models on CPU-only hardware can be slow — if you see timeout errors, raise this number. |
| `agent.max_hops` | Hard ceiling on how many steps the agent can take answering one question, so a confused model can't loop forever. |
| `agent.max_consecutive_duplicates` | If the model asks for the same thing twice in a row this many times, the system assumes it's stuck and stops. |
| `agent.max_consecutive_invalid_steps` | Same idea, for the model requesting something that doesn't exist in your schema. |
| `database.path` | Where your actual database file lives, **relative to this deployment's own folder.** |

### 7.2 `ontology_schema.yaml` — what data exists, and what's safe to search

This is the file that teaches the system (and the LLM) about your data.
It defines **object types** (roughly: your tables) and their **fields**.

```yaml
object_types:
  Employee:
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
      email:
        type: data
      expense_reports:
        type: link
        target: ExpenseReport
        cardinality: many
        via_table: expense_reports
        via_column: employee_id

  ExpenseReport:
    id_field: report_id
    table: expense_reports
    id_column: report_id
    security:
      via_field: employee_id
    fields:
      amount:
        type: data
      status:
        type: data
      submitted_date:
        type: data
      employee_id:
        type: link
        target: Employee
        cardinality: one
```

Walking through what each piece means:

- **`id_field` / `id_column`** — the name the LLM uses to refer to this
  object's identifier, and the actual column name in your database. These
  are often the same string, but don't have to be.
- **`table`** — the real table name in your database.
- **`security`** — this is the access-control heart of the whole system,
  and it works one of two ways:
  - **`field: <column_name>`** — this object type carries its own
    security value directly (e.g. `Employee.department`). Use this on
    whichever object type is the "root" of your access model.
  - **`via_field: <link_field_name>`** — this object type doesn't carry
    a security value itself; instead, follow the named link field to
    find the object that does, and use *its* value. `ExpenseReport`
    doesn't have a department of its own — it inherits its owning
    employee's.

  Every single field read is checked against this — not just once at
  the start of a question, but on every hop the agent takes, including
  ones reached by following a link. There's no way to see data outside
  your scope by chaining links.

- **`fields`** — every column the LLM is allowed to know about. Two
  kinds:
  - **`type: data`** — a plain value (a name, a number, a date).
  - **`type: link`** — this field's value is another object's ID.
    Links come in two shapes:
    - **`cardinality: one`** — a straightforward foreign key, stored as
      a real column (e.g. `ExpenseReport.employee_id`).
    - **`cardinality: many`** — a *reverse* relationship (e.g. "all the
      expense reports belonging to this employee"). This isn't a real
      column anywhere, so it needs two extra fields telling the system
      where to actually find those rows: `via_table` (which table to
      query) and `via_column` (which column in that table points back
      here).

**Important:** any field not listed here simply doesn't exist as far as
the LLM is concerned — this is how you control exactly what's exposed.
If a table has a column you don't want ever surfaced (say, a salary
figure, or an internal note field), just don't list it.

### 7.3 `policy.yaml` — who your users are

```yaml
security_attribute: department

users:
  alice:
    department: engineering
    allowed_actions: []
  bob:
    department: sales
    allowed_actions: []
```

- **`security_attribute`** — the name of the field (from
  `ontology_schema.yaml`'s `security` blocks) that represents your
  access boundary. In the example above it's `department`; it could just
  as easily be `region`, `team`, `clearance_level`, or anything else —
  the system doesn't assume what it's called, only that every user has
  one.
- **`users`** — each user's own value for that attribute. A user with
  `department: engineering` will only ever see data belonging to
  `engineering`, no matter how they phrase their question or how many
  links the agent follows to get there.
- **`allowed_actions`** — present for future use, **not currently
  enforced** by the live query path. See the Known Limitations section
  below before relying on this field for anything.

### 7.4 `example_queries.yaml` — demo questions for `scripts/run_deployment.py`

```yaml
examples:
  - user_id: alice
    query: "What expense reports has Alice submitted recently?"
  - user_id: bob
    query: "What is Alice's department?"
```

Purely for convenience — a quick way to smoke-test your deployment.
Each entry is a `user_id` (must match a user in `policy.yaml`) and a
`query` (a plain-English question).

### 7.5 Your database

Currently **SQLite only** — `connectors/sqlite_connector.py` is the only
database driver that exists right now. Your `database.path` in
`config.yaml` must point at a real SQLite file whose table and column
names match what you declared in `ontology_schema.yaml`.

For local development/testing, you can build a small fixture database
by hand, the same way the included example does — see
`deployments/acme_corp/dev_fixtures/schema.sql` for a reference on the
pattern: plain `CREATE TABLE` and `INSERT` statements, then:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('deployments/your_org_name/dev_fixtures/your_database.db')
conn.executescript(open('deployments/your_org_name/dev_fixtures/schema.sql').read())
conn.commit()
"
```

For a real production deployment, `database.path` would instead point at
your organization's actual database file — the schema/table/column
names in `ontology_schema.yaml` just need to match what's really there.

---

## 8. Running your deployment

```bash
python3 -m scripts.run_deployment your_org_name
```

This is the same generic script used for `acme_corp` — it works
unmodified for any deployment that has the four YAML files above and a
working database. If you ever find yourself wanting to edit this script
to special-case your organization, that's a sign something belongs in
your YAML configuration instead.

---

## 9. Known limitations, honestly

- **Row-level security (who can see whose data) is fully enforced.
  Action-level authorization (`allowed_actions` in `policy.yaml`) is
  not** — it's defined but not currently checked by the live path. Don't
  treat an empty `allowed_actions` list as meaning "this user is
  blocked"; right now, it isn't.
- **No audit logging on the live path.** A logging system exists
  (`core/intermediate_layer/audit.py`) but isn't currently wired into
  query execution.
- **SQLite only.** No Postgres, MySQL, or other database connectors
  exist yet.
- **One security attribute per deployment.** You can name it anything,
  but there's currently only one dimension of access control per user,
  not a combination of several.

None of these are secret or accidental — they're documented in the
relevant source files (search for `KNOWN GAP` and `STALE, PENDING
REDESIGN` comments) as real, tracked work, not silently missing
features.

---

## 10. Quick reference: what to copy vs. what to change

| If you want to... | Do this |
|---|---|
| Add a new organization | Create `deployments/<name>/` with the four YAML files + database. Never touch `core/`. |
| Change which model is used | Edit `config.yaml`. No code change. |
| Expose a new field to the LLM | Add it to `ontology_schema.yaml`. No code change. |
| Change who can see what | Edit `policy.yaml`. No code change. |
| Add a new *kind* of database | This requires a new file in `connectors/` — a real code change, not configuration. |
