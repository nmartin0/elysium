# The medallion pipeline -- bronze, silver, GOLD, and the ontology on gold

Researched September 22, at the owner's direction: "get the gold layer
front and center ... the ELT way so that data is preserved along the
path ... I want us to already get the ontology pointed at the gold
layer once that is sorted."

This EXTENDS ELT_ROADMAP.md (bronze, silver-from-bronze, durable
storage -- done; the silver changelog -- planned) and
FUSION_AND_IDENTITY.md (identity resolution belongs in gold). It
contradicts neither; where it adds, it says so.

---

## Where Elysium stands, MEASURED September 22

    source -> BRONZE (bronze_<silo>.<table>) -> SILVER (<silo>.<table>) -> ontology

- The catalog after a real sync holds exactly two namespaces:
  `bronze_primary_sql` and `primary_sql`. A real search opened only
  `primary_sql.customers` and `primary_sql.transactions` -- SILVER.
- Bronze: the source as-is, every column, the source's own types kept,
  two snapshots retained. Nothing reads it ("NOTHING READS BRONZE").
- "Silver" today is ONE step: `transform_rows`, type normalisation to
  the declared types. No standardisation, no validation, no quarantine,
  no deduplication policy, no history, no lineage columns.
- Gold: does not exist. FUSION_AND_IDENTITY.md names it as the place
  identity resolution belongs.

---

## What the precedent says each layer is

**The canonical split** (Databricks, who coined the pattern): bronze is
raw ingestion with no cleanup or validation; silver is "data cleaning
and validation"; gold is "dimensional modeling and aggregation".
Silver's listed operations: schema enforcement, handling of null and
missing values, deduplication, out-of-order and late data, data
quality checks and enforcement, schema evolution, type casting, joins.
Silver "should always include at least one validated, non-aggregated
representation of each record."
(docs.databricks.com/aws/en/lakehouse/medallion)

**Silver is one-to-one with its source** (dbt's convention, the most
widely followed): a staging model "bears a one-to-one relationship
with the source data table it represents. It has the same granularity,
but the columns have been renamed, recast, or usefully reconsidered
into a consistent format." Joins and business logic come AFTER.

**Invalid rows are routed, not lost** (Databricks expectations):
three policies -- warn (keep, record), drop, fail -- and a QUARANTINE
pattern that writes failing rows to a separate table "rather than
silently discarding them". For an ELT pipeline that preserves data
along the path, quarantine is the only drop that qualifies.

**What to check** (DAMA-DMBOK's six dimensions): completeness,
uniqueness, timeliness, validity, accuracy, consistency. Two nuances
that shape the design: nullability rules VARY BY COLUMN; and validity
(format, range, allowed values) is checkable at ingest where accuracy
(matches the real world) generally is not -- silver checks validity
and never claims accuracy.

**Cleaning, conservatively** (text-normalisation guidance): NFC
Unicode normalisation and whitespace cleanup are the recommended
BASELINE; case folding and stripping accents are aggressive and lose
meaning. Hence a rule below: silver applies only meaning-preserving
cleanups to VALUES; aggressive normalisation produces separate MATCH
KEYS in gold, never replacing a value.

**History belongs in silver, from comparing snapshots** (SCD Type 2
guidance): each version of an entity a row, with valid_from/valid_to;
for FULL-LOAD sources -- our shape: no updated_at, no change feed --
built by comparing successive snapshots, as dbt snapshots do. This is
ELT_ROADMAP.md's planned silver changelog, now with its name.

**Gold for an ontology is entity-centric, and the key is a contract**
(Palantir Foundry, whose design Elysium follows): an object type's
backing datasource must have a unique, non-null primary key; a
duplicate within one batch FAILS the indexing job; across
transactions, the later version wins. And: when one real-world entity
arrives under two keys from two systems, that is identity resolution,
which "belongs in the pipeline, before the object type".

**Identity: match, then survivorship, both governed** (MDM practice):
- Matching (Fellegi-Sunter, as implemented by Splink, which runs on
  DuckDB): a pair's weight against TWO thresholds -- above, a match;
  below, a non-match; BETWEEN, "evaluated manually". Three outcomes,
  not two.
- Survivorship is PER ATTRIBUTE, not per record: trusted source, most
  recent, most frequent, most complete -- usually mixed by attribute
  group. "No attribute-level decision is made before identity is
  established." "Deleting losing values destroys trust." "Manual
  actions are data, not side effects."
  Every one of these is already a rule in FUSION_AND_IDENTITY.md --
  declared rules primary, inference off by default, approved merges
  stored as data through the write queue.

**Publishing gold only after it passes** (Write-Audit-Publish, Iceberg):
write to a branch, audit there, publish by an atomic pointer move.
Nothing downstream ever sees an unaudited gold.

---

## What PyIceberg 0.12.0 can do here -- TESTED, not assumed

- Writes to a BRANCH: `append(..., branch="audit")`. Main unchanged
  while the branch holds the new rows. MEASURED.
- NO `fast_forward` (an open pull request, #3649) and no
  `replace_branch`. But `manage_snapshots().set_current_snapshot()`
  moves main to the audited snapshot -- a fast-forward in effect, the
  audit snapshot descending from main's -- and `create_tag()` records
  it, IN ONE COMMIT. MEASURED: before, main saw [a]; after, [a, b];
  the tag and main both at the audited snapshot.
- `table.upsert()` exists: merge by key, for the changelog.
- Scans take `snapshot_id=`: the generation already pins snapshots, so
  a generation pinned to a published gold snapshot reads nothing else.

So Write-Audit-Publish needs no Spark, no Nessie, no new catalog.

---

# The design

    source
      -> BRONZE   raw, every column, source types        (exists)
      -> SILVER   per source table, same grain:
                    standardise -> validate -> quarantine
                    -> deduplicate -> history (changelog)
                    + lineage columns
      -> GOLD     per OBJECT TYPE, entity-centric:
                    conform -> identity -> survivorship
                    + provenance -> AUDIT -> PUBLISH (WAP)
      -> ontology reads PUBLISHED gold, snapshot pinned per generation

## Silver: faithful, validated, nothing lost

**S1. Standardise -- meaning-preserving only.** NFC; trim and collapse
whitespace; declared sentinel strings ("N/A", "", "NULL", "-") to null,
per column, never globally; type casting to the declared type (today's
transform_rows); ISO formats for dates. NO case folding, NO accent
stripping on values. Every rule declared, never inferred.

**S2. Validate -- the constraints that already exist.** Patch 297's
field constraints (min/max, min_length/max_length, pattern, one_of) ARE
expectations; silver evaluates them on every row, plus required-ness
(completeness) per column. Each declares a policy: `warn` (keep,
count), `quarantine` (route), or `fail` (the silver build fails and the
previous published gold keeps serving).

**S3. Quarantine, never drop.** Failing rows go to
`quarantine_<silo>.<table>` with the rule, the policy, the value, the
bronze snapshot they came from. Counted per run; shown in Admin.

**S4. Deduplicate by the declared key.** Foundry fails a batch on a
duplicate key; silver does the same by default -- both copies
quarantined, reported by name -- with a declared tie-break as the
opt-in alternative. A duplicate key is a SOURCE problem, and silently
picking one hides it.

**S5. History: the changelog.** ELT_ROADMAP Phase 4, as planned:
snapshot diff by id (measured at 76 ms for 200,000 rows), appended as
SCD2 rows -- valid_from, valid_to, op, row hash. Deletions are rows too.

**S6. Lineage on every row:** `_silo`, `_source_table`,
`_bronze_snapshot_id`, `_synced_at`, `_row_hash`. Gold carries them
forward, so any gold value traces to the bronze snapshot it came from.

## Gold: one row per entity, audited before anyone sees it

**G1. Conform.** One gold table per OBJECT TYPE: `gold.<object_type>`,
keyed by the object id, properties as the ontology declares them,
mapped from each contributing silver table. A single-source type is a
straight conform -- which is why the ontology can move to gold BEFORE
fusion exists.

**G2. Identity (multi-source types only).** FUSION_AND_IDENTITY.md,
unchanged: declared rules first and primary; inference off by default,
Fellegi-Sunter three-zone decisions, the middle zone to a person
through the existing approval queue. The result is a CROSSWALK table,
`gold.<type>__members`: gold id -> (silo, source id), stored data.

**G3. Survivorship, per property, declared.** trusted_source(order),
most_recent (needs S5), most_complete. Every contributing value kept in
`gold.<type>__provenance` -- gold id, property, value, source, chosen,
rule. Nothing loses its trace.

**G4. Audit, then publish.** Gold is written to a branch; the audit
checks the Foundry contract (key unique and non-null), every link's
target exists, required properties present, and row count within a
declared bound of the last publication. Pass: one commit moves main
and tags `published-<n>`. Fail: nothing moves; the last published gold
keeps serving; the failure is reported by name.

**G5. The ontology reads published gold.** The mirror adapter reads
`gold.<object_type>` instead of `<silo>.<table>`; each generation pins
the published snapshot. Roll-back (ELT item 11) becomes re-publishing
an earlier tag.

---

## What moving the ontology onto gold changes -- the dependencies

1. **Storage binding.** Today an object type is bound to (silo, table,
   id_column, columns). On gold it is bound to one gold table. Every
   read path keyed by silo -- the mirror adapter, security.via_field
   resolution, link resolution -- must key by type.
2. **Writes go to SOURCES; reads come from gold.** The write mediator
   writes a source row. Read-your-writes (the mirror overlay) must map
   that source write onto the gold entity -- through the crosswalk once
   fusion exists. F-26 and F-29 (the overlay keeping only the latest
   edit; the sync's blind window) must be fixed FIRST: gold stacks on
   the overlay.
3. **The mirror's open correctness bugs come first**, since gold builds
   on silver: F-01 (booleans never sync), F-20 (decimal in/not_in
   raise), F-19, and item 8 (a sync that fails on catalog/warehouse
   disagreement).
4. **Live-read mode cannot read gold** -- gold exists only in the lake.
   DECISION: gold requires mirror mode, or live mode stays a
   single-source escape hatch.
5. **MAC on a fused entity.** Each property keeps its source's
   classification (FUSION_AND_IDENTITY.md); but an object's security
   FIELD -- the one MAC decides visibility on -- can then disagree
   between sources. DECISION: most restrictive wins, or reject the
   merge.
6. **Which source a write to a fused object goes to.** DECISION: per
   property, the survivorship source; or declared per action.
7. **Deletes through gold.** All members deleted -> the entity goes;
   one of several -> its values leave survivorship. Needs the deleted
   index (F-28, its own pending decision) to agree with gold.
8. **Scale.** Memory binds: a sync holds a table four times over
   (ELT_ROADMAP). Gold adds a pass over every contributing table.
   Batching, and DuckDB -- already an expected dependency for the diff,
   and Splink's engine -- become necessary at size, not before.

## The owner's decisions, September 22 -- ANSWERED

**D1. Gold requires mirror mode. YES, and live-read mode is DEMOTED.**
The owner: "Demote live reading mode as it will be incompatible with
using the enriched data." Gold exists only in the lake; a live read
goes to the customer's database, which holds no standardised,
validated, deduplicated, fused rows. So `read_from_mirror: false`
becomes a documented fallback for a deployment with no gold -- warned
about at startup, not offered as an equal choice -- and config.yaml's
comment claiming live reads are the conservative default (already
false: the code defaults to the mirror) is corrected with it.

**D2. A MAC conflict on a fused entity REFUSES the merge and sends it
for review.** Each property keeps its source's classification; if the
sources disagree about the value MAC decides on, the entity is not
merged. It goes to the same queue an inferred merge goes to, with both
values shown. Quietly taking the most restrictive would hide a real
disagreement between systems and silently change who can see what.

**D3. Where a write to a fused object goes -- ANSWERED BY FOUNDRY'S
OWN MODEL, and it is not "pick a source".** In Foundry, edits made
through actions are written to a separate WRITEBACK dataset and never
overwrite the backing dataset; what the ontology serves is the
combination of the input datasources and the user edits -- its
materializations are defined as exactly that. Their training material
tells downstream consumers to read the `_edited` dataset rather than
the original backing one.

ELYSIUM ALREADY HAS THIS SHAPE: the write log plus the mirror overlay
IS a writeback dataset layered over derived data. So:

  - An edit to a fused object is recorded against the GOLD ENTITY in
    the write log and layered over gold on read. No source is picked.
  - Pushing an edit into a source silo stays possible, but only where
    an object type DECLARES a write-back target -- per property, since
    survivorship is per property. Undeclared, the edit lives in the
    overlay and is never invented into somebody's database.
  - A single-source object type declares its one source as the target,
    which is exactly today's behaviour. Nothing regresses.
  - Foundry's warning is inherited: a destructive change to a backing
    dataset can LOSE edits. Gold's audit therefore checks that every
    pending edit's entity still exists before publishing.

**D3 (second half). The mirror changing WHILE it is being read.**
Iceberg answers it: a reader uses the snapshot that was current when
it loaded the table, readers take no locks, and table changes are
atomic -- a reader never sees a partial or uncommitted change. Elysium
already pins snapshot ids per generation, so a sync or a gold publish
during a read cannot disturb it; the reader sees the whole old state or,
after a reload, the whole new one.

TWO REAL HAZARDS REMAIN, and both are design work, not luck:

  1. SNAPSHOT EXPIRY UNDER A PINNED READER. Expiring snapshots deletes
     files a pinned generation may still be reading. Iceberg's own
     answer is tags: they retain important historical snapshots.
     Every published gold snapshot is TAGGED, and expiry must never
     remove a tagged snapshot or one pinned by a live generation.
  2. ONE REQUEST, ONE SNAPSHOT (roadmap 0.5.6, still open). A request
     that outlives a reload could read half from each generation. With
     gold the answer is settled: a request pins its generation at
     arrival, and the generation pins its snapshots.

**D4. Default policy: WARN, with quarantine opt-in -- and the split
matters.** Precedent divides by WHAT the check guards:
  - PER-ROW checks: Databricks expectations default to keeping
    invalid records and counting them -- warn.
  - BUILD-LEVEL checks: dbt's tests default to error, which stops the
    build, with warn available per test and thresholds (warn_if /
    error_if) for "one duplicate is a warning, ten are an error".
  The tiering practice both feed into: critical checks fail, important
  ones warn, informational ones only report.

  SO ELYSIUM SPLITS THE SAME WAY:
  - Silver's per-row expectations default to WARN (the row lands, the
    violation is counted and shown), with `quarantine` and `fail`
    declared per rule.
  - Gold's AUDIT checks -- the Foundry contract: key unique and
    non-null, link targets exist, required properties present -- default
    to FAIL, because a gold table that breaks them cannot back an
    object type at all.
  - A declared quarantine RATE threshold fails a build the way dbt's
    error_if does: a rule quarantining 0.1% of rows is a data problem;
    one quarantining 40% is a pipeline problem.

**D5. DuckDB accepted** as a dependency when the changelog lands --
the 76 ms diff over 200,000 rows, and Splink's engine for GOLD-6.

## Sources

- Databricks, medallion architecture: docs.databricks.com/aws/en/lakehouse/medallion
- Databricks, expectations and quarantine: docs.databricks.com/gcp/en/ldp/best-practices
- dbt staging conventions (one-to-one, same grain): github.com/VasiliiSurov/dbt-project-evaluator
- DAMA six dimensions: dataworkers.io/resources/data-quality-dimensions
- Text normalisation trade-offs: apxml.com (text normalization methods)
- SCD2 from snapshots: datavidhya.com/blog/what-is-a-slowly-changing-dimension
- Palantir Foundry, primary-key restrictions: palantir.com/docs/foundry/object-indexing/data-restrictions
- Survivorship: profisee.com/blog/mdm-survivorship; marionoioso.com (golden record)
- Fellegi-Sunter, Splink: moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html
- Write-Audit-Publish, Iceberg branching: iceberg.apache.org/docs/latest/branching
