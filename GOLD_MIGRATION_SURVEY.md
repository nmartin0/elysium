# What must change for Elysium to run on GOLD

The owner, September 22: find what actually has to be reworked so that
nothing depends on the raw read-from-database layer or on silver, and
"the ontology and the ontology engine that users are interacting with,
and anything else, is interacting at the code level with the enriched
golden layer."

SURVEYED IN THE CODE, September 22, at 50bbfb1 -- by reading every
place that is STORAGE-SHAPED (silo, table, column, via_table) rather
than ONTOLOGY-SHAPED (type, id, property). That distinction is exactly
what gold changes, and it is the whole of the work.

---

## The good news, established first

**THE MEDIATOR'S PUBLIC SURFACE IS ALREADY ONTOLOGY-SHAPED.** Every
method users and the agent reach -- visible_schema, search_object,
search_object_free_text, search_around, link_counts, count_objects,
aggregate_by_field, get_field, get_object, edit_history,
reauthorize_conditions -- takes an object type, a field name and an id.
None takes a silo, a table or a column. The translation happens INSIDE.

**THE AGENT HAS NO SECOND READ PATH.** It calls the mediator and
nothing else (checked: search_object, get_object, get_field,
search_around, aggregate_by_field, visible_schema, plus propose_action
and confirm_and_execute for writes). Repointing the mediator repoints
the agent.

**THE API ALREADY HIDES STORAGE.** api/routes.py strips storage,
column, via_table and via_column from every schema response, so the UI
speaks properties already. The UI's only uses of the words are a silo
tag in ObjectDetailPanel and the Admin silo panel -- both of which are
ABOUT sources and stay.

**THE WRITE OVERLAY IS ALREADY ONTOLOGY-SHAPED.** The write log is
keyed by (object_type, object_id) and its changes by FIELD NAME, and
the overlay is consulted BEFORE a field is resolved to a column. It
therefore works against gold unchanged -- one of the pieces GOLD-3 was
expected to need and does not.

**READS AND WRITES ARE ALREADY SEPARATE.** build_generation builds the
read mediator; WriteMediator builds a SECOND mediator over WRITE
adapters with the same schema. So reads can move to gold while writes
keep going to the customer's databases -- which is decision D3, and it
needs no new separation to hold.

---

## The shape of the change: a GOLD VIEW of the schema

The adapters take a RESOLVED TYPE CONFIG -- the storage block plus the
field definitions -- and answer in terms of it. The mirror adapter
already reads `{namespace}.{table}` from the Iceberg catalog. So the
change is not to rewrite the read paths; it is to hand them a schema
whose storage says GOLD:

    storage: {silo: "gold", table: <ObjectType>, id_column: <id_field>}
    every field's `column`  -> its own property name
    every reverse link's via_table/via_column
                            -> gold.<TargetType> and the target's
                               property that holds the foreign key

built once, per generation, beside the source-shaped schema the write
path keeps. Then _adapter_for returns a MirrorReadAdapter over the
`gold` namespace, and search, filters, links, security chains,
aggregates and free text all work in gold's terms without their own
rewrites.

THAT IS THE DESIGN TO TEST FIRST, because if it holds, most of the
list below becomes wiring rather than surgery.

---

## What must be reworked, by file, with why

### core/deployment_loader.py -- the wiring point
- `_build_silo_for_type()` maps type -> silo for reads. On gold every
  type reads from one namespace; the map becomes trivial for reads and
  must NOT be reused for writes, which still need the real silo.
- `build_generation()` passes `config.schema` to the read mediator.
  It must pass the GOLD VIEW, keep the source view for writes and for
  the sync, and PIN each type to its published gold snapshot (the
  mirror adapter already takes snapshot ids).
- `_mirror_last_synced_at()` reads silver's timestamps for freshness
  and for the overlay's `since`. On gold, freshness is the PUBLICATION
  time of the gold snapshot being read, and the overlay's `since` must
  stay the SOURCE-READ time of the silver behind it -- they are
  different instants and conflating them reopens F-29.

### core/ontology/mediator.py -- the translation layer
- `_adapter_for()`, `_resolve_type_config()`, `get_column_for_field()`,
  `get_field_storage_name()`, `_filterable_columns()`: all become gold
  terms through the view. They need no per-call changes if the view is
  right -- which is the claim to prove with a parity test.
- REVERSE LINKS, two sites (the batch at ~1717 and the single at
  ~2113): both query the TARGET type's adapter using the SOURCE's
  via_table/via_column. Re-keyed, not repointed: in gold the target's
  table IS gold.<Type> and the key is a property name.
- THE SECURITY CHAIN compares storage blocks -- "same silo AND same
  table", because a column name means nothing outside one table. In
  gold every type is one table in one namespace, so that guard becomes
  "same object type", and the comparison must be rewritten rather than
  inherited: as written it would silently allow a chain it used to
  refuse.
- `additional_storage`: a type spanning two tables cannot be combined
  in one operation today. Gold conforms a type into ONE table, so the
  restriction disappears for reads -- and gold currently SKIPS such
  types (GOLD-5), so they must keep the old path until fusion lands.

### core/ontology/write_mediator.py -- stays on the source
- `_write_limiter_for_silo(storage["silo"])` and the write adapters
  keep the source view. What changes is what happens AFTER a write:
  the overlay must be consulted against gold rows (it already is, by
  type and id), and D3 says an edit to a fused object is recorded
  against the gold entity rather than pushed at a source.

### core/mirror/ -- the pipeline keeps its own shape
- sync_targets, iceberg_sync, transform, standardise, expectations,
  duplicates, lineage all describe SOURCE tables and stay as they are.
- `integrity.check_mirror()` knows silver and bronze; it must learn
  gold -- a gold table with no silver behind it, or a published tag
  pointing at a snapshot that is gone, are the new inconsistencies.
- `gold.py` grows: the published-snapshot lookup the generation pins
  to, and expiry that never removes a tagged or pinned snapshot (the
  hazard named in D3's second half).

### api/routes.py -- mostly meaning, not mechanism
- `/api/data-freshness` and `/api/silos` report the SILVER sync. They
  must report the gold publication as what a reader is seeing, and
  keep the source sync as what feeds it: two facts, not one renamed.
- The schema responses already hide storage: nothing to do.
- `/api/health` checks sources (patch 325); it should also say whether
  gold has ever been published, since "sources reachable" and "gold
  serving" are different states.

### The UI
- Nothing structural: it already receives properties. The freshness
  banner's wording changes with the fact behind it, and Admin gains
  somewhere to see quarantine counts and the last publication.

### Tests
- The parity test that matters: for every object type, every mediator
  read answers IDENTICALLY through the source view and the gold view
  on the same data. That is what makes "gold is the default" a
  measured claim rather than a hope.

---

## What this survey did NOT find, and that matters

- No second read path hiding behind the mediator.
- No user-facing API that exposes silo/table/column for reads.
- No storage-shaped keys in the write log, the pending-write store,
  the deleted index, saved views, triggers or notifications: all are
  (object_type, object_id) already.

So the blast radius is one wiring point, one translation layer inside
the mediator, two reverse-link call sites, one security comparison, and
the reporting that says which layer a reader is seeing.

## The order that follows from it

  1. Build the GOLD VIEW and prove the parity claim on the shipped
     ontology, with the source view still the default.
  2. Re-key the two reverse-link sites and the security comparison.
  3. Pin the generation to the published snapshot; make freshness and
     health report the publication.
  4. Make gold the default read path; keep the source view for writes,
     the sync, and a type gold skips (multi-source, until GOLD-5).

---

# Three directions from the owner, September 22 (evening)

## 1. The web UI should show GOLD objects, and it nearly already does

The UI receives PROPERTIES, not columns: api/routes.py strips storage,
column, via_table and via_column from every schema response. So once
the read path is gold (GOLD-3), Browse, Explore, the object detail and
the charts are showing gold objects without a line changing.

WHAT DOES CHANGE IS WHAT THE UI SAYS ABOUT WHAT IT IS SHOWING:

  - Freshness must read "published at", the gold publication the
    reader is pinned to -- not the silver sync, which is a different
    instant and a different fact.
  - An object's detail should be able to show its PROVENANCE: the
    source and bronze snapshot its values came from, which silver's
    lineage columns now carry through conform.
  - Quarantine needs somewhere to be seen. Rows held back are absent
    from gold BY DESIGN, and an operator who cannot see the count and
    the reason will read the absence as data loss.
  - Admin's silo panel keeps meaning what it means -- it is about
    SOURCES -- and gains the publication beside it.

## 2. The YAML: the logic has not inverted, it has SPLIT

The owner: "it hardly makes sense that we have a YAML file saying what
the ontology should be, when the data pipelines are cleaning the data
to naturally present the ontology."

WHAT THE FILE ACTUALLY HOLDS, counted: two kinds of statement mixed
together in one block per type.

  DECLARATION -- what an object IS: id_field, title_field, each
  field's type and data_type, link targets and cardinality, security,
  constraints, required, on_violation, standardise, duplicate_keys,
  and the action types.

  MAPPING -- where the bytes are: storage (silo, table, id_column),
  each field's column, and a reverse link's via_table/via_column.

THE PIPELINE IS DRIVEN BY THE DECLARATION, not the other way round.
Silver standardises because a field declared it; it quarantines
against constraints the ontology states; it refuses duplicate keys
because id_field says what identity means; gold conforms to the
declared properties and its audit checks the declared contract. The
data does not "naturally present" an ontology -- it presents whatever
the source happens to hold, and the declaration is what turns that
into meaning.

THE PRECEDENT AGREES, and is blunt about it. Foundry's own pipeline
tool has you "start by defining endpoint schema for Ontology object
types and properties and describing the pipeline to match inputs to
endpoints" -- the ontology is the TARGET the pipeline is built to
hit. They call it hydration. And the wider practice is a data
CONTRACT: a producer renaming a column must break a check, not
silently redefine what the consumer means. Derive the ontology from
the data and that rename becomes a new ontology, with nothing to fail.

SO THE CHANGE IS NOT "GENERATE THE ONTOLOGY FROM GOLD". It is:

  a. SPLIT THE FILE. Declaration and source bindings are different
     documents with different audiences and different change rules:
     the ontology changes when the business does; a binding changes
     when a source system does. Mixing them is what makes the file
     read as though it were describing storage.
  b. DERIVE GOLD'S SHAPE FROM THE DECLARATION -- gold table per type,
     column per property -- so after GOLD-3 the READ path needs no
     mapping at all. The mapping demotes to an INGESTION detail,
     used only by the pipeline.
  c. LET THE PIPELINE PROPOSE, NEVER DECIDE. A command that reads a
     source and PROPOSES object types, properties and bindings for a
     person to accept is worth building -- the tedious half is real.
     It writes a proposal; it does not change the ontology.
  d. KEEP THE AUDIT AS THE ENFORCEMENT. Gold already refuses to
     publish when the declared contract is not met. That is the
     contract being checked, which is what makes the declaration
     worth having.

## 3. Adapters for the outside; connectors for the inside

The owner: adapters should be strictly for reading source databases as
the first step of the pipeline; reading gold should use INTERNAL
CONNECTORS of a similar shape but designed to run inside Elysium,
because the concerns are different.

THIS SUPERSEDES WHAT THIS SURVEY PROPOSED ABOVE -- reusing the mirror
adapter against a "gold view" of the schema. That would have worked,
and it would have carried source-shaped assumptions into the one place
that no longer has them. The concerns genuinely differ:

  AN EXTERNAL ADAPTER faces a system Elysium does not control:
  credentials, a network, per-silo concurrency limits, health checks,
  unknown column types, schema drift, and data that must be treated as
  untrusted. It is READ-ONLY by construction, and that is a security
  property (Phase 1's own wording: structurally incapable of writing).

  AN INTERNAL CONNECTOR faces data Elysium wrote itself: no
  credentials, no network, no drift -- the schema is ours, generated
  from the declaration -- a snapshot PINNED per generation, a cache
  keyed by that snapshot (E-10), and answers in the ontology's own
  terms: object type, property, id. It needs none of the adapter's
  apparatus and should not inherit it.

  AND THE INTERFACES DIFFER WHERE IT MATTERS: an adapter is asked for
  `table_name`, `id_column`, `columns` and a via_table; a connector is
  asked for an OBJECT TYPE, its PROPERTIES and its LINKS. Handing a
  connector a via_table would be handing it a fact that no longer
  exists.

THE COST, stated honestly: a second read implementation, and a parity
test between the two paths while both exist. The parity test is one
this plan already needed to make "gold is the default" a measured
claim rather than a hope.

WHERE THE LINE FALLS: adapters/ stays the boundary to the customer's
systems -- reads for ingestion, and the WRITE path, which keeps going
to the source. The connector reads gold, and nothing else reads gold.
