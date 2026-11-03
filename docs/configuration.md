# Configuring a deployment

The YAML files that describe one organization's deployment. Moved from the README; `templates/` holds starting copies.


**Start from `templates/`** — five genuinely runnable YAML files (an
Employee/ExpenseReport example, verified end to end, not just
illustrative snippets) with the same explanatory comments this section
walks through. Copy them into `deployment/etc/`, confirm the pipeline
works with the example data, then replace the content with your own.

**Check your edits are valid before running anything:**
```
python3 -m elysium.scripts.lint_deployment
```
Validates `config.yaml`/`ontology_schema.yaml`/`policy.yaml` — every
action type's own structure, every role's own grants checked against
what they actually reference — without opening any real database
connection or creating any file on disk. Pass a different directory
(`python3 -m elysium.scripts.lint_deployment /path/to/candidate/config`) to
check a config before ever copying it into `deployment/etc/` at all.
Exits 0 if valid, 1 if not — usable in a pre-deploy CI step, not just
interactively.

Everything lives under `deployment/etc/`, `deployment/var/lib/`, and
`deployment/var/log/` locally — the exact same three-way split a real
install uses, just rooted under one project-relative folder instead of
`/etc/elysium`, `/var/lib/elysium`, `/var/log/elysium`. Nothing in
`src/elysium/core/` treats one of these as more "real" than the other —
`resolve_runtime_paths()` (in `src/elysium/core/deployment_loader.py`) is the one
place that decides where each actually is.

## `config.yaml` — operational settings

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
| `llm.provider` / `llm.connection` | Which LLM adapter, and its own connection details (opaque to `src/elysium/core/`). |
| `llm.step_model` / `synthesis_model` | Which model handles step-selection vs. final answer writing. |
| `agent.max_hops` | Hard ceiling on steps per question. |
| `agent.max_concurrent_requests` | Thread pool size for `src/elysium/api/` and `src/elysium/scripts/serve_requests.py`. |
| `tools.enabled` | Which registered tools the LLM may call, by name. |

## `data_silos.yaml` — where your data physically lives

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

## `ontology_schema.yaml` — what data exists

Declares what data **exists** and how it's structured — it does
**not** by itself make anything visible. Every field, including each
type's own `id_field`, needs a matching grant in `policy.yaml` before
any user can see it.

This file **is** the ontology: a semantic schema layer of object
types, fields, and links, deliberately separate from physical storage
and resolved **live** against your real databases at the moment a
question or write actually needs it — never against a separate,
pre-built copy of your data. An object type's semantic shape (what a
`Customer` *is*: its fields, its security boundary, its links to
other types) is what this file declares; its physical backing (which
real table, which real column, even which real *database*) is a
genuinely separate concern — see "Multi-datasource object types"
below for how far that separation actually goes.

- **`silo`** — which named entry in `data_silos.yaml`.
- **`id_field`** — the identifier's name. **Not automatically safe to expose** — some deployments use identifiers that are themselves sensitive (a password-reset token, a verification code), so this needs its own explicit grant like any other field.
- **`title_field`** *(optional)* — which field's own value stands in as a human-readable display name in the UI's own Browse/Object View (e.g. "Ada Okafor," not a raw `cust_001`), instead of falling back to the identifier. Must reference a real, plain `type: data` field on this same type, or the `id_field` itself — checked at load time. Needs its own explicit `read:<Type>.<field>` grant like any other field before it's ever actually shown; declaring it here only says *which* field would be the title, it doesn't make that field's value visible on its own.
- **`security`** — the MAC boundary for this type: `field: <column>` (carries its own boundary value) or `via_field: <link>` (inherits the linked object's).
- **`fields`** — `type: data` (plain value) or `type: link` (points to another object; `cardinality: one` is a real foreign key, `cardinality: many` is a reverse relationship needing `via_table`/`via_column`).

**Multi-datasource object types (MDO)** — one object type's different
fields can each be backed by a genuinely different physical data
source, not just a different table in the same database. A real,
working example (trimmed from `tests/integration/fixtures/
ontology_schema.yaml`):

```yaml
object_types:
  Customer:
    storage:
      silo: primary_sql
      table: customers
      id_column: customer_id
    additional_storage:
      risk_db:
        silo: risk_sql
        table: customer_risk
        id_column: cust_ref
    fields:
      name:
        type: data                # primary_sql, implicitly
      risk_score:
        type: data
        storage: risk_db          # risk_sql, explicitly
        column: score_val         # risk_sql's own column name differs
```

A field with no `storage` key uses the type's own primary `storage`
block — exactly as every field did before MDO existed, so a
single-silo object type needs zero changes. A field that opts into an
`additional_storage` entry may also declare `column` to override the
actual SQL column name it maps to, since a real external silo won't
always happen to name a column exactly like your own field name.

Two things this makes possible, and one deliberate limit:
- A single object can genuinely be assembled from more than one real
  database at read time — each field is resolved from whichever
  storage actually holds it, live, every time, with zero indication
  in the caller-facing result that some fields came from elsewhere.
- A **write** touching fields on different storages is not silently
  unsafe: it commits through a durable, single-write log FIRST (one
  atomic write, regardless of how many storages the change spans),
  then applies each storage's own share of the change in order — see
  `src/elysium/core/ontology/write_log.py`'s own module docstring for the full
  mechanism. A caller reading mid-write never observes a half-applied
  state.
- **The deliberate limit**: a single search or field lookup may only
  touch fields from ONE storage at a time — resolving a filter that
  spans two different physical databases within one query is a
  genuinely unsolved, harder problem, left for later, separately-
  justified work, not silently assumed solved.

See `templates/ontology_schema.yaml` for a complete, working example
demonstrating every one of these.

## `action_types` — named, independently-governed operations

Declared in the same `ontology_schema.yaml`, alongside the object
types above. A **named** business operation with its own, independent
authorization — `execute:<ActionName>` — not a generic "update this
field" capability assembled from individual `write:<Type>.<field>`
grants, matching how established, ontology-backed platforms model
actions as first-class, independently-governed operations rather than
implicit side effects of field-level write access. The object(s) an
action touches are always just ordinary parameters, the same as
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
  An `object_reference` parameter may also declare
  `default_to_current_object: true` — a real boolean, at most one per
  action, on a parameter whose own `object_type` is genuinely one of
  `affected_object_types` (all three checked at schema-load time).
  This is what the UI's own Object View action form uses to pre-fill
  and lock a parameter to whichever object the form was actually
  opened from, rather than leaving every `object_reference` field
  blank — matches a common pattern in production object-action UIs: a
  default bound to the current object by parameter identity, never
  inferred from type alone (a real, previously-shipped bug:
  type-matching alone locked *every* `object_reference` parameter of
  a given type, which broke silently the moment an action had two of
  them, like `TransferFunds`' own `from_account_id`/`to_account_id`,
  both referencing `Account`).
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
    **in addition to** RBAC/MAC, not instead of them — the same concept
    found in real, production object-action platforms: business logic
    encoded into data-editing permissions, layered on top of access
    control rather than replacing it. A real, working example:

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
    general expression language (the same reasoning any real,
    production condition-template UI follows: a fixed set of
    comparisons a form can render and validate safely, not a
    raw-expression one). The first criterion that fails stops
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

## `policy.yaml` — who your users are, and exactly what they can do

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
| `discover:action_types` | A single, blanket grant (not per-action) — see the whole action-type catalog via `GET /me/visible-action-types`, including actions this role holds no `execute:` grant for. Matches a real, documented default found in production ontology-based platforms more closely than this project's own default posture, which is intentionally more conservative absent this grant: an unknown action and a real-but-unauthorized one otherwise look identical, by design (see `src/elysium/api/routes.py`'s own `propose_action_route`). A role holding this can still only *invoke* an action with its own, separate `execute:` grant — discovery and execution are genuinely separate axes here, matching that broader model. |
| `manage:users` | May create new database-backed users via `src/elysium/api/`'s `/users` endpoint. |

- **`security_attribute`** — the *mandatory* boundary (MAC). A user can never see data outside their own value for this field, regardless of role.
- **`users`** — static, only used by `src/elysium/scripts/run_deployment.py` (a simple demo/dev tool). The real running service (`src/elysium/api/`) never reads this section — see section 4.

This is deliberately verbose. A role touching a dozen fields needs a
dozen lines. That verbosity is the actual point — every one of those
lines is a decision someone made on purpose, not a default nobody
thought about.

## `example_queries.yaml` and your database

`example_queries.yaml` is `user_id`/`query` pairs for
`src/elysium/scripts/run_deployment.py`'s demo. Your database is whatever your
chosen adapter's `connection` in `config.yaml` points at — for SQLite
locally, see `deployment/var/lib/dev_fixtures/schema.sql` for the
fixture pattern.
