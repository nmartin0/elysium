# Audit intake -- every finding, before any of them is checked

Six audit files arrived on 24 September. This records EVERY finding in
them, so nothing is lost between reading and working. It is an intake
list, not a verdict.

**NOTHING HERE HAS BEEN CHECKED AGAINST THE CODE YET.** The status
column says what the AUDIT claims, not what is true today. Several of
these are certainly fixed already -- the audits are pinned to commits
hundreds behind `dev` -- and some will turn out to be overstated, as
OPEN_RISKS item 5 did. Each becomes a roadmap entry only after it has
been reproduced, or shown not to reproduce, against the code as it
stands.

## The files, and what each is pinned to

| File | Pinned to | Findings | Note |
| --- | --- | --- | --- |
| `001FINDINGS.txt` | dev, 10 passes | 33 (F-01..F-33) + 3 do-not-fix | The largest. 3,547 lines |
| `004FINDINGS.txt` | `120d1b2` | 8 + 3 smaller | Two HIGH findings appear in no other file |
| `ELYSIUM-FLAWS-2.txt` | `cb94943` | 21 (E-01..E-21) | Supersedes REVISE-THIS-FILE |
| `REVISE-THIS-FILE.txt` | `f4ea94e` | 5 | SUPERSEDED by the above, by its own statement |
| `AUDIT-09-css.md` | `ui/` | 2 defects, 2 dead, 3 weak guards | CSS |
| `AUDIT-10-ui-closeout.md` | `ui/` | 4 README, 2 HTML | Closes `ui/` |

## The same issue under three names

The audits were written independently and renumber freely. These are
one issue each, and must not be worked three times:

| Issue | IDs |
| --- | --- |
| Unit tests fail on a fresh clone (seeded/synced dependency) | 001 none / E-08 / REVISE finding 3 |
| No CI | E-09 / REVISE finding 2 |
| Session tokens stored in plaintext, never reaped | 004 S1+S2 / E-03 / REVISE 6a+6b |
| Login attempts unbounded (disk exhaustion) | E-02 / REVISE finding 1 |
| Lockfile claim stale in requirements.txt | E-15 / REVISE 5a |
| Pending-write store described as in-process | E-16 / REVISE 5b |
| SECURITY_ARCHITECTURE "THE REAL HOLE" heading | E-18 / REVISE 5c |
| tools -> functions rename incomplete | 001 F-12a-adjacent / 004 finding 3 / roadmap 004-F3 |
| Repository visibility vs LICENSE | E-21 / roadmap |
| `write:` grant unauthorisable | F-02 + F-03 / roadmap F-02 |
| Deleted index never rebuilt | F-28 / roadmap F-28 |

## 001FINDINGS -- 33 findings

Severity and evidence grade are the audit's own. RP = reproduced by
running code, IN = inspection, MC = mechanical.

| ID | Sev | Ev | What it claims |
| --- | --- | --- | --- |
| F-01 | HIGH | RP | `coerce()` rejects `"true"`/`"false"`; mirror sync fails permanently, misreported as drift |
| F-02 | HIGH | RP | Cross-type actions unauthorisable by any valid policy. Owner decision |
| F-03 | HIGH | RP | `KeyError: 'mutations'` on a cross-type action containing a delete |
| F-04 | MED | IN | `chat(*args, **kwargs)` erases the typed LLM signature at the wrapper every call passes through |
| F-05 | MED | IN | Rate-limit check and increment are separate transactions (check-then-act) |
| F-06 | MED | MC+IN | `DeploymentConfigResponse` duplicates `DeploymentConfig` field-for-field |
| F-07 | LOW | MC | Identical via_table destructuring at four sites |
| F-08 | LOW | IN | `submission_criteria` parameter-skip is safe only via an unstated precondition |
| F-09 | LOW | IN | `MemoryGuard.put()` uses a private mediator method; flattens `None` to `""` |
| F-10 | LOW | MC+IN | `_generation(request)` called 31x where a `Depends()` exists |
| F-11 | LOW | MC | `mediator()` test fixture duplicated seven times |
| F-12a | LOW | IN | "THE SEVEN REAL GRANT PATTERNS" enumerates six, omits `manage:deployment` |
| F-12b | LOW | IN | `login_attempt_tracker` claims a structurally read-only connection; it is not |
| F-12c | LOW | IN | `write:` rejection message claims it is "not enforced anywhere". It is |
| F-13 | LOW | IN | `get_object()` audit entries carry no `request_id`, so the preferred read path is absent from traces |
| F-14 | HIGH | RP | Parameter used only in a sub-write's criteria rejected at load. Two defects in one function |
| F-15 | HIGH | RP | Valid non-object JSON from the model -> uncaught 500, whole run discarded |
| F-16 | LOW | MC | 64 assertion-free tests. REGRADED by the audit itself; remedy replaced with fixture work |
| F-17 | LOW | IN | Every action parameter shown to the model as a quoted string regardless of type |
| F-18 | INFO | IN | Agent limited to equality filters (documented gap) |
| F-19 | MED | RP | A reverse link accepted as `security.via_field`; read path crashes with OperationalError |
| F-20 | MED | IN | Mirror stringifies literals for three operators and not two; parity tests cannot catch it |
| F-21 | MED | IN | `entries_for_request()` `readlines()` loads the whole audit log, defeating `max_scan` |
| F-22 | HIGH | RP | Ollama adapter leaks 3 of 4 failure modes past `LLMUnavailable` |
| F-23 | HIGH | RP | Synthesis catches `RequestException`, not `LLMUnavailable` |
| F-24 | LOW | RP | Claude SDK adapter passes the system prompt as argv; ~128 KB ceiling -> untranslated `OSError` |
| F-25 | HIGH | RP | Generation numbers repeat after restart and are consumed by rejected loads; audit entries attributed to the wrong config |
| F-26 | HIGH | RP | Mirror overlay returns only the latest edit, serving stale values for earlier ones |
| F-27 | HIGH | RP | Crash recovery loses deletes, reports success, writes a fabricated `create` into the write log |
| F-28 | MED | IN | `rebuild_deleted_index()` documented as the recovery path, never called |
| F-29 | MED | RP | Sync timestamp taken after the read: a blind window where writes are neither mirrored nor overlaid |
| F-30 | MED | IN | `create_colleague_user.py` bypasses `create_debug_user.py`'s safety guard entirely |
| F-31 | LOW | IN | `ObjectNotes.submit()` is the only error handler ignoring session expiry |
| F-32 | LOW | IN | `apiFetchOrThrow` reads an untyped `body.detail`, against the file's own stated policy |
| F-33 | MED | RP | Two critical auth controls each defended by exactly ONE test (mutation testing) |

Recorded as deliberately NOT to be fixed: N-01 duplicated denial-logging
block (rule of three says wait), N-02 `user_directory` bare `commit()`
(convention split, not a bug), N-03 Protocol vs ABC split (document the
Protocol side only).

## 004FINDINGS -- 8 findings and 3 smaller items

**The two HIGH findings here appear in no other file.** They are the
most severe items in the whole intake and are first to be checked.

| ID | Sev | What it claims |
| --- | --- | --- |
| 004-1 | MED | `lint.sh` lockfile step sets `FAILED=1`, which nothing reads -- drift can never fail the build. REPRODUCED |
| 004-2 | MED | Documentation references files and symbols that do not exist (7 paths listed, plus README section 5) |
| 004-3 | LOW | Incomplete tools -> functions rename; two vocabularies live at once |
| 004-4 | LOW | Comments that contradict each other or the code (3 instances) |
| 004-5 | LOW | README architecture map omits `app-schema` and ChartsPanel; lists 4 deployment YAML files, there are 5 |
| **004-6** | **HIGH** | **Stale SHARED security cache allows cross-region reads. `_security_value_cache` is a DataMediator instance attribute, one per generation, shared across all users and threads. REPRODUCED over HTTP: a user kept access after the object moved region, and the rightful user was denied** |
| **004-7** | **HIGH** | **Confirming a write does not re-authorise it. All MAC/RBAC runs at proposal; confirm applies up to 15 minutes later with no re-check. REPRODUCED: same action refused fresh, applied from the older proposal. `proposed_under_generation` is recorded and never compared** |
| 004-8 | LOW | The documented single enforcement point is not single: `WriteMediator` calls `_security_allowed()` directly rather than `check_access()` |
| 004-S1 | -- | Session tokens stored in plaintext |
| 004-S2 | -- | Expired sessions never purged |
| 004-S3 | -- | (Recorded as done well: argon2 with dummy hash, CSRF double-submit) |

## ELYSIUM-FLAWS-2 -- 21 items

| ID | Priority | What it claims |
| --- | --- | --- |
| E-01 | Security | Validation errors reflect request bodies, secrets included. No `RequestValidationError` handler exists |
| E-02 | Security | Unauthenticated disk exhaustion via `login_attempts`: 10 requests took credentials.db from 100 KB to 16.3 MB |
| E-03 | Security | Session tokens in plain text, never reaped. NEEDS OWNER (forces a re-login) |
| E-04 | Security | CSRF token compared with `!=` rather than `compare_digest` |
| E-05 | Security | No Permissions-Policy header |
| E-06 | Security | Failure kinds are runtime exception class names. NEEDS OWNER |
| E-07 | Correctness | A link's id type depends on the read path (ints live, strings mirrored). NEEDS OWNER |
| E-08 | Correctness | 17 unit tests fail on a fresh clone (seeded/synced dependency) |
| E-09 | Correctness | No CI of any kind |
| E-10 | Correctness | Mirror read path 8-10x slower than live; ~86% of a search is catalog load and manifest decode |
| E-11 | Correctness | Model calls have no deadline and discard token counts |
| E-12 | Correctness | No graceful shutdown; the executor is never drained |
| E-13 | Correctness | Sources are not checked at startup; `health_check()` is never called |
| E-14 | Correctness | `MemoryGuard` is built, tested and never used. NEEDS OWNER: wire it or delete it |
| E-15 | Docs | `requirements.txt` says a lockfile is "deliberately deferred"; both lockfiles exist |
| E-16 | Docs | README says the pending-write store is in-process memory |
| E-17 | Docs | README says links cannot cross data silos; they can |
| E-18 | Docs | SECURITY_ARCHITECTURE heads a closed hole as "THE REAL HOLE" |
| E-19 | Docs | UI_ROADMAP lists log rotation as missing (it ships) and says there is no migration mechanism (there is one, ad hoc). The true gap is narrower: no store records a schema version |
| E-20 | Docs | Six roadmap files overlap plus four `*_PLAN.md`. NEEDS OWNER: propose, do not perform |
| E-21 | Owner | Repository visibility vs LICENSE |

## REVISE-THIS-FILE -- superseded, kept for its verified-correct list

`ELYSIUM-FLAWS-2` supersedes this file by its own statement (line 7).
Its five findings map to E-02, E-09, E-08, E-15/16/18 and E-03. What is
worth keeping is its **section 7**, a list of claims the reviewer
executed rather than read: SQL injection blocked through field and
object-type names; the read-only connection enforced at the engine
including `ATTACH` and `PRAGMA writable_schema`; the login timing
channel measured closed at 0.7% delta over 25 samples; lockout at
exactly MAX_ATTEMPTS with a uniform 401; uniform denial across six
endpoints; CSRF enforced as middleware; security headers present.

Those are negative controls somebody already paid for. They should not
be re-derived, and anything that would break one of them is a
regression worth a test.

## ui/ -- AUDIT-09 (CSS) and AUDIT-10 (closeout)

| ID | Sev | What it claims |
| --- | --- | --- |
| CSS S1-01 | Defect | `.app-frame--sidebar-collapsed .app__sidebar` defined twice; the first is entirely dead and its comment describes behaviour the component deliberately removed |
| CSS S1-02 | Defect | The cascade-layer architecture is declared and never used: six of seven layers are empty in the shipped build, every rule we write is unlayered. Migration must be one pass or not at all |
| CSS S2-01 | Dead | Four rules for markup the Blueprint migration removed |
| CSS S2-02 | Dead | Three custom properties defined and never used |
| CSS S3-01 | Guard | The duplicate-selector test sees 101 of 148 selectors and no compound selector at all -- which is why S1-01 was undetected |
| CSS S3-02 | Guard | The `!important` check covers three of four stylesheets, omitting the one whose purpose is making `!important` unnecessary |
| CSS S3-03 | Cosmetic | A duplicated comment block |
| UI S1-01 | Docs | `ui/README.md` says "no design system"; the UI is built on Blueprint |
| UI S1-02 | Docs | `app-schema` missing from the workspace listing -- the THIRD place it has been omitted from an enumeration |
| UI S1-03 | Docs | Per-package contents are a snapshot of an earlier codebase (4 of ~19 modules listed for shell-api) |
| UI S1-04 | Docs | "Five separate checks", four listed, "all four" run. Plus: the React plugin is switched off, so no React rule has ever run |
| UI S2-01 | Minor | No `<noscript>` fallback |
| UI S2-02 | Minor | No favicon link; every page load 404s |

## How each of these leaves this file

One of four ways, and the evidence goes in the roadmap entry:

1. **Already fixed** -- name the patch that did it. Several will be:
   the audits predate months of work.
2. **Still true** -- reproduced against current code, then a roadmap
   entry with the reproduction.
3. **Overstated or wrong** -- recorded with the measurement that shows
   why, as OPEN_RISKS item 5 was.
4. **Needs the owner** -- to the decisions section.

An audit's claim is checked the same way one of mine is. A finding I
cannot reproduce is recorded as unreproduced rather than quietly
fixed: I have already had one of my own reproductions pass for the
wrong reason this week, and an external one can do the same.
