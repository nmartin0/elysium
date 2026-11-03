# Development

Running the pieces, extending the system, the front end, the site and the tests. Installation is `docs/install.md`.

## Two ways to run this: `src/elysium/scripts/run_deployment.py` vs. `src/elysium/api/`

These are **intentionally not unified**:

- **`src/elysium/scripts/run_deployment.py`** is a simple demo/dev tool. It reads users directly from `policy.yaml`'s static `users:` section — no login, no password, just a list of example questions run as each named user in turn.
- **`src/elysium/api/`** is the real, running HTTP service. Every user is a real login, created via `src/elysium/core/user_directory.py` (database-backed, runtime-mutable) and authenticated via `src/elysium/core/auth/` (argon2id password hashing, session tokens).

```bash
# Local dev, against the venv set up in docs/install.md section 2:
uvicorn elysium.api.app:app --reload
```

**Writes are real, and genuinely two-phase.** `POST /query` may return
a `202 Accepted` with a `pending_write` reference instead of an answer
— nothing has been written yet. A separate, later request,
`POST /writes/{write_id}/confirm` (`{"approved": true}` or `false`),
is what actually approves or rejects it. This mirrors
`src/elysium/scripts/run_deployment.py`'s terminal confirmation prompt, adapted for
a remote caller — a synchronous "type y/n" pause has no meaning over
HTTP, so proposing and confirming are genuinely separate requests,
possibly minutes apart. Proposed writes expire on their own (15
minutes) if never confirmed.

---

## Extending the system

| To add... | Implement | Register in |
|---|---|---|
| A new database technology | `src/elysium/core/ontology/interface.py`'s `ExternalReadAdapter` (and `ExternalWriteAdapter` to accept writes) | `src/elysium/core/deployment_loader.py`'s `_READ_ADAPTER_REGISTRY` (and `_WRITE_ADAPTER_REGISTRY`) |
| A new LLM backend | `src/elysium/core/llm/interface.py`'s `LLMAdapter` | `src/elysium/core/deployment_loader.py`'s `_LLM_ADAPTER_REGISTRY` |
| A new tool | `src/elysium/core/functions/interface.py`'s `Function` | `src/elysium/core/functions/registry.py`'s registry |

For a whole new sub-app (a new top-level screen in `ui/`, not a new
backend extension point), check `ROADMAP.md` and `DEV_UI.md` first —
there's a real chance it is already designed, or already decided against.

---

## The front end

Ten packages under `ui/packages/` -- eight screens, `shell-api` and `testing`, 45 components, each with its own
test file:

| package | what it is |
| --- | --- |
| `app-browse` | the object browser — search, filters, charts, bulk actions, saved views |
| `app-admin` | users, roles and grants; the deployment's own configuration, silos, metrics and mirror are the System sub-app's Server page |
| `app-schema` | the visible schema, as the asking user may see it |
| `app-inbox` | the Inbox: one page whose tabs the queue modules fill, and the count of what is waiting on its rail entry |
| `app-approvals` | pending writes and the approval flow |
| `app-identity` | proposed merges — decide whether two records are one, on the agreement pattern rather than on values the reviewer may not read |
| `app-notifications` | triggers and what they fired on |
| `app-query` | ask a question, read the answer and its trace |
| `shell-api` | fetch, session, CSRF, and the design tokens |
| `testing` | the test kit every sub-app's tests use: setup, the test host, and the conformance suite each module is held to |

`npm run lint` runs oxlint, `tsc --noEmit`, oxfmt and knip. The suite
is vitest.

## The marketing site

`site/` is the public website — static HTML and CSS, no build step. It
is **separable**: nothing under it links or imports outside itself,
and it runs its own gate with `bash site/check.sh`. Elysium's lint
excludes it. Lift the directory into its own repository and nothing is
left behind.

## Tests

What is planned next lives in one file, `ROADMAP.md`: Tier 0 core work for a strong model, task cards for efficient models, the questions that wait on the owner, and the waves in which they run.


| suite | how to run | size |
| --- | --- | --- |
| unit | `pytest tests/unit` | 488 files |
| integration | `pytest tests/integration` | 109 files |
| controls | declared in CI | 1141 |
| front end | `cd ui && npm run test` | vitest |
| site | `bash site/check.sh` | ruff + pytest, some in a real browser |

`./lint.sh` runs ruff, mypy and vulture over the Python, and keeps 16
declared contracts.
