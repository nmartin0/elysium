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
