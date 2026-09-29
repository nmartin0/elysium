# The simulator inside Elysium

`sim/` is `github.com/nmartin0/elysium-sim`, grafted in whole with its
77 commits rather than copied, so nothing was lost when that
repository was deleted. Its history is reachable from this one:

    git log --oneline -- sim/

## It is a separate project that happens to live here

It keeps its own `pyproject.toml`, `lint.sh`, `requirements*.txt`,
`tests/`, `scripts/` and `vulture_whitelist.py`. **Eleven of its
top-level names collide with Elysium's**, which is why it is isolated
in a directory rather than merged into the tree.

Run each from its own root:

    ./lint.sh                 # Elysium
    python -m pytest tests/unit tests/integration

    cd sim && ./lint.sh       # the simulator
    cd sim && python -m pytest tests

## What had to change in Elysium to accommodate it

One file: `pytest.ini`. A bare `pytest` at the top level collected
`sim/tests` and ERRORED before running anything, because sim's
conftest imports `simulator`, which is only on the path from sim's own
root. `testpaths` and `norecursedirs` now keep a bare run to Elysium's
own suite. Nothing else in Elysium was touched: no source, no
`pyproject.toml`, no import contract.

## The dependency trap, which cost an hour to find

**The two projects share one Python environment and their requirement
sets conflict.** Installing sim's requirements removed the type stubs
Elysium's mypy needs, and Elysium's lint started failing with errors
that had nothing to do with the simulator:

    core/config.py:48: error: Library stubs not installed for "yaml"

Neither project names those stubs in its own `requirements-dev.txt` --
they arrive as transitive dependencies, so `pip install -r` for one
project can silently take them from the other.

Three stubs are needed for BOTH lints to pass in one environment:

    pip install types-PyYAML types-requests types-PyMySQL

**A separate virtualenv per project is the cleaner answer** and the
one to adopt if this bites again. It is recorded here rather than
fixed because changing how either project installs is a decision, not
a tidy-up.

## What has been verified

| | |
| --- | --- |
| Elysium lint | all checks passed, 8 import contracts kept |
| Elysium integration | 449 passed |
| sim lint | all checks passed |
| sim tests | 603 passed, 471 skipped |
| a bare `pytest` at the top level | collects 0 sim tests |

The 471 skips are sim's own: they need live databases.
