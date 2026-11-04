#!/usr/bin/env python3
"""commit_msg_check.py -- the commit message rules, as a script.

    commit_msg_check.py FILE             the commit-msg hook (FILE: the message)
    commit_msg_check.py --claude-pretool the agent hook: reads a tool call as
                                         JSON on stdin and, for `git commit`,
                                         runs the pre-commit checks (exit 2
                                         refuses the call)

A message has a subject of at most 72 characters, body lines of at most 72,
and a last paragraph of `Key: value` trailers. The only keys are:

    Card: <id>             a card id, or `T0.n step k`; required on a card branch
    Controls-Added: ...    control ids or none; required when src/ changes
    Controls-Deleted: ...  control ids or none; required when src/ changes
    Invariants: ...        I1..I8 or none; required when src/ changes
    Large-change: <why>    required when tools/diffsize.py asks

Any other trailer, an attribution trailer among them, is refused. The
message also goes through the name guard.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import diffsize  # noqa: E402
import name_guard  # noqa: E402

WIDTH = 72
KEYS = ("Card", "Controls-Added", "Controls-Deleted", "Invariants", "Large-change")
_TRAILER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)$")
_CARD = re.compile(r"^(?:T0\.\d+[A-Z]?(?: step \d+[a-z]?)?|[A-Z][A-Z0-9]*(?:-[A-Za-z0-9]+)+)$")
_IDS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\s*,\s*[A-Za-z0-9][A-Za-z0-9._-]*)*$")
#: `git commit` as a command: at the start, or after ; & | ( or a newline; global options allowed.
_GIT_COMMIT = re.compile(r"(?:^|[;&|(\n])\s*git(?:\s+(?:-[cC]\s+\S+|--?\S+))*\s+commit\b")
_INVARIANTS = re.compile(r"^I[1-8](?:\s*,\s*I[1-8])*$")


def split_message(message: str) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """(lines before the trailers, trailers by key, last-paragraph lines that are not trailers)."""
    lines = [ln.rstrip() for ln in message.splitlines() if not ln.startswith("#")]
    while lines and not lines[-1]:
        lines.pop()
    start = len(lines)
    while start > 0 and lines[start - 1]:
        start -= 1
    if start == 0:  # a single paragraph is a subject and a body, never trailers
        return lines, {}, []
    trailers: dict[str, list[str]] = {}
    loose = []
    for line in lines[start:]:
        match = _TRAILER.match(line)
        if match:
            trailers.setdefault(match.group(1), []).append(match.group(2))
        else:
            loose.append(line)
    if not trailers:  # an ordinary last paragraph
        return lines, {}, []
    return lines[:start], trailers, loose


def _shape_problems(lines: list[str], body: list[str], trailers: dict[str, list[str]],
                    loose: list[str]) -> list[str]:
    problems = []
    if len(lines[0]) > WIDTH:
        problems.append(f"the subject is {len(lines[0])} characters; keep it within {WIDTH}")
    for number, line in enumerate(body[1:], start=2):
        if len(line) > WIDTH and not _TRAILER.match(line):
            problems.append(f"line {number} is {len(line)} characters; wrap the body at {WIDTH}")
    for key, values in trailers.items():
        if key not in KEYS:
            problems.append(f"{key}: is not an accepted trailer (only {', '.join(KEYS)}); "
                            f"no attribution trailers")
        elif len(values) > 1:
            problems.append(f"{key}: is given {len(values)} times")
    if loose:
        problems.append(f"the last paragraph mixes trailers with text: {loose[0]!r}")
    return problems


def _card_problems(card: str | None, branch: str) -> list[str]:
    if card is None:
        if branch.startswith("card/"):
            return ["Card: is missing (every commit on a card branch names its card, "
                    "e.g. `Card: T0.5 step 3b` or `Card: ADM-03a`)"]
        return []
    return [] if _CARD.match(card) else [f"Card: {card!r} is not a card id or `T0.n step k`"]


def _src_problems(value: dict[str, str | None]) -> list[str]:
    problems = []
    for key in ("Controls-Added", "Controls-Deleted", "Invariants"):
        found = value[key]
        if found is None:
            problems.append(f"{key}: is missing (every commit that changes src/ lists it; "
                            f"`none` is an answer)")
        elif found != "none" and not (_INVARIANTS if key == "Invariants" else _IDS).match(found):
            what = "I1..I8 or none" if key == "Invariants" else "control ids or none"
            problems.append(f"{key}: {found!r} is not {what}")
    return problems


def check(message: str, *, branch: str = "", changes_src: bool = False, large: bool = False) -> list[str]:
    """What is wrong with `message`, as sentences; empty when it is fine."""
    lines = [ln.rstrip() for ln in message.splitlines() if not ln.startswith("#")]
    if not any(lines):
        return ["the message is empty"]
    body, trailers, loose = split_message(message)
    value = {key: (trailers[key][0].strip() if trailers.get(key) else None) for key in KEYS}

    problems = _shape_problems(lines, body, trailers, loose)
    problems += _card_problems(value["Card"], branch)
    if changes_src:
        problems += _src_problems(value)
    if large and not value["Large-change"]:
        problems.append("Large-change: <reason> is missing (the change is over "
                        f"{diffsize.LIMIT} non-generated lines)")
    problems += [f"line {hit.line} names the precedent's vendor or one of its products; "
                 f"write \"the precedent\"" for hit in name_guard.check_text(message)]
    return problems


def _staged_names() -> list[str]:
    out = subprocess.run(  # noqa: S603, S607 -- fixed argument list, no shell
        ["git", "diff", "--cached", "--name-only", "-z"], capture_output=True, text=True,  # noqa: S607 -- fixed command
        check=True, cwd=ROOT).stdout
    return [name for name in out.split("\0") if name]


def _branch() -> str:
    return subprocess.run(  # noqa: S603, S607 -- fixed argument list, no shell
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True,  # noqa: S607 -- fixed command
        check=False, cwd=ROOT).stdout.strip()


def check_file(path: str) -> list[str]:
    message = Path(path).read_text()
    first = next((ln for ln in message.splitlines() if ln.strip() and not ln.startswith("#")), "")
    if first.startswith(("Merge ", "Revert ", "fixup! ", "squash! ")):
        return []
    size = diffsize.staged_size()
    return check(message, branch=_branch(), changes_src=any(n.startswith("src/") for n in _staged_names()),
                 large=diffsize.too_big(size, ""))


def commit_messages(command: str) -> str | None:
    """The message given by -m options of a `git commit` command line, if it can be read."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    parts = []
    for index, word in enumerate(words):
        if word in ("-m", "--message") and index + 1 < len(words):
            parts.append(words[index + 1])
        elif word.startswith("-m") and len(word) > 2 and not word.startswith("--"):
            parts.append(word[2:])
    return "\n\n".join(parts) if parts else None


def claude_pretool() -> int:
    try:
        call = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (call.get("tool_input") or {}).get("command", "")
    if not _GIT_COMMIT.search(command):
        return 0
    hook = ROOT / ".githooks" / "pre-commit"
    result = subprocess.run([str(hook)], capture_output=True, text=True, check=False, cwd=ROOT)  # noqa: S603
    problems = [result.stdout.strip(), result.stderr.strip()] if result.returncode else []
    message = commit_messages(command)
    if message is not None:
        problems += check(message, branch=_branch(), changes_src=any(n.startswith("src/") for n in _staged_names()))
    problems = [p for p in problems if p]
    if problems:
        print("git commit refused by the project's checks:\n" + "\n".join(f"- {p}" for p in problems),
              file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("file", nargs="?")
    parser.add_argument("--claude-pretool", action="store_true")
    args = parser.parse_args(argv)
    if args.claude_pretool:
        return claude_pretool()
    if not args.file:
        parser.error("a message file is required")
    problems = check_file(args.file)
    for problem in problems:
        print(f"commit-msg: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
