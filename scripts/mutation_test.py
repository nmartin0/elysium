"""Mutation testing for one module against the tests that cover it (DEP-2).

    python -m scripts.mutation_test core/mirror/incremental.py \\
        tests/unit/test_incremental_sync.py

WHAT IT IS FOR. scripts/check_controls.py breaks code in ways a person
chose and checks the tests notice. mutmut breaks it in EVERY small way
it can -- a `<` for a `<=`, an `or` for an `and`, a message to None --
and reports the changes no test noticed. Its first run, over
core/mirror/incremental.py, found that nothing checked the sync's mark
was the HIGHEST cursor value rather than the last one read: a change
that would have made changed-rows reads go backwards, and passed all 45
tests written for that module.

A SURVIVOR IS A QUESTION, NOT A VERDICT. Some are equivalent -- the
code means the same thing either way -- and a few are messages nobody
asserts on. Read each, then either write the test or decide it does
not matter. The controls are where a deliberate decision is recorded.

WHY A SCRATCH COPY. mutmut works in the directory it runs from: it
writes `mutants/` there and reads `[tool.mutmut]` from that directory's
pyproject.toml. Running it in the repository would leave both behind
and pin the configuration to one module. So the repository is copied
(without .git and ui/), the configuration is written into the COPY, and
nothing in the working tree changes.

FORKSERVER ISOLATION, and why: by default mutmut runs the clean test
pass in the same process as its statistics pass. This codebase keeps a
per-process record of which SQLite databases already have their schema
(core/sqlite_connection.py), and pytest reuses temporary paths between
the two passes, so the second pass found a fresh database marked
"already verified" and failed with "no such table". Forking each pass
from a clean server process is what mutmut provides for exactly this.

Slow by nature -- each mutant reruns the selected tests -- which is why
it takes one module and its own tests, and why it is not in lint.sh.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
#: Copied beside core/ so the tests can import everything they import.
ALSO_COPY = ["adapters/", "api/", "scripts/", "functions/", "sim/", "deployment/"]
SKIPPED = {".git", "ui", "mutants", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def _config(module: str, tests: list[str]) -> str:
    quoted = ", ".join(f'"{test}"' for test in tests)
    also = ", ".join(f'"{path}"' for path in ALSO_COPY)
    return f"""

[tool.mutmut]
source_paths = ["{module.split('/')[0]}/"]
only_mutate = ["{module}"]
pytest_add_cli_args_test_selection = [{quoted}]
pytest_add_cli_args = ["-p", "no:cacheprovider", "-q", "-x"]
also_copy = [{also}]
process_isolation = "forkserver"
forkserver_warmup = "none"
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("module", help="the file to mutate, e.g. core/mirror/incremental.py")
    parser.add_argument("tests", nargs="+", help="the test files that cover it")
    parser.add_argument("--keep", action="store_true",
                        help="keep the scratch copy and print where it is")
    args = parser.parse_args()
    for path in (args.module, *args.tests):
        if not (REPO / path).is_file():
            parser.error(f"{path} is not a file in this repository")

    scratch = Path(tempfile.mkdtemp(prefix="elysium-mutation-"))
    try:
        shutil.copytree(REPO, scratch, dirs_exist_ok=True,
                        ignore=lambda _dir, names: [name for name in names if name in SKIPPED])
        with (scratch / "pyproject.toml").open("a") as pyproject:
            pyproject.write(_config(args.module, args.tests))
        run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=scratch,
                             capture_output=True, text=True)
        if run.returncode != 0:
            print(run.stdout[-3000:], run.stderr[-3000:], sep="\n", file=sys.stderr)
            return run.returncode
        results = subprocess.run([sys.executable, "-m", "mutmut", "results"], cwd=scratch,
                                 capture_output=True, text=True).stdout.split("\n")
        survivors = [line.split(":")[0].strip() for line in results if line.endswith(": survived")]
        # The last progress line holds the totals: "236/236  🎉 218 ... 🙁 18".
        counts = re.findall(r"(\d+)/(\d+)\s+\S+ (\d+) .*?🙁 (\d+)", run.stdout)
        if counts:
            _, total, killed, survived = counts[-1]
            print(f"{args.module}: {total} mutants, {killed} killed, {survived} survived")
        if not survivors:
            print("No mutant survived: every change mutmut made was caught by a test.")
            return 0
        print(f"\n{len(survivors)} mutant(s) survived -- a change no selected test noticed:\n")
        for name in survivors:
            shown = subprocess.run([sys.executable, "-m", "mutmut", "show", name], cwd=scratch,
                                   capture_output=True, text=True).stdout
            changed = [line for line in shown.splitlines()
                       if line[:1] in "+-" and line[:3] not in ("+++", "---")]
            print(f"  {name}")
            for line in changed:
                print(f"      {line}")
        return 0
    finally:
        if args.keep:
            print(f"\nscratch copy kept at {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
