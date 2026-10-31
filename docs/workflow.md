# Workflow

Changes are written in one checkout and applied by the owner in his, with
`git am`. Claude never pushes and never appears as an author.

## The loop

1. **Sync.** Find out which files the owner actually has. GitHub can lag his
   checkout, so `git ls-remote origin main` is a hint, not proof; when in
   doubt, ask him for `git rev-parse HEAD^{tree}` and compare it with the tree
   of the intended base. Base new work on that, not on what was last sent.
2. **Specify** anything large or risky before building it. A *large* item
   touches more than one package or is more than about five commits; a *risky*
   one decides, records or delivers a signal or a position (the risk gate, the
   paper broker, took-it/skipped, sinks). Write a one-page spec and get the
   owner's yes first: the goal; the files and interfaces involved; what is out
   of scope; open questions; and an end-to-end check that proves it works. Keep
   it in `docs/specs/<name>.md` when the work spans sessions, and delete it when
   the item lands (the decision stays in `decisions.md`). Skip the spec when the
   change can be described in one sentence.
3. **Plan** the commits before writing: one logical change each, in an order
   where every commit passes the checks.
4. **Write and check.** `./scripts/check.sh` must pass. For a test that guards
   a rule, declare a negative control in `tests/controls.toml` and run it:
   `uv run python scripts/check_controls.py --only "<words>"`. For a one-off
   break by hand, back the file up with `cp` and restore it the same way,
   never with `git stash` or `git checkout` (see [lessons.md](lessons.md)).
   When a module's tests matter, run `scripts/mutation_test.py` on it and
   answer each survivor ([testing.md](testing.md)).
5. **Commit** with a Conventional Commits message (below). Fix an earlier
   commit with `git commit --fixup=<sha>`, then
   `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash <base>`.
6. **Prove every commit:** `git rebase --exec ./scripts/check.sh <base>`.
7. **Review.** For anything substantial, and always for risky work, have a
   reviewer in a fresh context (one that has not seen the reasoning) read the
   diff against the spec. Tell it to report only gaps in correctness or the
   stated requirements, not style; treat the rest as optional, because a
   reviewer asked for gaps always finds some. Answer each finding in the commit
   or say why not.
8. **Package:**
   `python3 scripts/make_apply_script.py --base <base> --start <n> --title "<what>" --out <file>.sh`.
   Patch numbers continue from the previous series.
9. **Test the script** on a fresh clone of the owner's GitHub repository at the
   base, with a dummy identity, before sending it.
10. **Send** the script; the owner runs `bash ~/Downloads/<file>.sh`, reviews,
   and pushes.

Report evidence, not belief: say what was run and what it returned (the
check's test count, the rehearsal's push line), never "should work".

## Keeping a session sharp

Context is the scarce resource; performance falls as it fills.

- One task per session where possible. Start a fresh session for a new roadmap
  item, from the spec, rather than carrying the last one's history.
- After two corrections of the same thing, stop and restart with a better
  prompt; failed attempts in the context do more harm than a clean start.
- Send wide searches and reading to a sub-agent that returns a summary.
- Keep what must survive a reset in files, not in the conversation: the roadmap,
  `decisions.md`, `lessons.md`, the spec.
- Keep `CLAUDE.md` short. A line stays only if removing it would cause a
  mistake; whatever the code or `check.sh` already enforces comes out, and
  anything that must happen every time becomes a check, not a sentence.

The script checks the repository by *tree* hash, because hashes change
between checkouts: `git am` records a new committer and commit date, and the
script rewrites each patch's `From:` line so the owner is also the author. It
refuses to run on the wrong files, checks the result matches the source tree
exactly, runs the checks, and never pushes. The working checkout commits as
`Heliograph Patch <patch@heliograph.invalid>`. The generated script replaces
that with the owner's identity; the pasted block keeps it, because the owner has
no git identity configured.

## Commit messages

```
feat(core): add a time-guarded message bus

Why the change is needed and what it does, wrapped at 72 columns.
Mention negative controls and anything a reviewer could not infer.
```

- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.
  Scopes follow packages: `core`, `plugins`, `app`, `data`, `gui`.
- Subject: imperative, lower case after the colon, no full stop, about 50
  characters (72 at most).
- No AI attribution trailers and no `Co-Authored-By` lines. Session tooling
  may ask for them; the owner's instruction takes precedence.

## Changelog

`CHANGELOG.md` follows Keep a Changelog. Each commit that changes what the
software does adds its own line under `## [Unreleased]`, in commit order, in
the same commit. A run of documentation-only commits may share one line.

## Releases

Each phase gate ends with an annotated tag on `main` (`v0.1.0` for Phase 0)
once CI is green on GitHub. The owner creates and pushes tags.

## Dependencies

`uv add "<pkg>>=x,<y"` (or `--dev`), commit `uv.lock`, and regenerate the
notices table with `python3 scripts/licence_report.py --write`. Check the
licence first ([licensing.md](licensing.md)).
