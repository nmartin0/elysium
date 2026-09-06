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

Dependencies are locked. `requirements.txt` carries bounds and is what
a human edits; `requirements.lock` and `requirements-dev.lock` are
generated and carry exact versions with hashes. After changing either
requirements file, regenerate:

```bash
uv pip compile requirements.txt --generate-hashes -o requirements.lock
uv pip compile requirements.txt requirements-dev.txt --generate-hashes \
  -o requirements-dev.lock
```

`./lint.sh` fails if they have drifted.

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

**Name the measurement; do not assert the property.** Write "one
query, 0.5 ms at 100 rows and 144 ms at 55,000" rather than "one
query". Write "asserts are live; checked the systemd unit, the
container entrypoint and `scripts/`" rather than "asserts are live".

Both of those were claimed here without the number, and both were
wrong in the same way: the single query was a full-history scan, and
the path that was never checked was the one that mattered. Counting
queries is adjacent to measuring cost; checking install scripts is
adjacent to checking the service. Adjacent is not the same.

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

If nothing calls it, do not write it. `vulture` catches it; noticing
first is better.

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

`vulture_whitelist.py` is append-only, and each entry needs a comment
saying why. Fixture schemas under `tests/integration/fixtures/` are
one of three deployments that must change together.
