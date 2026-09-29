# The simulator inside Elysium

`sim/` is `github.com/nmartin0/elysium-sim`, grafted in whole with its
77 commits rather than copied, so nothing was lost when that
repository was deleted. Its history is reachable from this one, but
NOT through `git log -- sim/`: those commits were made when the files
sat at that repository's root, so they carry no `sim/` paths. Use the
graft's second parent:

    git log --oneline <graft-commit>^2      # 77 commits, tip 13a845b

## It uses Elysium's toolchain, not its own

It arrived with its own `pyproject.toml`, `lint.sh`, `requirements*`
and locks. **Those collided, and not gently.** Sim pinned `mypy>=1.11,
<2`; Elysium's lock pins `mypy==2.3.1`. Installing either project's
requirements downgraded or upgraded the other's type checker by a
major version, and the resulting failures looked like bugs in whichever
project you happened to lint next.

So sim gave way. It now has no build or lint configuration of its own:

    ./lint.sh                      # both projects, 16 contracts
    python -m pytest tests/unit tests/integration
    python -m pytest sim/tests

`pytest` with no arguments runs both suites.

**THE `mypy<2` PIN WAS UNNECESSARY.** Sim's 55 source files pass mypy
2.3.1 with no issues at all. The pin that caused the whole collision
protected nothing.

## What moved where

| from | to |
| --- | --- |
| sim's 8 import contracts | `pyproject.toml`, verbatim, alongside Elysium's 8 |
| `psycopg`, `PyMySQL` | `requirements.txt` (psycopg was already there) |
| sim's vulture whitelist | `vulture_whitelist.py`, reasons and all |
| `postgres` / `mariadb` markers | `pytest.ini` |
| `sim/scripts/check_controls.py` | `sim/simulator/check_controls.py` |
| `sim/scripts/check_lockfiles.py` | deleted -- sim has no locks now |

`sim/scripts` had to go: it shadowed Elysium's `scripts` package, so
sim's own tests imported the wrong module.

**RUFF FOUND 39 STYLE VIOLATIONS** in sim that its own configuration
never looked at -- its ruff settings were identical to Elysium's but
pointed at fewer paths. Fixed across 36 files rather than exempted.

## Two things that need care

`pythonpath = . sim` in `pytest.ini` puts BOTH roots on the path, so a
new top-level package in `sim/` that shares a name with one of
Elysium's will shadow it in exactly the way `scripts` did. Elysium is
first, so Elysium wins -- which is the right way round, but it means
the failure appears in SIM's tests, pointing at Elysium's code.

`lint-imports` needs `PYTHONPATH=sim` to resolve `simulator`; that is
set in `lint.sh` at the one call site.

## Verified with both present

| | |
| --- | --- |
| `./lint.sh` | all checks passed, 16 contracts kept |
| Elysium unit | 3,569 passed |
| Elysium integration | 449 passed |
| sim | 596 passed, 471 skipped |

The 471 skips are sim's own: they need live PostgreSQL and MariaDB.
