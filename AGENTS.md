# AGENTS.md

Operational instructions for AI agents working on Elysium.

Deliberately short. Research on 138 real repositories (Gloaguen et al.,
2026) found context files reduce agent success when they restate what
an agent can already read, and help only when minimal and precise. So
this file contains only what you would get **wrong** without being
told. Everything else — structure, dependencies, what the code does —
read from the code.

For the reasoning behind these rules, see `PRINCIPLES.md`. This file is
the *how*; that one is the *why*.

## Commands

```bash
./lint.sh                                    # ruff, mypy, vulture, import-linter
python -m pytest tests/ -q -m "not integration"   # the suite that must pass
cd ui && npx vitest run && npm run lint      # frontend
```

Integration tests marked `test_real_model_*` need a live Ollama. They
fail in sandboxes without one. That is environmental, not a regression.

## You do not push

You have no write access to the remote. Produce a patch and hand it
over:

```bash
git format-patch origin/dev..HEAD --stdout > /tmp/change.patch
```

Then verify it applies to a **fresh clone** of the real remote HEAD and
passes lint and tests there, before presenting it. A patch that only
works in your working copy is not done.

## Verification that actually verifies

When you write a test for a bug you fixed, **break the fix and confirm
the test fails.** If it still passes, find out why before moving on.

This caught five hollow tests in one session: a concurrency test that
passed against a racy lock (one trial, wrong interleaving), a batching
test that passed unbatched (two-row fixture), a pagination test that
passed unsorted (SQLite happened to return key order), a cache test
that passed without the cache clear (each prefetch overwrote its own
keys), and a linter test that passed against the reverted fix (the
code path only runs after a *different* failure).

Prefer real servers over mocks for anything user-visible. `jsdom`
cannot see CSS.

## Non-negotiable invariants

**Elysium never writes to a customer's database through a read path.**
`SQLiteReadAdapter` uses a `set_authorizer` connection that refuses
writes at the engine level. Do not add a write method to a read
adapter, and do not route around this.

**Deletes do not delete.** A delete is an edit recorded in the write
log; the source row is untouched. See `core/ontology/write_log.py`.

**MAC is applied in Python, per object, after the engine returns** —
because a security value can chain through `via_field` across silos. A
`GROUP BY` pushed into SQL would aggregate rows the caller cannot see.
Never move authorization into a query.

**Functions receive a capability, never a mediator.** `OntologyAccess`
is bound to one caller and one declared object-type list. A function
never sees a `UserRecord`.

## Before designing anything new

Check what Palantir Foundry does first, and quote their documentation
in the commit. Three designs in one session were wrong until
researched: delete (they never touch the source row), Phase 3 (a
transform stage is for drift detection, not join performance), and
functions (their authors cannot see the calling user either).

If the research contradicts a decision already committed, say so and
reverse it. `ROADMAP.md` records several such reversals; that is the
intended use.

## Do not add speculative code

If nothing calls it, do not write it. `AppendOnlyAdapter` and
`link_type_summaries` were both deleted for this reason. `vulture`
will catch it, but noticing first is better.

## Commit messages

Subject ≤ 72 characters, body wrapped at 72. Explain *why*, name what
was measured, and state what you got wrong. Validate before
committing:

```bash
awk '{ if (length($0) > 72) print NR": "length($0)" chars" }' /tmp/msg.txt
```

## Schema changes are breaking

`ontology_schema.yaml` is a real format with three live deployments
(`tests/integration/fixtures`, `templates`, `deployment/etc`). Change
it only with explicit authorization, migrate all three, and confirm
each still loads and lints.

The deployment linter (`scripts/lint_deployment.py`) must know about
any new schema construct. It reads raw YAML on its error path, so
anything generated at load — link fields, for instance — needs
expanding there too, or it will blame the wrong file.

## Files you should not hand-edit

- `venv/`, `ui/node_modules/` — generated
- `vulture_whitelist.py` — append only, with a comment saying why
- Anything under `tests/integration/fixtures/` without updating all
  three deployments together
