# 000COORDINATION.md -- how four agents work on Elysium at once

Read this before your work list. It is short, and it is the part that
decides whether parallel work saves time or costs it.

## The one rule

**ONE FILE, ONE OWNER.** Never edit a file another agent owns, even
trivially, even to unblock yourself. This is the rule every source on
multi-agent development converges on, and it is the one that fails
first when ignored.

Git worktrees stop us overwriting each other's files. They do **not**
stop two agents making incompatible assumptions -- isolation moves a
collision from mid-write to merge time. The ownership map below is
what makes collisions rare rather than merely visible.

## Who owns what

| Area | Owner | Directories and files |
| --- | --- | --- |
| Pipeline, mirror, gold, serving | **backend** | `core/mirror/**`, `core/ontology/mediator.py`, `core/ontology/gold_view.py`, `core/ontology/link_types.py`, `core/ontology/field_types.py`, `core/deployment_loader.py`, `adapters/sqlite_adapter.py`, `adapters/sqlalchemy_adapter.py`, `adapters/inmemory_adapter.py`, `scripts/run_sync.py`, `scripts/check_mirror.py`, `scripts/repair_catalog.py` |
| Front end | **frontend** | `ui/**` (everything), `UI_ROADMAP.md`, `DEV_UI.md`, `OBJECT_EXPLORER_PLAN.md`, `CONFIG_ROUND_TRIP_AND_UI_KIT.md` |
| Auth, the write path, the API's edges | **security** | `core/auth*`, `core/user_directory.py`, `core/intermediate_layer/**`, `core/ontology/write_mediator.py`, `core/ontology/write_log.py`, `core/pending_write_*.py`, `core/identity_decisions.py`, `api/csrf.py`, `api/app.py` |
| The LLM boundary and the agent loop | **agentloop** | `core/llm/**`, `core/agent/**`, `core/memory/**`, `adapters/ollama_adapter.py`, `adapters/vllm_adapter.py`, `adapters/claude_agent_sdk_adapter.py`, `functions/**`, `core/functions/**`, `scripts/agent_trace.py`, `scripts/llm_bench.py` |

Tests follow their module: if you own `core/mirror/gold.py`, you own
`tests/unit/test_gold*.py`. Write new tests in new files named for
what they test; that is how we have avoided test conflicts so far.

## Shared files -- read them, do not edit them

These are hotspots. Every one of them has a single owner, and it is
the **backend** agent, because that is where the project-management
role sits. If you need a change in one, request it (below).

    api/routes.py                 every agent's endpoints live here
    core/ontology/interface.py    the adapter contracts
    tests/integration/fixtures/** shared by every integration test
    lint.sh  pyproject.toml  requirements*.txt  vulture_whitelist.py
    AUDIT_CHECKLIST.csv           the single status list
    UNIFIED_ROADMAP.md  OPEN_RISKS.md  RULES.md  PRINCIPLES.md
    AGENTS.md  README.md  INSTALL.md  and every other root document

**Why `api/routes.py` is not split**: it is 3,000+ lines that every
area touches, and an auto-wiring file edited by four agents is the
textbook case for a conflict that compiles and then disagrees at
runtime.

## Asking for something you do not own

Create `REQUESTS_<yourname>.md` on your branch:

```
## <short title>
NEEDS: <agent who owns it>
WHAT: the endpoint, field, function or shape you need.
WHY: what you cannot do without it.
MEANWHILE: what you did instead -- nothing, a stub, a skipped test.
    Say which. Do not work around it silently.
```

Then tell the human, who will pass it on. The owner replies in the
same file. **Do not edit the other agent's files to unblock
yourself.**

If you find a **security defect** in someone else's area, say so
immediately and directly rather than filing it.

## How work is done

Every agent follows the same sequence, one item per patch:

1. **Check the base, both ways.** Confirm your previous patch actually
   landed on the remote, and that the remote has not moved ahead.
2. **Reproduce the finding** against current code. If it does not
   reproduce, that is a result: record it, with what you tried.
3. **Fix it**, with the reasoning in the code.
4. **Write the test that would have caught it.**
5. **Run a control**: break the fix deliberately, confirm the test
   fails, restore, confirm it passes. A control that proves nothing is
   a finding about your tests -- write the missing case.
6. **Run the gates**: `./lint.sh`, `pytest tests/unit`,
   `pytest tests/integration` (front end: `npm run lint`, `npm test`).
7. **Report** in `STATUS_<yourname>.md` on your branch: what landed,
   what you learned, what you did not check.

`PRINCIPLES.md` and `AGENTS.md` are the house standard. Read both.
The short version: measure rather than assume, say what you did not
check, and correct a wrong claim in public when you find one.

## Merging

**`dev` IS THE INTEGRATION BRANCH.** Every agent branches from `dev`
and merges back into `dev`. `main` only ever moves when `dev` is known
good, and only the human moves it.

    main
      └── dev ─────────┬──────────┬──────────┬──────────┐
                    backend   agentloop   security   frontend
                     (LLM1)     (LLM2)      (LLM3)     (LLM4)

**Sequentially, one branch at a time, with the human at the gate.**
Never all four at once. The order is:

1. The agent says a branch is ready in `STATUS_<name>.md`.
2. The human merges it into `dev`.
3. **The full suite is re-run from the merged `dev`**, not from the
   branch. A branch that was green alone can fail merged; that is the
   whole reason for this step.
4. Every other agent rebases on the new `dev` before continuing.
5. When `dev` has been green for a while, the human fast-forwards
   `main` to it.

Rebase from `dev` at least daily even when you are not merging. A
branch that has not seen `dev` for a week is a merge nobody wants.

## Stopping rules

- **Stuck for three attempts on the same error?** Stop and report it.
  Do not keep trying variations.
- **About to edit a file you do not own?** Stop and file a request.
- **About to change a behaviour another agent depends on** -- an API
  response shape, a function signature, an exception type? Stop, say
  so, and let it be scheduled.
- **A test outside your area starts failing?** That is information,
  not an obstacle. Report it; do not "fix" it into passing.

## Joint work -- nobody starts these

Each needs changes in two areas at once. Starting one from either side
produces a half-feature and a merge conflict.

    UI-LIVE            server-sent events: endpoint + UI
    CONFIG-WRITE       validating write endpoint + UI
    PIPELINE-BUILDER   endpoints + sub-app
    ACCESS-1..6        classification model + admin UI
    ALERT-1            server-side evaluation + UI surface
    GOLD-3d provenance per-object lineage endpoint + display
    E-07, PA001-G12    API response-shape changes the UI consumes

If you find more joint work, add it here rather than starting it.
