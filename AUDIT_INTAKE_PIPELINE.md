# Audit intake, part 2: the pipeline and agent review (14 files)

A second audit set arrived on 24 September: 13,360 lines across 14 files,
pinned to dev `a598ed0`, with 26 reproduction probes (P1-P31) whose code
is printed in full. Every finding in it is recorded here.

**NOTHING HERE HAS BEEN CHECKED AGAINST THE CODE YET.** As in
AUDIT_INTAKE.md, the status column says what the AUDIT claims. A finding
earns a roadmap entry after it reproduces, or demonstrably does not.

## Why the headline number understates it

The index says 139. Counting mechanically across the files gives **154
distinct ids**, and several ids carry more than one defect:

| Where | Headline | Actually |
| --- | --- | --- |
| `PA001-F6` | one finding | four (F6.1-F6.4) |
| `PA001-A15..A18` | "smaller findings" | four separate defects |
| The test tier's strict xfails | "56 xfails" | **57 separately failing behaviours**: F1x4, G6x3, C1x4, A7x4, X2x4, F3x3, A2x3, S1x2, A8x2, R22x6, R23x4, R26x2, and one each for A9, A11, A13, F2, F4, F5, G1, G4, G5, G8, G9, G11, G12, M1, X1 |
| The dirty-data zoo | "one probe" | **25 coded cases / 33 probe cases**, 20 of which behave wrongly today |
| `LB-1` | one finding | two fixes (1a compute figures in code, 1b the number check) |
| `PA001-A7` | "unquoted identifiers" | four distinct parse failures, one of them arbitrary SQL execution |

So the honest count of **distinct broken behaviours in this set is over
200**, before the 78 in AUDIT_INTAKE.md.

## THE SIX THAT OUTRANK EVERYTHING ELSE

Checked first, in this order:

| ID | Why first |
| --- | --- |
| **PA001-M1** | Says pyiceberg 0.12 CAN expire snapshots (`table.maintenance.expire_snapshots()`, P22: 9 snapshots -> 1). **Patch 397 concluded the opposite and wrote "measured rather than assumed" into a commit, a docstring and a test.** I called `ExpireSnapshots(...)` directly; the audit calls it through `table.maintenance`. If they are right, my claim is wrong in public and must be corrected first. The audit also says five places in the repo repeat the false claim. |
| **PA001-X2** | CRITICAL. The agent crashes (`TypeError: Object of type Decimal is not JSON serializable`) on ANY question reading a decimal or date field, in the SHIPPED configuration. Existing agent tests mock the mediator and return floats, so none can see it. |
| **PA001-X1** | HIGH, MAC disclosure. `get_field` returns many-valued link ids with no `check_access`, while `link_counts` two methods away filters correctly and its own comment calls the case "UNTESTABLE IN THIS DEPLOYMENT". One cross-region row tests it. |
| **AL-1** | HIGH, crash. Model-emitted list/dict values raise `TypeError: unhashable type` in `_step_signature()`, OUTSIDE the try/except, so `/query` fails outright. A model produces these shapes naturally. |
| **PA001-F1 + F2** | CRITICAL. A new source column freezes bronze, silver and changelog PERMANENTLY while sync reports success and the integrity check passes; any bronze write failure re-derives silver from the PREVIOUS bronze snapshot and serves stale data, also reporting success. |
| **PA001-F5** | CRITICAL. An S3/MinIO mirror works until its first sync, then the server cannot start, restart or reload. Four hard-coded local catalogs; only run_sync passes storage options. |

## Pipeline defects (PA001-*), all 44 with their sub-items

### Critical

- **F1** new source column freezes the table permanently (P1, P2). Three
  failures in one: changelog scans new columns on the old snapshot; bronze
  `overwrite` without `union_by_name`; `_read_bronze` then returns the STALE
  snapshot and the fresh rows are discarded. Not fully fixed without A9.
- **F2** any bronze failure makes silver serve stale data (P1-B). The comment
  claiming "silver stays correct either way" is false.
- **F5** object storage honoured by the writer only (P11). Now FOUR local-only
  catalogs including the new gold binding.
- **A1** the drift policy queries the write log by TABLE name; the log is keyed
  by OBJECT TYPE. Every removed column is absorbed even with pending writes.
  Both claims in its comment are false, and the shipped ontology is a counter-
  example to one of them.
- **A2** many-to-many join tables are never synced. m2m links, link_counts and
  search_around are EMPTY on the default read path.
- **X2** the agent crashes on any decimal or date field (see above).
- **G1** (critical once gold is read) many-to-many links raise on gold: the
  view points the link at `gold.<Target>`, which has no such column.

### High

- **F3** stringified bronze changes what silver accepts. Boolean half fixed
  (82881ef); `coerce('5.0', integer)` still raises. Scope measured: only
  boolean and whole-float integer diverge.
- **F4** the partial-read guard protects only the changelog; bronze and silver
  still overwrite with the table the guard just called untrustworthy. A genuine
  mass deletion is also never recorded.
- **A3** rejected writes are marked `applied` and served through the overlay
  (P14: database holds 900, ontology serves 800).
- **A5** the overlay bound is a stale "last changed" time; `min()` across
  tables lets one unchanged lookup table hold it back indefinitely. Partly
  fixed; the read-time property is written only when data changed.
- **A6** served snapshots frozen until reload, and pins can MIX: a pinned table
  reads the startup snapshot while a table first synced later reads current.
  run_sync triggers no reload and INSTALL.md says nothing about one.
- **A7** source column names executed as SQL. Four distinct failures: reserved
  word breaks the sync; `"unit price"` parsed as an alias; `"a-b"` parsed as
  the EXPRESSION a minus b (with a misleading "column 'a' is missing" message);
  `"(SELECT k FROM secrets)"` EXECUTED, reading an unreferenced table into
  bronze.
- **A8** decimal filters. equals/in fixed (ce14480); range on decimal was still
  refused. **Overlaps our patch 396.**
- **A9** the changelog cannot widen; every change touching a new column is
  lost.
- **A11** the manifest publishes `data_silos.yaml` verbatim, credentials
  included (P15). Partly mitigated by `${VAR}` references; a literal password
  is still accepted.
- **A19** every API integration test runs `read_from_mirror: false`, so the
  default serving path has no end-to-end tests.
- **C1** a malformed decimal (`$5.00`, `N/A`, `1,234`) raises
  `decimal.InvalidOperation`, which derives from ArithmeticError, not
  ValueError, so it escapes the drift handler: the operator is told `"[<class
  'decimal.ConversionSyntax'>]"`.
- **G2** the gold parity test compares gold to the MIRROR, not the source, on a
  schema with no m2m and no cross-silo field, so it cannot see A2 or G1.
- **G4** a crash during a FIRST gold build publishes unaudited gold; readers
  pin `current_snapshot()`, not the published tag.
- **G5** adding a field raises out of the gold step; every later type is never
  built and the run ends in a traceback, so the post-sync health checks never
  run.
- **G9** one refused silver table silently skips gold for ALL types, with
  nothing printed or recorded.
- **S1** default standardisation flattens every declared text field: newlines
  collapse to spaces. Contradicts MEDALLION_PIPELINE's own match-key rule, and
  a user editing a prefilled field writes the flattened value back to the
  source.
- **X1** many-valued link fields leak ids across MAC (see above).

### Medium

- **A10** a declared type change has no path forward; the table refuses every
  sync until silver is dropped by hand.
- **A12** bronze copies EVERY column of every referenced table, reversing the
  stated column-minimisation policy (SSNs, password hashes, free text).
- **A13** lineage stops at the layer boundary. Partly fixed on silver; the
  changelog still has no bronze snapshot id and no UPDATE before-image.
- **A14** ~2.6 KB/row peak, about ten whole-table materialisations per sync
  (P10: 342 MB at 50k rows, 657 MB at 200k). ELT_ROADMAP records ~1.2 KB/row.
- **A15** tables are read at different moments and a refused table leaves its
  neighbours advanced. WORSE on dev: gold builds only when every table synced,
  so one refusal freezes all of gold.
- **A16** `repair_catalog --write` takes no sync lock and can race a commit.
- **A17** `unchanged` is never recorded and degraded runs are recorded as
  `synced`.
- **A18** the declared-column check ignores `additional_storage` and matches
  tables by bare name across all namespaces -- which on dev can pick a
  QUARANTINE table.
- **G3** one cross-silo field removes the whole connected graph from gold (the
  integration fixture builds NOTHING), and those types silently fall back to
  the mirror.
- **G6** gold serves integer ids as strings and stringifies FK values.
  **Extended**: this reaches the DEFAULT mirror path too, not only gold.
- **G8** the gold link audit depends on declaration order: a referencing type
  declared before its target is refused whenever a new target row and a row
  referencing it arrive in one sync. Mutually-linked types cannot both be
  ordered first.
- **I1** the integrity check reports EVERY gold and quarantine table as broken
  silver. "A check that always reports problems on a healthy deployment trains
  operators to ignore it, which is how F1 and F2 go unnoticed."
- **M1** pyiceberg CAN expire snapshots; five places say it cannot (see above).
- **S2** SQLAlchemy sources (Postgres) put dict/list, UUID, bytes and timedelta
  through `str()`, so bronze holds Python repr (`"{'a': True}"`, `"<memory at
  0x...>"`) and silver cannot recover it.
- **F6.2** six stale comments justify decisions that no longer hold.
- **F6.3** the manifest is published BEFORE the sync loop, so it describes the
  previous run.
- **F6.4** layers are identified by name prefix only.

### Low

- **A17**, **G7** (link check compares ids without type normalisation; latent
  until G6 is fixed on one side), **G10** (a silo named `gold`, `gold_history`,
  `bronze_*`, `changelog_*` or `quarantine_*` collides silently), **G11** (gold
  republishes unchanged types every sync -- snapshot and tag growth, and
  "latest publication" moves when nothing happened), **G12** (decimal scale
  differs by path; FastAPI's encoder turns Decimal into float, so
  `Decimal("12345678901234567.89")` does not survive).
- **F6.1** FIXED on dev (duplicates quarantine every copy).
- **A4** FIXED on dev (overlay merges every applied entry).

### Correction the audit makes to its own earlier work

P12 claimed 88 get_field reads identical by value AND type; the link-id
lists differ by type, so P12 must have compared link lists loosely. Its
value conclusion stands, its type conclusion does not.

## The dirty-data zoo: 20 wrong behaviours in one table

Each is a distinct silver defect, run through the REAL sync:

mojibake undetected; zero-width, tag, bidi, homoglyph and C0 control
characters all pass into gold untouched (R23 -- and the agent reads tag
characters that reviewers cannot see); HTML entities undetected; "N/A"
and `999-999-9999` kept as real values; `1900-01-01` parsed as a real
date; **"N/A" in an integer column refuses the WHOLE TABLE** (R22);
`1,234`, `1e3`, `5%`, `3,14`, `01/02/2024`, `45000` all table-refused
for want of a declared format (R27); `$5.00` CRASHES (C1); full-width
digits silently accepted as 123; `"007"` silently becomes 7, losing a
code's leading zeros; `NaN` and `inf` accepted into `number`, poisoning
every sum (R26); `2099-01-01` accepted with no range; CRLF flattened
(S1).

## Recommendations (R1-R63) -- the ones directly applicable

Part I, pipeline (R1-R21): **R3** canonical type-aware bronze encoding
(P1: lossy encoding cannot be fixed retroactively once history
accumulates); **R6** declared health checks per table and object type;
**R8** independent reconciliation source-to-gold (the only thing that
can see F1/F2, where bronze and silver agree with each other and both
disagree with the source); **R9** one run id and one run report across
all layers; **R11** enforced retention and orphan-file cleanup (now
possible per M1); **R12** column classifications that propagate through
layers; **R13** an erasure workflow (NO planning document on dev mentions
GDPR or the right to be forgotten, and the changelog made the lake a
system of record); **R18** dependency-aware per-type gold builds;
**R19** a source-mutation matrix and live-parity suite in CI. Then R2,
R4, R5, R7, R10, R14-R17, R20, R21.

Part II, cleaning (R22-R36): **R22** type failures become ROW-level
expectations (today one bad cell refuses the table and, through G9, all
of gold); **R23** a text-hygiene pass and agent-boundary guard; **R26**
numeric sanity defaults; **R36** the C1 fix. Then R24, R25, R27-R35.
Their headline conclusion: **do not adopt automatic value repair** -- a
2024 VLDB evaluation of 12 algorithms found most introduce more errors
than they remove.

Part III, enrichment (R37-R50): **R38** value kinds and per-value
provenance; **R39** compartment-safe aggregates (a pipeline-time count
has no user and would store the X1 leak); **R42** guard LLM enrichment
inputs and outputs. Then R37, R40, R41, R43-R50.

Part IV, statistical (R51-R63): **R52** an imputation policy; **R57**
conformal FDR thresholds or none; **R58** clustering without blind
transitive closure; **R59** an evaluation harness; **R61**
cross-compartment matching runs system-high; **R63** the agent reads
evaluation results, code enforces them. P27 measured our own FUSION
design on synthetic data: with dob and email it is near-perfect; with
the fields enterprise tables actually have, **about half the automatic
merges at threshold 0.5 are wrong**, and conformal risk control
correctly REFUSED to auto-accept anything.

## LLM boundary (LB-1..LB-10)

LB-1 arithmetic in prose, unverified (two fixes: 1a compute figures in
code, 1b a number check that fails closed like the citation check);
LB-2 date and ordering logic left to the model -- the agent can only
filter by EQUALITY although core/filters.py implements range, in,
date_range and relative dates, and the schema shown to the model hides
every field's data type; LB-3 silent partial answers (three code-
detected failures presented as complete); LB-4 output shape not enforced
at decoding; LB-5 records rendered as Python repr step logs; LB-6
deterministic follow-ups delegated (52% of the step prompt is procedure,
re-sent every hop); LB-7 tool arguments transcribed by the model; LB-8
entity lookup by exact-match guess although `search_object_free_text`
exists; LB-9 every question through the open-ended loop; LB-10 injection
defence as a prompt instruction.

Probe P28 built the three-tier front end and answered **65% of
answerable test questions with ZERO model calls, all correctly**,
escalating every open-ended and every low-confidence question.

## Agent loop (AL-1..AL-12)

AL-1 crash (above); AL-2 the planner reads raw source data while
choosing actions, including write proposals, with NO untrusted-data
framing in the step prompt (P29: planted text reaches it verbatim);
AL-3 48,704 characters sent over 9 hops to gather ~1,100; AL-4 one step
per call; AL-5 no retries; AL-6 one stop reason; AL-7 no tracing; AL-8
no pass^k evaluation; AL-9 JSON-in-prompt instead of native tools;
AL-10 no token budget; AL-11 cancellation between hops only; AL-12 a
proposed write ends the run.

## Agent research (AR-1..AR-10) and model selection

P31: **97.5% of each hop's prompt is an exact prefix of the previous
one**; only 16% of what is sent needs reading. AR-1 verify prefix-cache
reuse; AR-2 move per-hop notes to the end of the user message (today
they sit at the end of the SYSTEM prompt, invalidating the cache for
everything after them); AR-3 persist each user's system-prompt KV;
AR-4 readable tool results; AR-5 constrain the step choice fully;
AR-6 GEPA; AR-7 plan caching feeding router growth; AR-8 n-gram
speculation; AR-9 heterogeneous models; AR-10 fine-tune on our own task.

MODEL_SELECTION: the ~10 minutes per hop is mostly READING THE PROMPT
(~5.4 tokens/s prefill, ~1.5 decode -- 10-25x below published figures
for this model class). Check the VM's AVX2/FMA flags first. Then
phi4-mini -> Qwen3-4B-Instruct-2507: same size, same speed class,
63.5% -> 94.0% on multi-function selection, which compounds to ~4.5x
less time per SUCCESSFUL answer over four steps.

## The three patches

- **01** `tests/pipeline` (161 tests, ~50 s, no model server; 105 pass, 56
  strict xfails), `core/mirror/validation/` (tier 0/1/2 checks, ~25 named
  checks, history drift, an end-to-end canary), `scripts/validate_pipeline.py`,
  a CI step.
- **02** `core/mirror/pipeline_model/` -- the pipeline derived as a typed model
  with one check registry; 8 checks; its GENERIC type check found G6 unaided.
- **03** `scripts/llm_bench.py` -- measures prefill/decode/prefix-cache/pass^k
  with Elysium's REAL prompt.

All verified on a clean `a598ed0`: lint.sh exit 0, 2,392 unit, 439
integration, 116 pipeline + 57 xfail.

## Owner decisions this set adds

D1 model switch after the bench; D2 Ollama or llama-server; D3 whether
data may leave the VM for escalation; D4 LGPL licences (pycountry,
python-stdnum) in a proprietary product -- counsel; D5 governance items
with policy content (erasure, retention, plaintext credentials, column
classifications, special-category inference); D6 fine-tuning.
Q1-Q6: regulatory regimes, crypto-shredding vs PII-split, lake-level
access by other tools, which source databases come first, freshness
targets per type, and whether gold_history or the silver changelog is
the history of record.

## Dependency decisions (DEPENDENCY_REVIEW-001)

ADOPT runtime: rapidfuzz, dateparser, babel. ADOPT dev: hypothesis,
mutmut. ADOPT as extras: scikit-learn `[ml]`, splink `[fusion]`.
CONDITIONAL: phonenumbers (bus factor 1), holidays, email-validator,
ftfy (dormant). LATER: openlineage-python. DEFER: spacy,
sentence-transformers, jellyfish. AVOID: pycountry (LGPL). AVOID
pending counsel: python-stdnum (LGPL). REJECT: setfit,
recognizers-text. NOT NEEDED: jsonschema, mapie, outlines.

## The set is complete, and one file was a stale revision

AAA_14_MANIFEST.txt lists all 14 files with SHA-256 prefixes and line
counts. Every one matches what is on disk -- except AAA_02, where the
copy first supplied was revision `ac957e4d` (3,100 lines) and the
authoritative one is `cd52b172` (3,107). **The whole difference is a
nine-line header note; no finding was added, removed or altered**, so
the checklist stands.

GAP-1 IS CLOSED, and not by finding the missing files. The manifest
states that 001FINDINGS, 004FINDINGS and AUDIT-01..AUDIT-10 are earlier
EXTERNAL reports by other reviewers, that Audits 01-08 were never
produced at all, and that UNIFIED_ROADMAP.md already recorded this
(at line 1126, not 858 as the manifest says -- right about the
substance, off by about 270 lines). OUR OWN REPOSITORY ALREADY KNEW,
and I asked the owner for the files instead of grepping the roadmap I
had been editing all week. Nothing in
the pipeline set depends on them.

It also settles a naming trap: **the "-001" suffix is a document
revision number, not a position in a series.** There is no
PIPELINE_AUDIT-002 to go looking for.

## Where the two audit sets overlap

| Issue | This set | AUDIT_INTAKE.md |
| --- | --- | --- |
| decimal range refused | PA001-A8 | roadmap decimal range -- **fixed, patch 396** |
| deleted index / retention | PA001-M1, R11 | F-28 -- **patch 397, and M1 may contradict it** |
| tools vs functions | -- | 004-3 -- **documented, patch 396** |
| SQLite identifier quoting | PA001-A7 | LIB-3 -- partly fixed; A7 says the SQLite adapter still interpolates in the BRONZE path |
| gold is a copy of everything | R12 | OPEN_RISKS #2 -- **patch 395** |
| agent filter expressiveness | LB-2 | F-18 |
| unit tests need a seeded deployment | (E.1 rule followed) | E-08 |
| no CI | R19 extends it | E-09 -- audit says dev ADDED CI at 3799d90 |
| write overlay defects | A3, A4, A5 | F-26, F-29 |
| MAC leak on links | X1 | not in the first set |
| security cache across users | not in this set | 004-6 |
| confirm does not re-authorise | not in this set | 004-7 |

**Neither set found the other's most severe finding.** 004-6 and 004-7
appear in no file of this set; X1, X2, F1, F2 and F5 appear in no file
of the first. That is the strongest argument in either document for
reading both completely.
