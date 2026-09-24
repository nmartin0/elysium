# The unified roadmap

**Why this exists.** Nineteen planning documents hold roughly 12,700
lines between them -- nine and 8,500 when this file was first written.
Each is right about its own area and none can say what to do next,
because the answer depends on the others. This file is the ordering;
the detail stays where it is, and each item names its home.

**How it is ordered.** By dependency and by what would stop a
deployment, not by size or by interest. An item appears after
everything it needs and before everything that needs it.

**What this is not.** It is not a schedule and it does not estimate.
Several items below are a day and several are a month, and saying
which would be a guess presented as a plan.

---

## WHAT IS LEFT -- the one list, checked against the code

**September 21, after patch 295.** Every `.md` plan was read and each
open item checked against the CODE rather than taken at its word --
because this roadmap, the one meant to be read, described seven built
things as open and omitted most of what the other documents hold.

### Built, but some document still says open

Each checked in the code; corrected here, pointed to elsewhere.

    UNIFIED   0.5.2 decimal, 0.5.3 dates (f9b76be), 0.5.35 source types
              (258), 1.3 restore (288), 2.4 (289-291), 3.0 triggers
              (264-280), the pending-write store (276) -- all corrected
    ROADMAP   "a persistent PendingWriteStore" (245, 276); a statement
              timeout on writes (the progress handler covers them)
    BACKLOG   json_each (254); the metrics retention sweep -- it runs,
              api/app.py:376
    UI_ROAD   1 config view, 2 FHS paths, 4 silo view, 5 schema graph,
              10 untrusted-text delimiting, 17 metrics, 21 backup,
              22 object views, 24 watch-to-notify, 27 change over time,
              29 per-request snapshot, 30 approvals, 33 role editing,
              34 notes
    HOT_REL   4a re-resolve the user per hop -- refresh_user, per step
    SECURITY  2 the write-down check (260), 4 the grant algebra (262)
    OBJ_EXPL  phases 3-5: the table, the charts, saving and acting

### READ THIS FIRST: every entry below is "probably open"

Checked against the code on September 21 -- and FOUR entries were still
wrong when built against: the first-run password and graceful shutdown
were already done; log rotation and the hardened systemd unit existed
but were installed by nothing. So each entry is re-checked against the
code BEFORE it is built, and corrected here if it was wrong.

### THE GOLD LAYER, FRONT AND CENTER -- the owner's direction, September 22

    source -> BRONZE -> SILVER (standardise, validate, quarantine,
    deduplicate, history, lineage) -> GOLD (conform, identity,
    survivorship, audit, publish) -> ontology reads PUBLISHED gold

Researched and designed in MEDALLION_PIPELINE.md, which extends
ELT_ROADMAP.md and FUSION_AND_IDENTITY.md. MEASURED first: the ontology
reads SILVER (`<silo>.<table>`); bronze is never read; gold does not
exist. PyIceberg 0.12 does Write-Audit-Publish -- branch writes, then
set_current_snapshot and a tag in one commit -- tested here.

THIS ORDER GOES FIRST, and in it. The ontology reaches gold at GOLD-3,
before fusion: a single-source object type needs no identity
resolution, so gold for it is a straight conform.

  DECIDED BY THE OWNER, September 22 (reasoning and precedent in
  MEDALLION_PIPELINE.md): D1 gold requires mirror mode and LIVE-READ
  MODE IS DEMOTED -- a documented fallback, warned about at startup;
  D2 a MAC conflict REFUSES the merge and sends it for review; D3 an
  edit to a fused object is recorded against the gold entity in the
  write log and layered over gold -- Foundry's writeback model, which
  Elysium's write log already is -- and reaches a silo only where an
  object type declares a write-back target per property; D4 per-row
  expectations default to WARN, gold's audit checks default to FAIL,
  with a quarantine-rate threshold that fails a build; D5 DuckDB
  accepted.

  AND FROM D3's SECOND HALF, the mirror changing while it is read:
  Iceberg readers are pinned to the snapshot they loaded and never see
  a partial change, which Elysium already gets by pinning per
  generation. Two hazards become work: published gold snapshots are
  TAGGED so expiry cannot delete files a pinned generation still
  reads; and 0.5.6 -- one request, one snapshot -- is settled, a
  request pinning its generation at arrival.

  GOLD-0. PREREQUISITES -- gold builds on silver and on the overlay, so
          their open bugs come first, pulled forward from B1 and item 8:
          ~~F-01~~ FIXED, patch 332 (coerce reads the words every other
          database writes); ~~F-20~~ FIXED, patch 333;
          ~~F-19~~ FIXED, patch 334; F-19
          reverse link as security.via_field; ~~F-26 WITH F-29~~ FIXED, patch
          335; ~~item 8~~ FIXED, patch 336: the sync refuses,
          before reading the source. GOLD-0's bug list is DONE. And the owner's
          decisions D1-D5 (MEDALLION_PIPELINE.md
          -- gold vs live mode, MAC on a fused entity, write target,
          default expectation policy, DuckDB), with F-28, which decides
          how deletes reach gold.
  GOLD-1. SILVER, HARDENED (S1-S4, S6). ~~S1 standardisation~~ DONE,
          patch 337: NFC, trim and collapse on every string; sentinels
          declared per field; opt-out per field; a typo refused at load.
          ~~S2-S3 expectations and quarantine~~ DONE, patch 338: a
          field's constraints evaluated per row, warn/quarantine/fail
          per rule, quarantine tables that record the rule and leave
          the row in bronze. ~~S4 duplicate keys~~ DONE, patch 339:
          every copy held and the key named by default; fail or a
          declared keep_last_by as the alternatives. ~~S6 lineage~~
          DONE, patch 340: _silo, _source_table and _row_hash per row;
          the bronze snapshot as a table property, since a per-row
          timestamp would defeat the unchanged-source skip. GOLD-1 IS
          DONE; next is GOLD-2.
          S1-S4, S6: meaning-preserving
          standardisation, declared per column; patch 297's constraints
          evaluated as expectations with warn/quarantine/fail;
          quarantine tables, never a silent drop; duplicate keys
          quarantined and named; lineage columns on every row; quality
          counts per run, shown in Admin.
  GOLD-2. ~~GOLD FOR SINGLE-SOURCE TYPES~~ DONE, patch 341: built at
          the end of every sync, audited on a branch, published by one
          commit and tagged. NEXT: GOLD-2b (demote live mode) and
          GOLD-3 (the ontology reads gold).
          GOLD FOR SINGLE-SOURCE TYPES (G1, G4): gold.<object_type>,
          conformed from silver; audited on a branch -- key unique and
          non-null, link targets exist, required properties, row count
          within bounds -- and published atomically. A failed audit
          moves nothing.
  GOLD-2b. ~~LIVE-READ MODE DEMOTED~~ DONE, patch 342: a startup
          warning naming what it bypasses, config.yaml's contradictory
          comment corrected, INSTALL.md saying it plainly. NEXT: GOLD-3.
          LIVE-READ MODE DEMOTED (D1): a startup warning naming what
          it gives up, INSTALL.md and config.yaml corrected -- the
          comment there still calls live reads the conservative
          default, which the code has not done for some time.
          SURVEYED IN THE CODE -- GOLD_MIGRATION_SURVEY.md, patch 344:
          the blast radius is one wiring point (build_generation), the
          translation layer inside the mediator, TWO reverse-link call
          sites, ONE security comparison ("same silo and table" becomes
          "same type"), and the reporting that says which layer a
          reader sees. The shape: a GOLD VIEW of the schema handed to
          the read mediator, since adapters already answer in terms of
          the type config they are given. Already ontology-shaped, so
          needing nothing: the mediator's public surface, the agent,
          the API's schema responses, the write overlay, the write
          log, pending writes, saved views, triggers.
  GOLD-3. THE ONTOLOGY READS PUBLISHED GOLD -- AND SO DOES THE AGENT
          (the owner, September 22): "redirect the LLM agent machinery
          to read from the gold layer and not the lower layers ... the
          LLM will now be able to follow objects in the gold layer,
          links in the gold layer, with the gold layer actually
          providing the real, distilled objects and relationships."
          CHECKED: the agent reads ENTIRELY through the mediator --
          search_object, get_object, get_field, search_around,
          aggregate_by_field, visible_schema -- so repointing the
          mediator repoints the agent, with ONE exception that is real
          work: LINK TRAVERSAL. A reverse link today queries the TARGET
          type's adapter using the SOURCE's physical via_table and
          via_column (mediator.py's own comment records the cross-silo
          bug that taught this). On gold the target's table IS
          gold.<Type> and the foreign key is the target's PROPERTY
          name, so link resolution must be RE-KEYED, not merely
          repointed. Same for search_around and the reverse-link
          batch. visible_schema must describe gold's properties, since
          it is what the agent is told it may search by.
  GOLD-3. THE ONTOLOGY READS PUBLISHED GOLD (G5): storage bound by
          object TYPE, not (silo, table) -- the mirror adapter,
          security.via_field and link resolution re-keyed; the overlay
          mapping source writes onto gold rows; each generation pinning
          the published snapshot. Mirror roll-back (item 11) becomes
          re-publishing an earlier tag.
  GOLD-3b. AN INTERNAL CONNECTOR FOR GOLD, not an adapter (the owner,
          September 22): adapters stay the boundary to the customer's
          systems -- ingestion reads and the write path; a CONNECTOR
          reads gold, asked in the ontology's terms (object type,
          property, link) and needing none of an adapter's apparatus --
          no credentials, no network, no drift, a pinned snapshot and
          the E-10 cache. This SUPERSEDES the survey's "reuse the
          mirror adapter over a gold view". Costs a second read
          implementation and the parity test the plan already needed.
  GOLD-3c. ~~SPLIT THE ONTOLOGY FILE~~ DONE, patch 388.
          ontology_schema.yaml says what an object IS;
          source_bindings.yaml says where its data comes from (silo,
          table, column, and the table a link is resolved through).
          The loader merges them into exactly the schema it produced
          before -- asserted against the shipped deployment -- so
          nothing downstream changed. A deployment that has NOT split
          still works; binding the same type in BOTH files is refused.
          The migration script writes the bindings file and PRINTS
          what to delete rather than rewriting a commented file: its
          first version used yaml.safe_dump and deleted all 27
          comments in the shipped ontology.
  GOLD-3c. SPLIT THE ONTOLOGY FILE, and generate gold's shape from it:
          declaration (what an object IS -- types, links, security,
          constraints, actions) apart from source bindings (silo,
          table, column, via_*), which demote to an INGESTION detail
          once reads are gold. NOT "generate the ontology from gold":
          the pipeline is driven BY the declaration -- it standardises,
          quarantines and conforms because the ontology says so -- and
          a derived ontology would let a source's rename silently
          redefine meaning, which is what a data contract exists to
          stop. Worth building instead: a command that PROPOSES types
          and bindings from a source for a person to accept.
  GOLD-3d. WHAT THE UI SAYS ABOUT GOLD: freshness reading "published
          at" rather than the silver sync; provenance on an object,
          from the lineage silver carries; quarantine counts visible,
          since rows held back are absent by design and absence reads
          as loss; Admin keeping the silo panel (it is about SOURCES)
          and gaining the publication beside it.
  GOLD-8. ~~GOLD IS THE ONLY READ PATH~~ DONE, patch 385 (the owner,
          September 23: "there's no reason anymore why Elysium
          shouldn't be reading from the pristine gold layer, as
          anything else is inferior data"). The read_from_gold switch
          is gone; a mirrored deployment binds every type to published
          gold, the read mediator holds ONE reader -- the connector --
          and there is no fallback to silver anywhere. A type gold
          cannot build refuses at startup; a type not yet PUBLISHED is
          logged loudly and its reads raise, because an API that cannot
          start until gold exists cannot tell anyone why. Three bugs
          surfaced: the sync loads the same bundle and is what
          publishes gold (so `serving` is now a parameter), the WRITE
          mediator was inheriting the read schema and looking for an
          adapter called "gold", and constructing the app is starting
          the server in this codebase.
          STILL OPEN: `read_from_mirror: false` remains as a documented
          fallback that bypasses the lake entirely. Removing it is the
          next patch.
  GOLD-9. ~~LIVE READS REMOVED~~ DONE, patch 386. read_from_mirror:
          false is REFUSED at load rather than honoured or ignored,
          because a deployment that set it expects the old behaviour
          and silently giving it the new one is the worst of both. The
          startup warning, three route branches and the "reading live"
          answers are gone with it. Two real findings: a reverse link
          through a JOIN TABLE has no object type to re-key to, so the
          view keeps the table's name and the build publishes it; and
          the write path could follow reads into gold in six places
          that build a WriteMediator, so the mediator now CARRIES its
          source binding and nobody has to remember. The integration
          suite runs against a synced deployment -- one sync per
          session, copied per test.
  UI-LIVE. LIVE UPDATES, no manual refresh and no page reload (the
          owner, September 22; design in
          LIVE_UPDATES_AND_PIPELINE_BUILDER.md). MEASURED TODAY: one
          panel polls (MirrorPanel, 30 s) and everything else uses
          useFetchOnce, which never refetches; there is no streaming
          endpoint at all. Server-sent events, not websockets: one-way
          is the shape, plain HTTP keeps the cookie auth and the
          proxies, and EventSource reconnects with Last-Event-ID for
          free. THE SECURITY DECISION: an event carries NO DATA -- it
          says what KIND of thing changed, and the client refetches
          through the same authorised endpoints, so MAC and roles apply
          unchanged and no second read path exists to leak through.
          Fan-out across workers reuses the reload_epoch pattern: a
          monotonic table in SQLite, read by each stream, which also
          gives Last-Event-ID resume. Constraints to hold: no
          generation or connection held open across a hot reload, close
          within E-12's grace, caps and heartbeats, the table pruned.
  UI-LIVE-1..5. THE BUILD ORDER, from the audited inventory (parts 4-6
          of LIVE_UPDATES_AND_PIPELINE_BUILDER.md). Every event below
          already has ONE place it can be raised from -- write_log's
          pending and applied calls, notifications.notify(),
          SyncResult's single return, gold's publication,
          _write_quarantine, config_history's reload epoch -- so no
          refactor is needed to emit them.
          (1) THE SHELL'S ONE CONNECTION, the events table and the
              badge count: the smallest thing that proves the path,
              including Last-Event-ID resume, a heartbeat, caps, and
              closing inside E-12's grace while holding no generation
              or connection across a reload.
          (2) APPROVALS AND NOTIFICATIONS, tier 1 -- a proposal
              arriving, an approval landing, an unseen count -- plus
              pending changes shown ON the object, which
              pending_changes_for_ids already answers.
          (3) FRESHNESS, MIRROR STATE AND SILOS, and DELETE
              MirrorPanel's 30-second timer, so the first live panel
              also removes the last polling one. A freshness indicator
              that is itself stale is the sharpest irony in the
              product.
          (4) THE AGENT'S STREAM -- steps and tokens -- which is a
              different shape: per session, carrying data the
              recipient is already cleared to see (part 4.4), so it
              comes after the plumbing is proven.
          (5) TIER 3 as convenient: metrics, role changes, triggers,
              saved views, and deployment config, which is nearly free
              because the reload epoch is already monotonic.
          AND NOT ELIGIBLE, deliberately: search results, a table being
          filtered, an object being edited. A list that reorders while
          somebody reads it is worse than a stale one -- the precedent
          is a BANNER ("12 new results. Show them.") so the person
          decides when the ground moves.
  NOTIFY-1. ALERT MAIL, which SSE cannot do (part 5). AUDITED: no SMTP
          support of any kind exists. The precedent separates an EVENT
          from a NOTIFICATION from a DELIVERY, "keeping them apart
          prevents duplicate sends and ambiguous delivery state", and
          Elysium already has the notification -- with recipients from
          GRANTS. What is missing is an OUTBOX: one deliveries row per
          (event, user, channel), written in the same transaction as
          the event, its primary key the idempotency key. Preferences
          evaluated at SEND time; only the NOW tier mails, since email
          alerting "tends to easily become overrun with noise"; digests
          for the rest with a maximum wait. SMTP host and port in
          config, credentials as ${VAR}. And email is an outbound
          dependency in a product that otherwise has none, so it is
          optional, degrades silently to in-app, and never blocks a
          sync or a write.
  PIPELINE-BUILDER. A sub-app to build the pipeline visually (the
          owner, September 22): sources, bronze, silver rules per
          column, gold object types, links drawn as lines, with REAL
          ROWS shown at every stage and the quarantine count and
          reasons beside them. It edits the DECLARATION through the
          existing config path -- validation, config_history, the
          reload epoch, rollback -- never data, and never a second
          ontology authority. The dry run already exists: gold builds
          on an audit branch and publishes only if the audit passes, so
          a proposal can be built, shown and accepted. Depends on
          GOLD-3c (the file split) and UI-LIVE (a build finishing is an
          event).
  CONFIG-WRITE. UI EDITS REFLECTED INTO THE YAML (the owner,
          September 22; CONFIG_ROUND_TRIP_AND_UI_KIT.md). MEASURED: the
          shipped files are 104 comment lines of 127 and 90 of 162, and
          PyYAML's safe_dump keeps ZERO of them; ruamel round-trip
          keeps ALL and, with indent(mapping=2, sequence=4, offset=2),
          is BYTE-IDENTICAL to both -- so a write touches only the
          lines it changes. YAML stays the source of truth; no second
          copy in a database; the agent and outside programs keep
          reading the same files. Must hold: validate through the
          loader BEFORE writing (a file that cannot load must never
          reach disk), compare-and-set against the file on disk, a new
          GENERATION adopted at an epoch boundary rather than a live
          mutation (the read-only panel's stated reason stands), no
          secret ever written, an audit entry per write.
  UI-KIT. OWN THE COMPONENTS, don't swap one library for a bigger one
          (the owner, September 22). The risk is NOT a rug-pull --
          Blueprint is Apache-2.0, so what we have stays usable and
          forkable -- it is ABANDONMENT and design lock-in. MEASURED:
          49 import sites, 22 components, dominated by Button (62),
          Tag (42), Callout (28), InputGroup (19), FormGroup (17),
          HTMLTable (12); no grids, date pickers or comboboxes at all.
          So: a ui-kit in the repository for the twelve simple ones,
          and VENDORED headless primitives for the six where focus,
          ARIA and keyboard behaviour live (Dialog, Popover, Menu,
          Tabs, Checkbox/Switch, Alert) -- copied in, so an upstream
          change cannot strand us, as shadcn/ui switching Radix for
          Base UI demonstrated. Migrate panel by panel against the
          ~920 frontend tests, then a lint rule refusing new
          @blueprintjs imports.
  ACCESS-1..6. CLASSIFY THE DATA, NOT THE GRANTS -- agreed by the
          owner, September 22; the model and its audit are in
          ACCESS_CONTROL_PROPOSAL.md. Measured burden today: a role
          needs one grant string PER FIELD PER TYPE -- 1,050 for a
          50-type deployment. The model: tags carrying policy
          (read:tag:pii), fields inheriting their type's tags,
          classification PROPAGATING ALONG LINEAGE so a gold property
          keeps the classification of the source column it came from,
          and a scanner that PROPOSES tags. MAC is untouched and tags
          are kept away from it -- MAC answers which OBJECTS, tags
          answer which PROPERTIES. Most-restrictive-wins is stated and
          tested, `classify:` is its own permission, and per-field
          grants stay valid so nothing migrates. Build order:
          (1) tags as metadata only, enforcing nothing;
          (2) read:tag:X grants beside the existing ones;
          (3) inheritance type -> field;
          (4) propagation along lineage, with a report showing what
              inherited what, since a classification that arrives by
              derivation must be visible or it is magic;
          (5) the scanner, proposing only;
          (6) `classify:` before any of it is exposed in an editor.
  ALERT-1. FRESHNESS, DECIDED (DEV_UI.md 16.6): the deployment
          declares one expected sync interval, default 24 hours;
          thresholds are multiples of it -- warn at 1.1x, fail at 2.1x,
          which is one late run and two consecutive misses -- measured
          from the PUBLICATION, which is the clock a reader
          experiences, not the source read. A type may declare its own
          pair or declare itself exempt; a target tighter than the sync
          interval is REFUSED AT LOAD, naming both numbers, since it is
          guaranteed to alert forever. And the publication time is
          shown on every object, so staleness is visible before it is
          an alert.
  INFER-1. ~~A vLLM ADAPTER~~ DONE, patch 391. An OpenAI-compatible
          client behind the existing LLMAdapter protocol, so the engine
          is a per-deployment choice rather than a migration -- Ollama
          for a laptop or a small team, vLLM where concurrency is real
          and a GPU exists. Every failure translates to LLMUnavailable
          at the boundary, as F-22 forced the Ollama adapter to do.
          AND THE AGENT'S CONCURRENCY NOW FOLLOWS THE ENGINE: 4 for
          ollama, matching llama.cpp's own parallel cap, 16 for vllm,
          which wants requests in flight. The old default of 4 for
          everyone matched Ollama's cap BY COINCIDENCE, so swapping
          engines and changing nothing else would have shown no
          improvement at all.
  INFER-1. A vLLM ADAPTER, and raising the concurrency limit
          (SCALABILITY.md). AUDITED: agent queries run through an
          explicit ThreadPoolExecutor sized from
          max_concurrent_requests, DEFAULT 4, while ordinary reads use
          Starlette's own pool of 40 -- so reads scale to ~40 and agent
          queries to 4. The benchmarks: at one request vLLM and Ollama
          are within ~20%, and Ollama is often faster on
          time-to-first-token; past 4-8 concurrent requests vLLM leads
          by 2-9x; at saturation Red Hat measured 793 tok/s against
          Ollama's 41, p99 80 ms against 673 ms. Ollama's own default
          parallel cap is FOUR, the same as ours by coincidence, so
          swapping engines without raising the limit would change
          nothing. The adapter is small -- an OpenAI-compatible HTTP
          client behind the existing LLMAdapter protocol -- which makes
          the engine a per-deployment choice: Ollama for a laptop or a
          small team, vLLM where concurrency is real.
  GOLD-4. ~~HISTORY~~ DONE, patch 373: every publication diffed
          against the last and appended to gold_history.<Type>, keyed
          by the object's id. A first publication records nothing; a
          suspected partial read records nothing; a failing changelog
          never breaks a publication. AND NO DUCKDB, though D5 accepted
          one: measured before adding it, the pure-Python diff already
          in the tree takes 377 ms for 200,000 rows against DuckDB's
          76 -- irrelevant beside a sync that takes seconds.
  LIB-1..3. ~~STOP REINVENTING~~ RESOLVED, patch 390, and TWO OF THE
          THREE WERE REJECTED ON INSPECTION -- which is a finding about
          the original audit, not about the libraries.
          (1) cachetools: NOT TAKEN. A new runtime dependency to
              replace 52 tested lines that also refuse an entry too
              large to cache.
          (2) statistics.quantiles: NOT TAKEN, and this one was
              measured. It RAISES on a single sample -- a real case
              here, "the one success is the whole latency picture" --
              and reports values never observed: p99 of
              [1, 2, 3, 400] is 388.09. For a latency report, an
              observed value is the right answer.
          (3) SQLAlchemy's identifier quoting: TAKEN, and it fixed a
              REPRODUCED limitation rather than a hypothetical one. A
              table called `order details` or a column called `group`
              -- both legal in SQLite -- broke every query with
              `near "order": syntax error`, so a customer database
              using either could not be mapped. No new dependency:
              SQLAlchemy was already here.
          STILL OPEN: folding SQLite into the SQLAlchemy adapter
          entirely. The quoting removes the bug class; the duplication
          remains.
  LIB-1..3. STOP REINVENTING, where a library does it better
          (LIBRARY_AUDIT.md, September 23):
          (1) SnapshotCache -> cachetools: DOWNGRADED once the
              framework was read (rule 18). It would add a RUNTIME
              dependency to replace 52 tested lines that also refuse
              an entry too large to cache. If we want the assurance,
              test ours against cachetools' semantics with the library
              in the TEST dependencies. Lowest priority of the three.
          (2) _percentile -> statistics.quantiles, keeping "None rather
              than zero when there is nothing to measure".
          (3) THE REAL ONE, AND THE FIRST TO DO:
              adapters/sqlite_adapter.py builds SQL by
              f-string in 50 places while adapters/sqlalchemy_adapter.py
              uses the expression API for the same job, and SQLAlchemy
              supports SQLite. Fold SQLite in as a dialect, WRITE PATH
              FIRST, with the existing tests as the parity check --
              every interpolated identifier is a place a declared
              schema controls SQL text, and a library that quotes
              identifiers is the answer to the CLASS rather than to its
              instances. 75 files reference it, so this is real work.
          AND WHAT STAYS HAND-WRITTEN, with reasons: the changelog diff
          (377 ms per 200,000 rows, measured, against a dependency),
          aggregates (they run over already-authorised rows, so a
          dataframe would be built per request for nothing), metrics
          (persisted by design, which a scrape-based client is not),
          and coerce() (deliberately stricter than dateutil -- it
          refuses '2026-2-1' rather than guessing).
  GOLD-4. HISTORY (S5): the changelog -- ELT_ROADMAP Phase 4 -- as SCD2
          rows by snapshot diff, deletions included; DuckDB if D5 says
          so. Needed by most_recent survivorship.
  GOLD-5. ~~MULTI-SOURCE GOLD~~ DONE, patch 374, and AUDITING IT
          CHANGED THE WORK: each storage declares its own id_column and
          each field names exactly ONE storage, so a type spanning two
          databases is a JOIN, not a survivorship contest.
          Per-property survivorship and the MAC conflict D2 governs
          arise when two sources describe an entity INDEPENDENTLY,
          which is identity resolution (GOLD-6). The join is OUTER: an
          object in one storage and not the other is real, and a
          required property missing from the absent side makes the
          audit refuse. Gold's view no longer excludes these types.
  GOLD-5. MULTI-SOURCE GOLD (G2, G3): FUSION_AND_IDENTITY.md's build
          order -- declared identity rules, a crosswalk table,
          per-property survivorship, every contributing value kept in a
          provenance table.
  GOLD-6. TECHNOLOGY DECIDED, September 23, by installing and running
          the candidates (FUSION_AND_IDENTITY.md). Splink is the right
          model -- Fellegi-Sunter, MIT, and its predict() returns
          gamma_<field> per pair, so the "why did these score" the
          review needs is DATA rather than a chart; compare_two_records
          scores ONE pair on demand, which is the review screen itself.
          ITS SIZE IS A DISTRIBUTION ARGUMENT, NOT A RISK ONE (rule
          18, corrected): 186 MB across seven transitive dependencies
          (duckdb, numpy, pandas, igraph, altair, sqlglot, jinja2)
          against Elysium's current TEN direct ones -- weight most
          deployments would carry for a feature that is off by default.
          AND estimate_u_using_random_sampling IS BROKEN: "Salting
          partitions must be specified and > 1", reproduced across
          splink 4.0.8/4.0.17, duckdb 1.1.3/1.5.5 and pandas 2/3. The
          path that avoids it is the one we should want anyway --
          DECLARED m and u probabilities, verified working end to end.
          So: a matcher INTERFACE; a deterministic matcher built in
          with no dependencies; Splink as an OPTIONAL extra; declared
          weights; two thresholds; every merge still a proposal, and a
          MAC conflict still refusing it (D2).
  GOLD-6. INFERRED IDENTITY: Fellegi-Sunter (Splink, on DuckDB), off by
          default; the uncertain middle zone to a person through the
          approval queue.
  GOLD-7. ~~SCALE~~ DONE ENOUGH, patches 384 and 387. Gold now streams:
          PyIceberg's scan produces a RecordBatchReader and its append
          accepts one, and the audit accumulates a batch at a time,
          keeping only the ids uniqueness needs. MEASURED ON THE READ:
          +81.8 MB materialised against +11.0 MB streamed for 300,000
          rows of six wide columns, the residual being the id set --
          proportional to OBJECTS, not row width. NOT DEMONSTRATED
          end to end: a cold build peaked 333 MB against 321, and the
          gap did not widen at three times the row width, so the write
          side and the allocator dominate. The streaming is kept
          because it is correct and removes an O(width x rows)
          materialisation, not because an end-to-end win was shown.
          STILL OPEN: the changelog materialises the PREVIOUS
          publication to diff against, so a build holds one table's
          worth of rows whatever the new one does.
  GOLD-7. ~~SCALE~~ PARTLY DONE, patch 384, and MEASURED FIRST: a
          single-source gold build no longer materialises Python dicts.
          200,000 six-column rows cost 25.7 MB as Arrow buffers against
          154.3 MB as dicts -- 772 bytes a row, a six-fold
          amplification -- and the build itself went from 126.7 MB peak
          and 5.80s to 0.4 MB and 0.21s. STILL OPEN: the whole table is
          still materialised, so this removes the multiplier rather
          than the limit; and the dict path remains for identity
          resolution, survivorship and the changelog, which compare
          values row by row. Streaming in batches is blocked on the
          audit -- "are these ids unique" cannot be answered by a batch
          that has not seen the others.
  GOLD-7. SCALE: batching, when a table outgrows memory (ELT_ROADMAP,
          "the limit that actually binds").

EVERYTHING BELOW CONTINUES AROUND THIS, not ahead of it: B0 and the
rest are fitted between GOLD stages where they touch nothing gold
depends on.

### Build next, in this order -- the external audit first

AGREED WITH THE OWNER, September 21. Two external audit reports
(ELYSIUM-FLAWS-2, pinned to cb94943, and the review it superseded,
pinned to f4ea94e) were read in full and every item checked against dev
at 926ff1a. The reports are not committed -- they say so -- so each item
is recorded here in its own words, with its audit number, and what
checking it found NOW.

    THE SECOND AUDIT BATCH, September 22: 001FINDINGS (F-01..F-33,
    N-01..N-03, ten passes), 004FINDINGS (findings 1-8, S1-S3), AUDIT-09
    (CSS) and AUDIT-10 (ui/ closeout), all read in full and every item
    checked against dev at 4935b6a. Its items are labelled A and B so the
    numbers 1-12 below keep meaning what they meant. IDs: "004-F6" is
    004's finding 6; "F-27" is 001's; "09-S1-01" and "10-S1-01" are the
    audits'.

   A1. ~~004-F6~~ FIXED, patch 310: the cache is scoped -- a ContextVar,
       one per request, per agent query, per call; none on the mediator.
       004-F6 -- A LIVE MAC BYPASS, REPRODUCED ON CURRENT dev. The
       security cache (_security_value_cache, _security_link_cache) is an
       instance attribute of the ONE DataMediator per generation, shared
       by every user and thread, cleared only when anybody's next
       prefetch runs. Reproduced over HTTP: a us-west user reads
       cust_001; the source moves it to us-east; the us-west user reads
       EVERYTHING again -- the response even says region 'us-east', the
       value that should have denied it -- while the rightful us-east user
       is DENIED. Scope the cache to one request. Regression test: warm
       the cache, change the security field, read directly with NO
       intervening search -- the existing test clears it by searching,
       which is why it passes.
   A2. ~~F-27~~ FIXED, patch 311 -- exhaustive dispatch, a delete resume
       that never undoes a later operation, marked applied LAST -- with
       scripts/find_fabricated_creates.py, READ-ONLY, for the entries it
       already fabricated. RUN IT ON EVERY LIVE DEPLOYMENT. F-28 still
       awaits the decision below, and must come after that check.
       F-27, THEN F-28 -- WRITE-LOG INTEGRITY, REPRODUCED. Crash recovery
       dispatches two ways over three operations, so a DELETE falls into
       the create branch: the delete is lost, recovery reports
       {'resumed': 1}, and the log gains a FABRICATED 'create' with empty
       changes. Make both dispatches exhaustive, raising on the unknown
       case; add _resume_one_delete_entry; order record_delete before
       mark_applied. BEFORE DEPLOYING: query each live deployment for
       applied 'create' entries whose changes are {} -- they are the
       fabrications. Then F-28: rebuild_deleted_index(), the documented
       recovery, has no caller (every hit is a comment) -- see the
       decision below.
   A3. THE GATES THAT CANNOT SEE WHAT THEY GUARD, all measured. FIXED in
       patches 312-314: lint.sh (004-F1), the !important check
       (09-S3-02), the duplicate check (09-S3-01, and 09-S1-01 with it).
       And oxlint's React hook rules, patch 315: they run now, proven by a
       planted violation; the codebase has none.
       004-F1 -- lint.sh's lockfile step sets FAILED=1, which nothing
         reads, so drift can never fail the build. STATUS=1, and a test
         that introduces drift and expects lint.sh to exit non-zero.
       oxlint RUNS NO REACT HOOK RULES -- a conditional useState scored
         "0 warnings and 0 errors". Enable rules-of-hooks and
         exhaustive-deps, and fix what they find (10-S1-04's note).
       09-S3-01 -- the CSS duplicate-selector test now sees 1 of 204 rule
         blocks: the @layer wrapping indented every rule past its
         column-0 pattern. Match any selector, normalise whitespace, track
         media context. (Stylelint's no-duplicate-selectors is the
         audit's better answer; it is a new dependency.)
       09-S3-02 -- the !important check (now in layers.test.ts) lists
         three files by hand and misses layers.css; glob every .css.

    1. ~~E-08~~ FIXED, patches 316-317: every unit test passes on a fresh
       clone (2,041), over a deployment of its own -- synced_deployment
       or private_deployment in tests/unit/conftest.py -- and an AST
       tripwire refuses any bare call that falls back to the developer's.
       Found on the way: the sync read one deployment's silos while
       writing another's mirror (patch 316); and TEN more tests that
       read or wrote the developer's deployment -- credentials.db,
       triggers.db, write_log.db, a mirror -- while passing.
   1b. ~~E-08b~~ FIXED, patch 318: a bare AuditLog() writes to a private
       temporary file of its own, removed at exit; an AST tripwire
       refuses any production construction relying on that default.
       Measured on a fresh clone: the whole unit suite now leaves NOTHING
       in deployment/. (Chosen over making the log required: production
       already passes one everywhere, and 29 of the 58 test sites have no
       temporary directory in scope.)
       E-08b -- THE AUDIT LOG STILL GETS TEST ENTRIES. On a fresh clone
       the full unit suite leaves deployment/var/log/audit.log behind:
       DataMediator and PendingWriteStore default to a bare AuditLog(),
       whose default path is the REPOSITORY'S audit log -- "each
       defaulting one for tests", its docstring says. Production always
       passes one (build_generation), so live deployments are unaffected;
       every test building a mediator directly writes into the
       developer's audit trail. Fix the default (no path into the
       repository), which touches the ~18 hand-built mediator fixtures
       -- F-11's consolidation belongs with it.
       E-08 -- 30 UNIT TESTS FAIL ON A FRESH CLONE, not the 17 reported.
       They read the repository's own seeded deployment and fail as
       "assert 0 > 0" on a clean checkout. THIRTEEN WERE WRITTEN AFTER
       THE AUDIT, in this project's own patches, and reported green from
       a seeded working copy:
         test_action_effect (5), test_constraints_enforced (5, patch
         297), test_decimal_filter_scale (3), test_declared_triggers
         (2, 279), test_restore_gives_back_the_backup (1, 288),
         test_saved_view_evaluation (3), test_search_around_is_capped
         (2), test_security_cache_is_bounded (2), test_trigger_actions
         (3, 277), test_trigger_evaluation (2), test_trigger_recipients
         (2, 278).
       Fix: a fixture building a seeded, synced deployment in a
       temporary directory, so they keep proving something. Never
       depend on deployment/var/lib. The integration tier is clean on a
       fresh clone (403 pass) -- it already builds its own.
   1c. ~~E-08c~~ FIXED, patch 320: api.app's module-level app is built
       lazily (PEP 562), so importing the module builds nothing; and
       test_serve_requests gives serve() paths. CI's "created nothing"
       step now runs after BOTH tiers. Measured on a fresh clone: 2,051
       unit and 415 integration tests, and nothing in deployment/.
       E-08c -- THE INTEGRATION TESTS WRITE INTO deployment/var/lib.
       Found by E-09's own check: on a fresh checkout, the non-model
       integration suite leaves credentials.db, write_log.db, metrics.db,
       config_history.db and a mirror there. "Clean on a fresh clone"
       above meant it PASSES, not that it writes nothing. The same fix as
       E-08: find the writers (run each file alone, list what appears),
       give them their own directories -- then move CI's "created
       nothing" step after the integration tests.
   1d. PYTHON 3.10: INSTALL.md says "3.10 or later"; the locks were
       generated on 3.12 and nothing has ever run on 3.10. Test it (a CI
       matrix, with locks valid for both) or say 3.12.
    2. ~~E-09~~ WRITTEN, patch 319 -- .github/workflows/ci.yml, every
       step's command run in a clean 3.12 venv on a fresh clone and
       passing. NOT RUNNING until the owner pushes it and enables
       Actions; only the owner can.
       E-09 -- NO CI. A workflow running lint.sh, the unit and
       non-model integration tests, and in ui/ npm ci, npm run lint and
       npm test -- plus a job on a checkout with NO seeded data, so
       E-08 cannot return. Written here; only the owner can run it.
    3. ~~E-01 WITH E-02~~ FIXED, patch 321: validation errors drop input
       and ctx (the owner's decision); login refuses a username over 128
       or a password over 1,024 with the same 401, writing and hashing
       nothing; creation refuses the same usernames; expired attempt rows
       are deleted as failures are recorded.
       E-01 WITH E-02 -- pre-authentication, together because the second
       depends on the first.
       E-01: validation errors echo the request body. Measured: a login
       with only a password returns 422 with that password in it --
       AND /me/password (patch 300) echoes the caller's CURRENT
       password. A global handler; see the owner's decision below.
       E-02: login fields are unbounded and expired login_attempts rows
       are never deleted. Measured: a 20,000-character username wrote a
       row; a 200,000-character password was accepted for hashing. Bound
       both -- an oversized field gets the SAME 401 and writes NOTHING --
       and delete expired rows inside record_failure(). Keying by the
       RAW username stays: it stops throttling revealing which accounts
       exist. Tests assert the ROW COUNT, not only the status.
    4. ~~E-03, E-04, E-05~~ FIXED, patches 322-324: expired sessions are
       deleted as new ones are made; the CSRF token is compared with
       compare_digest, as bytes, pinned at source; every response denies
       camera, microphone, geolocation, payment and usb.
       E-03's second half -- expired sessions are never deleted. (The
       first half, hashing, is done: patch 301.) Delete them inside
       create_session().
       E-04 -- the CSRF token is compared with `!=`; use
       secrets.compare_digest, pinned at source level, since no timing
       test can be made reliable.
       E-05 -- no Permissions-Policy header; deny camera, microphone,
       geolocation, payment, usb.
    5. ~~E-13~~ FIXED, patch 325: every source checked at startup and
       named in the log; /api/silos and /api/health check the SOURCES --
       they checked the mirror, and a deleted source read healthy.
       ~~E-12~~ TESTED, patch 326: a real server, shut down mid-confirm,
       finishes it -- the write and both audit entries.
       ~~E-11~~ FIXED, patches 327-328: chat() takes a deadline and a
       TokenUsage (327); each query gathers under a deadline --
       agent.query_deadline_seconds, the owner's 300 s default "until we
       can test on better hardware" -- and its token counts are logged
       (328).
       ~~E-10~~ FIXED, patch 329: whole tables cached by snapshot. Mirror
       search_object 15.31 -> 0.99 ms (live 1.35); get_field 11.82 ->
       2.51 (live 1.46). ITEM 5 DONE.
       E-13 -- sources are not checked at startup: nothing calls
       health_check(). Report each failure by name; do not refuse to
       start. (This IS the "startup checks" item this list already held.)
       E-12 -- graceful shutdown is MOSTLY DONE (patch 305: uvicorn waits
       30 s, systemd 45 s). Still missing: the test that begins a
       confirm, shuts down, and asserts the write and both audit entries
       completed.
       E-11 -- chat() has no deadline and drops the provider's token
       counts. Moved out of "needs a capable model": a stalled FAKE
       adapter tests it.
       E-10 -- the mirror read path is 8-11x slower than live.
       RE-MEASURED on dev, the "before" any fix must beat: search_object
       1.04 ms live against 11.61 ms mirror; get_field 0.63 against 4.87.
       No table cache exists:
       cache per (table, snapshot id), which the generation already pins.
   B0. FOUND BY A3 ITSELF, once oxlint's React plugin ran: two rules it
       turns on by default, switched OFF in .oxlintrc.json with this
       entry as the reason. Each fix changes a component's behaviour, so
       each needs its own review and tests:
       react/set-state-in-effect, 10 sites -- setState called
         synchronously in an effect (usually `setLoading(true)` at a
         fetch's start, or state reset when a prop changes): RolesPanel
         (2), WatchDialog (2), ApprovalsPanel, NotificationsPanel,
         WatchList, LinkTrail, SavedViews, ExploreRelated. Derive the
         state, or reset with a key; then turn the rule on.
       react/refs, 2 sites -- a ref read during render, in the custom
         hooks useFetchOnce and useDeferredValue. Possibly intentional;
         decide, then turn it on or say why not.

   B1. THE SECOND BATCH'S CORRECTNESS FINDINGS, each reproduced unless
       marked:
       ~~F-26 WITH F-29~~ FIXED, patch 335.
       F-26 WITH F-29 -- mirror read-your-writes. get_applied_changes_since
         keeps only the LATEST edit (reproduced: two edits, the first
         lost); the merging version has no production caller. And
         last_synced_at still reports the COMMIT time, not when the source
         read began -- MEASURED: a 2 s source read left a 2.08 s blind
         window. One combined
         test: several edits across a sync boundary, the sync taking
         measurable time.
       ~~F-01~~ FIXED, patch 332.
       F-01 -- coerce("true", "boolean") raises, and the mirror calls that
         schema drift; the table can never sync.
       ~~F-15~~ FIXED, patch 389: a non-object answer raises into the
         same handler as any other unusable one, so the run finishes on
         what it gathered instead of 500ing it away.
       F-15 -- valid JSON that is not an object ([1,2], "finish", 42,
         null) crashes next_step, a 500 that discards the whole run. A test
         per shape.
       ~~F-22 WITH F-23~~ FIXED, patch 389: the adapter translates HTTP
         errors, non-JSON bodies and wrong-shaped answers into
         LLMUnavailable, and synthesis catches LLMUnavailable rather
         than one adapter's library exception -- a handler that had
         become unreachable.
       F-22 WITH F-23 -- the Ollama adapter leaks HTTPError and KeyError
         instead of LLMUnavailable, and synthesis catches
         RequestException, so a real outage propagates. One change.
       ~~F-14~~ ALREADY FIXED, and UNTESTED until patch 389, which is
         how a fix becomes a regression. Four tests now hold it.
       F-14 -- a parameter used only in a sub-write's criteria is rejected
         at load (reproduced); two defects in one function.
       ~~F-19~~ FIXED, patch 334: refused at load, by one shared rule.
       F-19 -- a REVERSE link accepted as security.via_field (reproduced),
         then a raw OperationalError on the read path.
       ~~F-20~~ FIXED, patch 333: every operator's literals go through
       _decimal_literal.
       F-20 -- MEASURED, and narrower and worse than reported. PyIceberg
         binds a string literal to the column's type, so on integer, float
         and date columns the asymmetry is harmless. On DECIMAL columns it
         is not: the scale fix (_decimal_literal) reaches only `equals`,
         so `in` and `not_in` RAISE "scales differ". Reproduced end to end
         on the shipped mirror: amount equals 49.99 -> 2 results; amount
         in [49.99] -> ValueError. A chart's "keep" cross-filter IS an
         `in`. Quantise in/not_in literals and range bounds too.
   B2. THE SECOND BATCH'S MEDIUM FINDINGS:
       ~~F-04~~ fixed in patch 327, with E-11's contract.
       F-04 the limiter's chat(*args, **kwargs) erases the typed
         signature; F-05 the rate limit checks then records in separate
         transactions; F-06 DeploymentConfigResponse duplicates
         DeploymentConfig with nothing checking them against each other;
         F-21 entries_for_request readlines() the whole audit log; F-24
         the Claude adapter passes the system prompt in argv (~128 KB,
         then an untranslated OSError); F-30 create_colleague_user makes
         the same debug/'a' account with no guard; F-33 the pending-write
         ownership check and session expiry are each defended by one test
         -- MEASURED by mutation over both suites: the ownership check
         F-33 named was REPLACED by the approvals work's may_claim, which
         8 tests catch at two layers (5 store, 3 route) -- resolved. Session
         expiry is caught by exactly ONE test,
         test_session_store.py::test_expired_session_returns_none -- add a
         second at get_current_user.
       004-F7's LEFTOVER: confirming is re-authorised now (verified: a
         customer moved out of region is not written) -- but the proposer
         is then told "awaiting_other_reviewers" when nobody can approve
         it. Say so, instead of stranding it until expiry.

    6. THE OWNER'S DECISIONS, built as decided below: E-06, E-07, E-14.
    7. DOCUMENTATION THAT SAYS WHAT IS NO LONGER TRUE, one commit each:
       E-15 requirements.txt calls lockfiles "deliberately deferred";
         both lockfiles exist and lint.sh checks them.
       E-16 README's "Single OS process" limitation -- WORSE than the
         audit says: patches 292-295 made reloads, role approvals,
         generation numbers and capacity caps work across processes.
         Write down exactly what is now guaranteed, and no more.
       E-17 README says links cannot cross silos; they can, and
         test_cross_silo_links records it.
       E-18 SECURITY_ARCHITECTURE.md still heads a closed hole "THE
         REAL HOLE"; the write-down check was built in patch 260.
       E-19 UI_ROADMAP.md lists log rotation as missing -- it ships and,
         since 305, is installed -- and says there is no migration
         mechanism; there is one, ad hoc. The true gap is narrower: no
         store records a schema version (see item 12).
       From the earlier report: INSTALL.md never puts the seed and sync
         steps beside the test command; and the prompt-injection
         boundary -- the synthesis call has no tools, every step is
         re-authorised against the caller's grants -- is stated nowhere,
         so nobody later "improves" the synthesis call by giving it one.
   B3. THE SECOND BATCH'S DOCUMENTATION, alongside item 7:
       004-F2 references to paths and symbols that do not exist
         (core/tools/, DataSiloAdapter, _ADAPTER_REGISTRY, App.jsx and
         more), including README section 5's extension table and the
         shipped config.yaml -- plus a check that every path the docs
         name exists; 004-F4 Shell.tsx still reasons about "only three
         real nav items"; 004-F5 the README never mentions app-schema or
         ChartsPanel; 004-F8 access_control.py claims to be the ONLY
         enforcement point while the write path calls _security_allowed
         directly -- route it through check_access(), or correct the
         claim; F-12a policy_validation's "SEVEN REAL GRANT PATTERNS" --
         worse now, with manage:roles and manage:escalation added.
       ui/README.md (10-S1-01..04): "no design system" on a Blueprint UI;
         app-schema missing; package contents a snapshot of an older
         codebase -- MEASURED WORSE: api.ts exports 49 functions (the
         audit counted 30) and the README names none of notes, history,
         aggregate, trace, silos, deployment config or freshness, and five
         of app-browse's seven components; "five separate checks", then
         four listed.
       config.yaml's mirror block says both keys "default to the
         conservative answer ... reads going to the customer's own
         databases"; the code defaults read_from_mirror to TRUE.
       ui/index.html (10-S2-01, 10-S2-02): no <noscript>, no favicon.
   B4. CSS (AUDIT-09):
       09-S1-01 the collapsed sidebar is defined twice, index.css:609
         and :1283, same layer, no media query: :609 is dead and its
         comment cites an aria-hidden Shell.tsx removed on purpose.
         Delete it. 09-S3-03 a duplicated dvh comment block, citing "the
         vh line above", which is not there.
       09-S1-02's follow-up: layers ARE in use now (fixed), so the three
         specificity-stacked Blueprint overrides (index.css :277, :340,
         :959) can go.
       09-S2-01 four rules for markup the Blueprint migration removed;
         09-S2-02 three tokens defined and never used -- delete them and
         add the converse assertion to tokens.test.ts.
   B5. THE SECOND BATCH'S LOW FINDINGS: F-07 one via_table destructuring
       at four sites -- a helper in core/; F-08 state the precondition
       submission_criteria's skip depends on; F-10 _generation(request)
       by hand 51 times (was 31) where get_generation is a dependency;
       F-11 the mediator() fixture duplicated (18 files define one); F-13
       get_object() audit entries carry no request_id; F-17 every action
       parameter shown to the model as a quoted string; F-31
       ObjectNotes.submit ignores session expiry; F-32 api.ts reads an
       untyped body.detail. F-16 (regraded LOW): its real remedy is the
       fixtures -- a cross-type action, a numeric mirror column, a
       delete in the resume fixtures -- and belongs with item 1.

    8. ~~A SYNC THAT FAILS~~ DONE, patch 336.
       A SYNC THAT FAILS when the catalog and warehouse disagree,
       instead of leaving it to check_mirror (BACKLOG).
    9. PENDING WRITES MARKED UNAPPLYABLE AT RELOAD, so the inbox never
       offers one that cannot be approved (HOT_RELOAD 6).
   10. SYNC FAN-OUT over a bounded pool (UI 11).
   11. MIRROR ROLL-BACK, 0.5.4's second half.
   12. SCHEMA MIGRATIONS -- narrowed by E-19: per-store migration
       callables exist; no store records a schema version (3.3, UI 16).

### Decided by the owner, September 21

    - E-01, the error shape: drop `input` and `ctx` from validation
      errors, keep `loc` and `msg` -- after checking what ui/ reads.
    - E-06: silo failures reported in a closed vocabulary --
      unreachable, missing, empty, refused, misconfigured, unknown --
      not the runtime's exception class names.
    - E-07: every id is a string, on both read paths.
    - E-14: delete MemoryGuard -- built, tested, used by nothing, and
      PRINCIPLES.md 7 says nothing is built for a caller that does not
      exist.
    - E-20: PROPOSE a consolidation of the roadmap files; do not
      perform one.

### AUDIT INTAKE, 24 September -- TWO sets, 273 items, none yet checked

    THE WORKING LIST IS AUDIT_CHECKLIST.csv: one row per verifiable
    claim, 273 rows, every id unique, with source, severity, the claim,
    where to look, the probe that reproduces it and a status. 203
    unverified. The two prose intakes (AUDIT_INTAKE.md,
    AUDIT_INTAKE_PIPELINE.md) explain; the CSV is what gets worked
    through.

    ONE GAP TO CLOSE WITH THE OWNER: the ui/ audits supplied are 09 and
    10 of a series of ten. They cite specific findings from audits 01,
    02, 03, 05, 06, 07 and 08 -- S2-04, S2-05, S2-06, S3-01, S1-02,
    S1-03, S1-05, S3-05, S4-01, S4-07 -- which were never supplied. Ask
    for them before calling the ui/ surface covered.

### AUDIT INTAKE, 24 September -- TWO sets, none yet checked

    A SECOND SET arrived the same day: 14 files, 13,360 lines, pinned to
    a598ed0, with 26 reproduction probes printed in full. Recorded in
    AUDIT_INTAKE_PIPELINE.md. 154 distinct ids, and the ids understate
    it: the test tier it ships encodes 57 separately failing
    behaviours, F6 and A15-A18 are eight findings under two headings,
    and the dirty-data zoo is 25 cases of which 20 behave wrongly. Over
    200 distinct broken behaviours between the two sets.

    CHECKED FIRST, in this order:
      PA001-M1  CONFIRMED AND FIXED, patch 402. The audit was right
                and I was wrong: table.maintenance.expire_snapshots()
                works (15 snapshots to 3). Six places in this
                repository said it could not be done, each saying
                "checked, not assumed". Gold expires its own now,
                under the seven-day margin the retention guard already
                required. Expiry reclaims METADATA, not disk -- so
                patch 397's conclusion survives its wrong reason.
      PA001-X2  CRITICAL: the agent crashes on any decimal or date
                field, in the SHIPPED configuration.
      PA001-X1  CONFIRMED AND FIXED, patch 404. One cross-region row
                reproduced it: link_counts said 2, get_field returned
                3. Now filtered like link_counts.
                RAISED BY IT, NEW-1: a FORWARD single-valued link still
                returns its target's id when that object is hidden.
                That id is a foreign-key COLUMN of the caller's own
                visible row, so withholding it changes what reading an
                object means and could break legitimate joins. YOUR
                DECISION; today's behaviour is pinned by a test so it
                cannot drift while you make it.
      AL-1      CONFIRMED AND FIXED, patch 405. All three shapes
                reproduced. Fixing the signature alone was not enough:
                the values then reached the adapter, which raised
                ProgrammingError, also outside the caught set. Both
                halves landed, and a bad shape is now a recoverable
                mistake the model corrects.
      F1        CONFIRMED AND FIXED, patch 406, together with A9
                because the audit was right that F1 is incomplete
                without it. Bronze now widens as silver always has,
                and the changelog widens and reads only what the old
                snapshot holds.
      F2        CONFIRMED AND FIXED, patch 407. A bronze table
                EXISTING is not the same as this run's bronze being
                current; only _write_bronze knew, and it does not
                keep it to itself now.
      F5        CONFIRMED AND FIXED, patch 408. SIX call sites, not
                the four reported: five hard-coded a local warehouse
                and only the WRITER honoured mirror.storage. One
                factory now, plus a tripwire test, because the defect
                was not a bad line -- it was the same line copied five
                times.

    Then 004-6 and 004-7 from the first set, then the rest by severity.

### AUDIT INTAKE, 24 September -- 78 findings, none yet checked

    Six audit files arrived and every finding in them is recorded in
    AUDIT_INTAKE.md, which also maps the eleven issues that appear
    under two or three different IDs across files.

    NOTHING IS ON THIS ROADMAP FROM THEM YET, deliberately. A finding
    earns a roadmap entry once it has been reproduced against the code
    as it stands, or shown not to reproduce. The audits are pinned to
    commits hundreds behind dev -- 001FINDINGS to a 1,321-test suite,
    004FINDINGS to 120d1b2, ELYSIUM-FLAWS-2 to cb94943 -- so a good
    number are already fixed, and at least one is likely overstated in
    the way OPEN_RISKS item 5 turned out to be.

    FIRST TO CHECK, because they are the most severe and the least
    likely to have been touched by any work so far:

      004-6  a STALE SHARED SECURITY CACHE allowing cross-region
             reads. The audit reproduced it over HTTP: after an object
             moved region, the old user kept access and the rightful
             one was denied. If it still holds it outranks everything
             else in all six files.
      004-7  CONFIRMING A WRITE DOES NOT RE-AUTHORISE IT. Reproduced:
             the same action refused when proposed fresh, applied from
             a proposal made 15 minutes earlier.

    Then 001FINDINGS by severity, then the E- items, then ui/.

### Needs a decision from a person

    - F-02, WITH F-03 IN THE SAME CHANGE -- no valid policy can authorise
      a cross-TYPE action: the validator rejects every write: grant, and
      the write path demands one per field (reproduced). Restore write:
      as a grant, or drop the demand and rely on execute: alone -- the
      second changes the authorisation model. F-12c -- the rejection
      message claims write: is "not enforced anywhere" -- goes with it.
      F-03's KeyError on a delete
      surfaces the moment either lands.
    - ~~F-28~~ ANSWERED, patch 397, and MEASURING CHANGED THE ANSWER.
      The audit recommended the script "given the scan's cost"; a
      rebuild is one pass, 22 ms per 10,000 log rows, 206 ms per
      100,000, 1.07 s per 500,000. And any CHECK is also one pass, so
      detection could never be cheaper than the rebuild it avoids --
      which rules out the middle option I had proposed. A WATERMARK
      escapes both: the index remembers the highest log row it has
      consumed, and a boot compares two integers. Measured on 50,000
      rows: 80.9 ms to rebuild, 0.39 ms to find current, 1.25 ms to
      catch up after one write. The script remains for an index that
      is WRONG rather than behind.
    - F-28 -- rebuild the deleted index at startup, or by an operator
      script. The audit recommends the script, given the scan's cost.
    - F-18 -- the agent can emit only equality filters; widening it is a
      feature, not a fix.
    - ~~`range` on a DECIMAL field~~ ANSWERED, patch 396: a GAP, not a
      decision. decimal is an exact numeric type and SQL has never
      excluded it from BETWEEN. Fixing it exposed a worse bug on the
      source path: a TEXT money column compared LEXICOGRAPHICALLY, so
      100.00 was an amount between ten and fifty.
    - `range` on a DECIMAL field is refused outright, so money cannot be
      filtered by amount. Found while measuring F-20; no report raised it.
      Deliberate, or a gap?
    - ~~004-F3~~ ANSWERED, patch 396: DOCUMENTED, not renamed. The
      boundary word is the industry's (OpenAI deprecated `functions`
      for `tools` in 2023 and now rejects both together; MCP says
      tools), and renaming the inside buys nothing anyone outside can
      see. Five places pointed at a core/tools/ package that does not
      exist, which is what an unstated mapping looks like after a
      while.
    - 004-F3 -- "tools" at the config and API boundary, "functions" in
      the core. Renaming the boundary changes a config key and an API
      field; documenting the mapping does not.
    - E-21 -- repository visibility. LICENSE describes unpublished
      proprietary source; the repository is publicly readable. Only the
      owner can decide this.
    - Whether one request pins one mirror snapshot (0.5.6).
    - Query's starter questions -- deferred because a starter can leak
      what MAC hides (QUERY_PLAN part 1).
    - The context-rot fix (R2): three paths, measured, none chosen.

### Needs a capable model -- 2.2 first

    - Measuring the loop, capping what a step returns (= R2's fix),
      where the effective window ends (UI 14-15, 23). Token counts and
      a deadline moved to E-11: a fake adapter tests them.
    - An eval harness with baselines (UI 25); the labelling experiment,
      then query with memory (UI 40, 41).
    - Every model-behaviour question in IDEAS.md.
    - An OpenAI-compatible adapter (UI 19).

### Product features

    - Query: reading the question back, follow-on questions, history
      (QUERY_PLAN 2-4).
    - Saved SELECTIONS -- a set of objects rather than a question
      (BACKLOG).
    - The search bar's five unbuilt operators (UI 18).
    - The instance graph beyond one hop, "full Vertex" (UI 32).
    - Parallel multi-silo reads (UI 20); silo editing (35); a scheduler
      (36); explaining a result (37); scenarios (39).
    - Watch-to-ask (31); watch-to-run-the-agent (38).
    - An agent-audit view -- scripts/agent_trace.py exists, nothing
      shows it (28).
    - Interfaces and shared properties (ROADMAP).

### Larger designs, written and unbuilt

    - The plugin API (3.1, THIRD_PARTY_EXTENSIONS).
    - The help assistant (3.25).
    - Fusion and identity -- the gold layer (3.6).
    - Bootstrapping a deployment from a manifest (LAKE_METADATA_NOTE).
    - Something that READS the ELT changelog.

### Deliberately held, with the trigger named

    - PostgreSQL row-level security for MAC; column GRANT with SET ROLE;
      the table-size ELT item.

### Waiting on a person running something, not on code

    - --workers FOR REAL. Patches 292-295 fixed all four blockers; it has
      only ever run as two apps inside one test process.
    - THE WATCH LAYOUT CHECK, rewritten in patch 290 and never seen to
      pass:  cd ui && npx playwright test -g "Watch recipient"

### Done since this inventory was written -- patches 297-305

    - Field-VALUE constraints on the field, checked at proposal and at
      confirm (297).
    - An administrator could reach manage:roles by creating an account
      (298) or by a role edit adding a grant they lack (299) -- both
      closed, Kubernetes' rules, with manage:escalation as `escalate`.
    - NIST SP 800-63B-4 password policy; change your own; an
      administrator's reset; every account action audited (300).
    - Session tokens stored as SHA-256, raw rows destroyed (301).
    - A reset forces a change at next login (302).
    - The frontend lint, failing unseen since 280, fixed -- and the gate
      is now `npm run lint`'s EXIT STATUS, not a count of one step's
      output (303).
    - The password UI: Change password in the user menu, Reset password
      in Admin -> Users (304).
    - ONE systemd unit, hardened, installing its log rotation, with a
      guard against a second; shutdown bounded, uvicorn 30 s and
      systemd 45 s (305).

### The second batch: already fixed, checked

    - 004-F7 confirm re-authorises now (verified; leftover in B2).
    - F-25 generation numbers: fixed by patch 294, including numbers no
      longer consumed by loads that fail validation.
    - 004-S1 session tokens stored raw: fixed by patch 301.
    - F-12b the false "STRUCTURALLY read-only" claim: gone.
    - 09-S1-02 cascade layers declared and unused: used now.
    - 004-F4's api/app.py comment: gone. (Its requirements.txt line is
      E-15; its Shell.tsx line is in B3.)
    - Overlaps: 004-S2 expired sessions = E-03; F-09 is moot once
      MemoryGuard is deleted (E-14).

### Deliberately NOT to be fixed (the second batch's N-01..N-03)

    - N-01 the duplicated denial-logging block in mediator.py: two
      occurrences; the rule of three says wait.
    - N-02 user_directory.py's bare commit(): a convention split, not a
      bug -- one connection, one commit.
    - N-03 Protocol vs ABC: document the Protocol side; do not unify.

### Checked afterwards -- what was first recorded as unverified

    Each of these was listed here as unverified, then measured, and the
    entries above carry the results: F-33 (mutation run over both
    suites), F-20 (PyIceberg on integer, float, date and decimal
    columns, then end to end on the shipped mirror), F-29 (a slowed
    source read), E-10 (re-timed), and 10-S1-03 (every component and
    endpoint family counted).

    FOUND WHILE DOING IT, and not in any report: `range` is refused
    outright on decimal fields ("Operator 'range' cannot be used on field
    'amount'"), so money cannot be filtered by amount -- "transactions
    over $500". Deliberate or not is a question for the owner.

    STILL UNVERIFIABLE: AUDIT-09 and -10 cite Audits 01-08, which were
    never provided. Only the one claim measured here -- that oxlint runs
    no React hook rules -- is known to hold.

### The audit verified these correct -- do not re-litigate

    - SQL injection through field and type names: blocked -- a closed
      filter vocabulary, validated against the caller's own schema.
    - The read-only connection: engine-enforced; UPDATE, INSERT, DELETE,
      DROP, ATTACH and writable_schema all denied.
    - The login timing side channel: closed, within noise.
    - Lockout at exactly 5, with the same generic 401.
    - Uniform 401 on every protected route, unauthenticated.
    - CSRF as middleware: missing, wrong and absent all the same 403.
    - No dangerouslySetInnerHTML, innerHTML, eval or new Function in ui/.
    - import-linter's contracts: enforced, not aspirational.
    - The second batch: 9 of 9 security mutations caught (disabling MAC
      fails 48 tests; authorize() always-grant, 42); concurrent audit
      writes do not corrupt; argon2 with a dummy hash; CSRF
      double-submit (004-S3); zero XSS sinks, zero credentials in browser
      storage, zero type escapes in ui/; zero !important and no colour
      literals outside tokens.css; two z-index values in all the CSS.
    - NOT A FINDING, and agreed: no idle session timeout, only the 24-hour
      absolute cap -- unless a compliance requirement arrives.

### Process changes the audit forced

    - THE TESTS RUN ON A FRESH CLONE for every patch, not only the patch
      apply. Applying there and testing in a seeded working copy is how
      thirteen tests were reported green that fail for anybody else.
    - `npm run lint` is judged by its EXIT STATUS (patch 303).
    - A GATE IS CHECKED FOR WHAT IT CAN SEE, not only that it passes:
      lint.sh could not fail on lockfile drift, oxlint ran no hook rules,
      and the CSS duplicate check saw 1 of 204 rules -- each green while
      blind.
    - Anything larger than one commit gets agreement on its shape first,
      as CLAUDE.md asks.

### Why this section exists

Seven of this document's own headings described finished work, found
only by checking. That is the backup inventory's failure (281) in
prose: a hand-kept list with nothing comparing it to the code. Prose
cannot be tested the way OWNED_DATABASES now is, so the substitute is
this -- re-check against the code before trusting any entry, and keep
the check's date on it.

---

## Where this stands, September 19

**PHASES 0, 1 AND 3.5 ARE COMPLETE.** The four blockers the commercial
audit named -- no real database adapter, unbounded search, unbounded
cache, no query timeout -- are closed, along with the live-read
coercion that had to precede them and the four items of phase 0.5.

    0.0  live reads honour the declared type        DONE
    0.1  an adapter for a real database             DONE
    0.2  a row limit that reaches the query         DONE
    0.3  a bound on the security cache              was already bounded
    0.4  a silo query timeout                       DONE
    0.5  the mirror becomes the read path           DONE
    1.1  persist the pending write store            DONE
    1.2  fsync before the catalog pointer swap      DONE
    1.3  backup and restore                         DONE
    1.4  secret indirection                         DONE

    3.5  non-user-derived constraints               DONE
         trace id, write-down check, attenuation,
         and the grant algebra as universal tests

**FOUR ENTRIES WERE WRONG ON INSPECTION** and are corrected in place
rather than deleted, because the mistake is more useful than the
absence:

    0.3    the caches were already bounded
    0.5.5  the sync already reported every drifted column
    3.5    "ordered or incomparable" was a false choice -- a
           Bell-LaPadula label has BOTH, and Elysium's values are
           compartments
    3.5    "intersection for action authority" had nothing to
           intersect: an action declares no authority of its own

**ALL FOUR WERE WRONG IN THE SAME DIRECTION** -- describing a defect
that reading the code carefully would have ruled out. That is a
prior worth carrying into the remaining design documents.

**WHAT REMAINS IS ORDERED BY DEPENDENCY BELOW.** Phase 2 needs
nothing. Phase 3 needs research. Phases 3.5 and 3.6 are designed and
unbuilt. The items in "Found on review" have no phase yet and are
placed where their dependencies put them.

---

## Phase 0 — Elysium cannot read a customer's data

Everything in this phase is a blocker for any commercial use. None of
it is interesting and all of it is required.

### 0.0 ~~Live reads honour the declared type~~ DONE

**THE PRE-POSTGRES COMMIT**, measured: the same field and ontology
returned `Decimal('49.990000000')` from the mirror and `49.99` as a
FLOAT from the silo. The sync coerces into silver; a live read handed
back whatever the driver produced.

It comes BEFORE 0.1 because psycopg returns Decimal, datetime, date
and UUID objects -- none of which the ontology's vocabulary names --
so an adapter would have widened this gap rather than revealed it.

**A FAILURE IS REPORTED AND SERVED.** The sync can refuse a whole
table because a refused sync leaves the previous snapshot standing; a
read has no previous value, and refusing would turn a type
disagreement into an unreadable object.

**THE SECURITY-VALUE PATH IS DELIBERATELY EXCLUDED** -- it is compared
for equality against the user's own, and changing the representation
of one side of the comparison that decides authorization is not worth
tidying a region name for.

**ONE HONEST DIFFERENCE REMAINS:** the mirror returns a decimal at
storage scale (`49.990000000`), the live path at source scale
(`49.99`). Numerically equal, and `decimal_places` governs display, so
the two agree everywhere a user looks -- but `str()` differs.

### 0.1 ~~An adapter for a real database~~ DONE

**ON SQLALCHEMY CORE, NOT A NATIVE DRIVER.** Our queries are simple --
no joins, no subqueries, no window functions -- so almost everything
that differs between engines is what Core's dialects handle:
placeholder style, identifier quoting, row-limit syntax, and schema
introspection.

**THE LAST DECIDED IT.** The schema-drift work needs to know what a
source says its column types are, and hand-writing that means
information_schema, PRAGMA, ALL_TAB_COLUMNS and sys.columns -- four
dialects of one question. Core's Inspector answers it once.

**Airflow is the precedent:** SQLAlchemy underneath, with
per-database overrides where they matter.

**THE SQLITE ADAPTER IS UNTOUCHED**, serving Elysium's own storage on
the stdlib module. Two mechanisms, divided on a real line: embedded
fixture storage against a customer's real database.

**VERIFIED AGAINST A REAL POSTGRESQL 16.2**, not a mock. `pgserver`
ships the server as a wheel, so the adapter's 19 tests exercise a
genuine engine -- which is what removed the objection that an untested
database adapter would be the largest unverified thing here.

### 0.1 (original note)

**THE SINGLE LARGEST GAP.** `_LLM_ADAPTER_REGISTRY`'s sibling holds
exactly one read adapter: `sqlite`. There is no PostgreSQL, MySQL,
Snowflake, REST or object-store adapter. The ontology is genuinely
silo-agnostic and the mirror is Iceberg — and there is nothing to
connect to a customer's actual data.

ROADMAP.md discusses PostgreSQL at length, but as ELYSIUM'S OWN STORE,
which is a different question and correctly deferred. Reading a
customer's PostgreSQL is mentioned once, in passing, and planned
nowhere.

**Blocks:** every commercial conversation. A prospect's first question
is whether it reads their warehouse.

**Depends on:** nothing. The adapter interface already exists and has
two implementations (`sqlite`, `inmemory`) — which is the two-reference
test a plugin surface is supposed to pass.

### 0.2 A row limit that reaches the query -- MAC PUSHDOWN DONE

**THE FIRST HALF IS BUILT.** A `field:` security declaration is now
pushed into the query as a condition, so the database returns only
rows the user may see. The canonical name is PREDICATE PUSHDOWN; what
cannot be pushed is the RESIDUAL predicate.

**MEASURED BEFORE:** 200,000 rows cost 0.70s and 66MB, extrapolating
to ~35s and ~3.3GB for ten million -- per request, before filtering.

**`via_field:` CANNOT BE PUSHED** and ontology_schema.yaml now says
so, because it is a schema choice with a performance consequence. A
known hazard rather than a local limitation: the row-level-security
field guidance is "keep predicates join-free", and Databricks'
SecureView barrier forces full scans for the same reason.

**AND THE LIMIT IS BUILT.** `find_ids` takes one, SQLite emits
`LIMIT n`, and pyiceberg takes a limit natively so the mirror stops
reading rather than trimming. `MAX_SEARCH_SCAN` is 10,000 -- far above
the API's own MAX_PAGE_SIZE of 500, far below where the fetch hurts.

**MEASURED:** 200,000 rows went from 858ms and 66MB to 49ms and
3.2MB, on a table twenty times smaller than the one that would have
exhausted memory.

**ONE MORE THAN THE CEILING IS READ**, which is how "we stopped
looking" is distinguished from "that was all of them" without a second
query.

**AND THE CALLER IS TOLD.** `scan_truncated` on the search response,
and a Browse banner saying the search STOPPED rather than that there
is more -- because where MAC is residual the ceiling bounds a scan
whose survivors are filtered, so the rows beyond it might all have
been invisible anyway.

**THE FREE-TEXT PATH WAS UNCAPPED**, which is the route Browse
actually uses: the first ceiling only reached `search_object`. Both of
its fetches are capped now.

**0.2 IS DONE.**

### 0.2 (original note)

`search_object` takes no limit. It returns every matching id, MAC
filtering happens after the fetch, and the adapter's read is a bare
`fetchall()`. API paging is cut in Python from a `total` already in
memory.

A ten-million-row table is therefore a ten-million-row fetch into
Python, per request, before filtering. Invisible on the dev fixtures;
an OOM on the first real query.

**Blocks:** 0.1 being usable. An adapter for a real database without
this makes the failure worse, not better, because real databases hold
real volumes.

### 0.3 ~~A bound on the security cache~~ THE ENTRY WAS WRONG

It said the caches "accumulate one entry per object ever
security-checked" and that a long-running deployment "grows memory
monotonically".

**MEASURED, AND THEY DO NOT.** Twenty-one identical searches leave the
cache exactly as one search does, and a search of a different type
REPLACES its contents. Both writes live inside
`_prefetch_security_values`, which CLEARS FIRST -- the words "cleared
only at the start of a bulk prefetch" were in the entry, and I read
them as a weakness rather than as the bound.

**SO THE BOUND IS ONE SEARCH'S CANDIDATE SET**, which 0.2 capped.
Verified against a patched ceiling: 2 gives 3 entries, 1 gives 2.

**PINNED ANYWAY, because the bound is INCIDENTAL.** Nothing declared
it, and a write added outside the prefetch would restore the growth
the entry feared with no test objecting. A source-level tripwire now
asserts every write happens where the clearing does.

**THE SECOND ROADMAP ENTRY THIS WEEK TO BE WRONG ON INSPECTION**, and
both were wrong in the same direction: describing a defect that
reading the code carefully would have ruled out.

**Blocks:** any deployment that stays up for a week.

### 0.4 ~~A silo query timeout~~ DONE

**THE ENTRY WAS RIGHT, this time.** No adapter set one, verified
before building.

`set_progress_handler` is SQLite's own mechanism -- a callback every
10,000 virtual-machine instructions, returning non-zero aborts with
OperationalError("interrupted"). Measured: a runaway query stops at
0.20s against a 0.2s deadline, and an ordinary one runs in 0.1ms
untouched.

**WRITES TOO**, inherited from the read adapter. Verified that an
aborted write leaves NOTHING behind -- zero rows -- because a
half-applied write would be far worse than a slow one.

**30 SECONDS BY DEFAULT**, per silo overridable, 0 to disable.
Documented in data_silos.yaml.

**BUILT BEFORE THE ADAPTER THAT NEEDS IT**, deliberately: a timeout
added alongside the first network adapter would be a timeout nobody
had ever watched fire.

**Depends on:** 0.1 in practice. SQLite on local disk rarely hangs; a
network database routinely does.

---

## Phase 0.5 — The mirror becomes the read path

**DECIDED:** `read_from_mirror` defaults to TRUE, and direct silo reads
become a secondary option on the way to deprecation. The mirror was
always meant to be the default; it shipped as opt-in and commented out.

This phase sits here because a PostgreSQL adapter that feeds an
opt-out mirror is a different piece of work from one that feeds the
only read path.

**WHAT THE PIPELINE IS**, verified rather than assumed: the sync reads
the source and writes BRONZE as strings, unaltered -- "the one
representation that cannot lose information it was given". SILVER
reads BRONZE, not the source, and coerces to the declared types.
Elysium reads silver.

That matches the medallion pattern exactly: bronze preserves
everything and transforms nothing, silver is where type casting
happens, and each boundary is a contract that should be explicit.

### 0.5.1 ~~Flip the default, and say what an empty mirror means~~ DONE

`read_from_mirror` defaults to TRUE. Browse distinguishes a
never-synced mirror from an empty one -- "Not synced yet", naming
run_sync -- using a signal the server already sent and only the
freshness line used.

**WHAT THE FLIP BROKE, all one cause:** 279 errors, every test
deployment failing with "unable to open database file". The read path
builds a SqlCatalog against a directory that may not exist, which was
harmless when mirror reads were opt-in. Created on demand now.

The integration fixture declares `read_from_mirror: false` EXPLICITLY:
those tests predate the mirror and assert against real silo data
without syncing. When the live path is deprecated, that line is the
list of what has to change.

### 0.5.2 ~~A `decimal` type, alongside `number`~~ BUILT, verified

**MEASURED LOSS.** `coerce()` sends `number` through `float()`, so
`'1234.56789012345678901'` becomes `1234.567890123457`. Money silently
becomes a different amount.

Bronze holds the string, so a corrected silver can be rebuilt WITHOUT
re-reading the customer's database -- which is what bronze is for. The
loss is recoverable, not permanent, and that is the only reason this
is not an emergency.

ALONGSIDE, NOT INSTEAD, following every layer we touch: Foundry has
Double and Decimal as separate base types, Iceberg has `double` and
`decimal(P,S)`, PostgreSQL has `double precision` and `numeric`. They
answer different questions -- a decimal needs a declared precision and
scale, a float does not. Floats for measurement, decimals for money.

`pyarrow.decimal128(P, S)` round-trips exactly; verified.

**AND A LINTER NOTE**, in the spirit of the `title_field` one: warn
when a field named like money -- amount, price, total, balance -- is
declared `number`. The mistake is cheap to make and expensive to find.

### 0.5.3 ~~Dates are strings, range filters wrong~~ BUILT, f9b76be

**A BUG, NOT A MISSING FEATURE.** The ontology has no date type;
`field_types.py` defers it deliberately and names the reasons
(timezone handling, parse-failure behaviour, format declaration). The
reasons are good. The consequence is not.

Dates stored as strings compare lexically. ISO-8601 sorts correctly BY
LUCK. Everything else does not, measured:

    '2026-1-5'  sorts AFTER '2026-02-03'   (unpadded month)
    '01/05/2026' sorts before '02/03/2026' (year ignored entirely)

So a `date_range` filter for "after February" returns a January row
and nobody is told.

`core/filters.py` already has a `date_range` operator restricted to
strings, with a validator -- but it validates the FILTER's bounds with
`fromisoformat`, never the STORED data. A well-formed filter still
compares against malformed values.

What a real type needs to answer, which is why it was deferred: what
timezone a naive timestamp means, what a parse failure does (drift, on
this project's own precedent), and whether a format is declared or
inferred.

**DECIDED: THREE TYPES, MIRRORING ICEBERG.**

- `date` -- no time, no zone, NEVER converted. A birthday is not an
  instant, and "converting" it is the classic bug where someone's
  birthday moves a day for users in Auckland. Arrow `date32`.
- `timestamp` -- a wall-clock reading with no zone, stored exactly as
  given. The literature calls these "local observations of time
  recorded in an unspecified time zone", and disambiguating them "a
  common data cleaning problem".
- `timestamptz` -- a true instant, stored UTC. Iceberg's spec:
  "values are stored as UTC and do not retain a source time zone".
  PostgreSQL's reason for timestamptz is the same -- it "guarantees
  that the precise moment in time is stored... in UTC", which
  "eliminates many time arithmetic problems, and ensures portability".

**A NAIVE TIMESTAMP IS NOT PROMOTED BY GUESSING.** Assuming UTC is a
guess; assuming the server's zone is worse, because it makes the same
data mean different things on two machines -- the exact coupling
storing UTC is meant to remove. A field may OPTIONALLY declare its
source zone (`timezone: "America/New_York"`) to be promoted to an
instant. Declared, never inferred.

**THE CHAIN ALREADY SUPPORTS THIS**, verified rather than assumed:

- All 22 `datetime.now()` calls in core/, api/ and scripts/ pass UTC.
  Not one naive timestamp.
- The sync's timestamp is `fromtimestamp(..., tz=UTC)`, explicit.
- `isoformat()` puts the offset on the wire: `...+00:00`.
- Bronze stringifies with `str()`, which PRESERVES the distinction:
  a date has no time, a naive timestamp has no offset, an instant
  carries one. Measured.

**AND THE SOURCES DIFFER IN A WAY THE ONTOLOGY ALREADY HANDLES.**
SQLite has no date type and returns strings for all three shapes,
indistinguishable. psycopg returns `date`, naive `datetime`, and
UTC-aware `datetime` respectively. The ontology's declaration is the
authority either way, which is what it was designed to be.

**THE UI NEEDS TWO FORMATTERS, and has neither.** `formatTimestamp`
renders RELATIVE time ("3 minutes ago"), which is timezone-independent
by construction and sidesteps conversion entirely. The moment an
absolute date is shown -- a transaction date, a contract start -- a
`date` must render as-is and a `timestamptz` must convert to the
viewer's zone. Two formatters, built when the types land, so the UI
cannot accidentally convert a birthday.

**DISPLAY CONVERSION BELONGS IN THE UI, NOT THE MIRROR.** If the
mirror converted, what is stored would depend on who is looking.

### 0.5.35 ~~Record what the SOURCE said its types were~~ BUILT, patch 258

**A GAP FOUND BY ASKING, then measured.** Coercion asks only "can this
value become the declared type?" -- never "is the source still saying
what it used to say?". So a source change that still coerces passes
silently. Three, measured:

    timestamptz -> timestamp    '...14:30:00+00:00' becomes
                                '...14:30:00'. The offset vanishes and
                                both coerce as strings. A DIFFERENT
                                KIND OF FACT, not a different value.
    numeric -> float            '10.50' becomes '10.5'. Both are valid
                                decimals; the scale changed.
    integer -> text             ' 42' still passes int(). Formatting
                                changed invisibly.

What we ARE protected against is a change that makes values
UNCOERCIBLE -- that fails loudly, silver holds, bronze keeps the
evidence. That covers most schema accidents. These three are the
remainder.

**THE PRECEDENT IS DEBEZIUM'S SCHEMA HISTORY.** It keeps "a log of
every DDL statement it has observed" and "for each change event...
records the schema version that was active when that event was
captured", so "consumers can reconstruct the exact schema for any
event by replaying the schema history".

The problem has a name and a reputation: "undetected schema drift is
one of the top causes of pipeline failures and silent data corruption
-- a column type change can cause data truncation or loss without any
error". The standard remedy is to compare "current schemas against
baselines" and alert.

**AND ELYSIUM ALREADY HAS THIS PATTERN, ON ONE SIDE ONLY.**
`config_history` exists precisely because a generation recorded WHICH
load it was and not WHAT IT SAID -- so "what did generation 7 contain"
had no answer. That is the same question, asked of our ontology.
Nothing asks it of the source.

**PER COLUMN, PER SYNC -- NOT PER VALUE.** Per-value type tags double
bronze's size to record a property of the COLUMN, and a row that
disagrees with its column is the drift already caught. Column types
belong beside `elysium.source_silo` and `elysium.source_table` in
bronze's table properties, which already exist for provenance.

**IT NEEDS AN ADAPTER METHOD THAT DOES NOT EXIST.** `columns_present`
returns names only. So this lands with the PostgreSQL work, where the
driver exposes types cleanly and a second implementation proves the
interface is not SQLite-shaped.

**SQLITE CAN ONLY ANSWER WEAKLY**, and that is honest rather than
disqualifying. `PRAGMA table_info` gives the DECLARED type, which
SQLite treats as advisory -- a column declared INTEGER can hold
'banana'. Recording "the source said INTEGER" still detects someone
altering the table, which is the case being caught.

**A NOTE ON POSTGRESQL**, from the same research: Debezium cannot get
DDL events from PostgreSQL's logical decoding at all -- "schema change
events are not separately published. Instead, any schema modifications
are only reflected as part of the data change events themselves". So
polling the catalog at sync time is not a shortcut; it is what the
established tool has to do too.

### 0.5.4 ~~A mirror administration surface~~ FIRST HALF DONE

**WE BUILT AN INTEGRITY GUARANTEE AND LEFT IT INVISIBLE.** Proven
behaviour: a value that cannot be coerced fails the whole table's
sync, silver keeps its previous snapshot untouched, and bronze accepts
the bad value anyway so it can be diagnosed. Exactly right.

The only trace is stderr on whatever ran the sync. A user sees data
three days stale and an administrator cannot find out why from inside
the product.

Admin has Users, Silos, Deployment Config and Metrics. Nothing shows
the mirror. What it should show:

- Per table: last successful sync, bronze and silver row counts. A
  divergence between those two IS the drift state.
- The last failure, with the offending column and value -- already
  computed and currently discarded.
- Snapshot history, which Iceberg records anyway, making "roll back to
  yesterday" a visible option rather than surgery.
- Sync now, so recovery does not need shell access.
- `check_mirror` and `repair_catalog` results.

**BUILT:** Admin -> Mirror. Per table: last synced, rows SERVED
(silver) and rows FETCHED (bronze), with the divergence NAMED rather
than left as two numbers to compare -- "fetched but not served, the
last sync was refused". Integrity problems from check_mirror above the
table. A live deployment says so rather than showing a blank page.

**AND THE LAST ATTEMPT, which the panel's own first run demanded.**
Snapshots record when data CHANGED, so a sync that ran and was refused
leaves exactly what a sync that ran and found nothing leaves. A table
refusing every sync since Tuesday looked identical to one whose source
had not changed since Tuesday.

`core/mirror/sync_attempts.py` records one row per table per attempt
-- synced or refused, with the full drift report on a refusal -- and
the panel shows it beside the change date, with the reason above the
table.

**STILL OPEN:** roll-back. History and Sync now are built;
rolling BACK to a snapshot is a write, and a different question.
Both need endpoints that DO something rather than report, which is a
larger security question than reading.

**THE GENERAL POINT:** operational tooling here is all scripts
requiring a terminal on the host -- check_mirror, repair_catalog,
run_sync, measure_prompts. For a commercial product that is a support
burden, and the workaround audit should have caught it. This closes
the reading half of check_mirror only.

### 0.5.5 ~~Report every drifted column at once~~ IT ALREADY DID

**THE ENTRY WAS WRONG.** It was written from reading `drift[0]` in the
raise, without checking what `describe_drift` does with the rest --
which is name every one, with the offending value and the rows
checked. Measured with three bad columns: all three reported.

What was actually wrong was smaller. The HEADLINE named one column
when several were affected, inviting someone to fix that column,
re-run, and discover the next a full read of the source later. It now
says how many others, with the verb agreeing.

**A reminder that a roadmap entry is a claim like any other.** This one
had been recorded twice and would have cost an afternoon building
something that existed.

### 0.5.6 Pin one mirror snapshot per request — OPEN QUESTION

Iceberg gives snapshot isolation and Elysium gets it free: verified
that a reader holding an old scan keeps seeing its own version while a
new reader sees the sync's result. Both served correctly, at once.

**UNVERIFIED:** whether one HTTP request pins ONE snapshot for its
whole duration. A request reading Customer then Transaction, with a
sync landing between, could see two generations of the mirror.
Elysium already pins the CONFIGURATION generation per request for
exactly this reason; the data equivalent may not be.

---

## Recorded for later: what a snapshot sync cannot recover

**CURRENT STATE IS NEVER MISSED.** Elysium is snapshot-only, so a sync
after any amount of downtime picks up whatever the source holds now.
Measured: offline while a row changed twice and two rows were added --
all three rows present afterwards.

**INTERMEDIATE STATES ARE LOST.** A row that went new -> in_progress
-> done while Elysium was away is recorded as new -> done. The
changelog records what the mirror OBSERVED, not what happened.

**AND THAT IS NOT ELYSIUM DISCARDING SOMETHING RECOVERABLE.** A normal
SQL table does not keep its own history either; `in_progress` is gone
from the source too. Retrieving it needs the source's WAL or binlog,
which is what CDC exists for -- the same conclusion the schema-drift
work reached from the other direction.

**SO "ELYSIUM IS IN SYNC" IS TRUE OF STATE AND FALSE OF HISTORY**, and
nothing says so. Worth stating before a customer assumes otherwise.

### And the measured case for snapshot has a gap in the measurement

ROADMAP.md closed incremental syncs with numbers -- 500,000 rows in
2.46 seconds, linear, ten million about a minute -- and with the
better argument that SNAPSHOT propagates deletes while APPEND cannot
see a deleted row at all.

**THOSE NUMBERS MEASURE ELYSIUM'S TIME, NOT THE SOURCE'S LOAD.** They
were taken against local SQLite. Reading 500,000 rows from a
customer's production database every five minutes is a real cost to
THEM, and nothing here has measured it.

That does not make APPEND correct. It makes the honest position:
snapshot is right, its true cost is borne by the source, and CDC is
the answer that is both incremental and delete-aware.

## Recorded for later: a diagnostic sweep

**THE PIECES EXIST AND ARE SCATTERED.** Adapter reachability is in the
Silos panel, bronze and silver in check_mirror, integrity in
check_mirror and repair_catalog, subsystem liveness in /health,
provenance in read_manifests.

**WHAT IS MISSING IS TRACING ONE ROW END TO END** -- silo, bronze,
silver, mirror, ontology -- and asserting it is the same row. That is
a different check from "each layer looks fine", and it is the one that
catches a pipeline whose layers are individually healthy and
collectively wrong.

**SHOWN AS THE PIPELINE ITSELF**, each stage lighting up as it is
checked, rather than as a list. A break between two ticks says where
to look without reading anything. The progress matters too: a sweep
that shows what it is doing is a sweep people run.

**AND THE HELP ASSISTANT CLOSES IT.** "bronze holds 7, silver holds
67" is only useful to somebody who already knows what that means.

## Recorded for later: read-through with background refresh

Not for now, and worth not losing. A read could trigger a fresh source
read so data is never stale -- but done naively it makes read latency
depend on SOURCE latency, which is the property the mirror exists to
remove. One slow source and every reader waits.

The established shape: serve the mirror immediately, trigger the
refresh in the BACKGROUND, let the next read get the newer data. Fast
reads and catch-up both.

This is where the live-read path earns its keep after deprecation as a
primary mode -- as the refresh mechanism rather than the serving one.


## Phase 1 — A deployment that survives its own operation

### 1.1 ~~Persist the pending write store~~ DONE

In-process memory, stated plainly in its own docstring. A restart
loses every approval awaiting decision.

For a product whose pitch is that writes are mediated and approved,
losing the queue on deploy is the worst fit between claim and
behaviour. ROADMAP.md establishes SQLite suffices and that the rebuild
is blocked on its DESIGN — who may see a queued write across a
restart, and what a reload does to one proposed under an older
generation — not on storage.

**THE DESIGN DECISION IS MADE.** Both questions turned out to be
answered by code that already exists.

**WHO MAY SEE A QUEUED WRITE ACROSS A RESTART:** whoever the CURRENT
grants say. Nothing about eligibility is stored. `confirm` authorises
against `_generation(request).config.roles`, and MAC and the
submission criteria are evaluated inside `confirm_and_execute()`
against the objects actually touched -- "duplicating them here would
be a second, weaker copy". Authority is re-evaluated at the point of
use, which is this project's rule everywhere else too.

**WHAT A RELOAD DOES TO ONE PROPOSED UNDER AN OLDER GENERATION:** this
is the real question, and it is about MEANING rather than authority. A
PendingWrite holds RESOLVED `sub_writes` -- the old ontology's
interpretation of what the action does. Re-authorising those under new
grants would check the new rules against the old meaning.

**AND A CHECK FOR IT ALREADY EXISTS.** `PendingWrite` carries
`proposed_under_generation`, and `confirm_and_execute()` calls
`_fields_no_longer_declared()` -- refusing a write whose target fields
the current ontology lacks, naming both generations and writing
`log_write_unapplyable`.

I began building a `source_digest` pin and backed it out: that refuses
whenever ANY configuration changed, where the existing check refuses
only when THIS WRITE can no longer be applied. Cruder, and a
duplicate.

**THE RESIDUAL GAP, narrower than first framed:** the existing check
asks whether the target FIELDS still exist. It does not ask whether
the ACTION still means what it meant -- an action whose sub-writes
were redefined leaves a stored write holding the old computation
against a field that is still perfectly present.

That is a real hole and a small one. Worth fixing when the action
definition itself can be compared, not by refusing every write that
outlived a config change.

**Depends on:** nothing. SQLite suffices, and the design is settled --
authority re-evaluated at use, meaning checked by the guard that
exists, with the narrow residual gap recorded.

### 1.2 ~~fsync before the catalog pointer swap~~ DONE

Researched. pyiceberg writes metadata through an unsynced path while
SQLite fsyncs its own commit — so the POINTER is durable and the thing
it points to is not, which is exactly backwards and precisely why a
crash strands a table rather than losing a commit.

Two fsyncs, not one: the file, then its parent directory, or the
directory entry may not survive. Cost is 1–4ms each on an SSD without
power-loss protection, which is nothing against a sync's normal
duration. Never retry a failed fsync. Consumer SSDs may acknowledge a
flush before committing to NAND, so this narrows the window rather
than closing it — worth stating in the code.

`scripts/repair_catalog.py` already makes the damage survivable.

### 1.3 ~~Backup and restore~~ DONE -- restore verified for real, patch 288

**THE INVENTORY WAS WRONG: SEVEN, NOT FIVE.** The entry named
credentials, write_log, config_history, metrics and artifacts, and
missed the mirror's own `catalog.db`; `sync_attempts.db` did not exist
when it was written. Verified against the live deployment.

`scripts/backup_deployment.py` uses `sqlite3.Connection.backup()`,
which takes a CONSISTENT snapshot of a database being written to --
`cp` tears across a write, and a torn credentials database is one
nobody can log into.

**THE SILOS ARE DELIBERATELY EXCLUDED**, and the manifest says so.
`dev_fixtures/` stands in for a CUSTOMER'S databases; backing them up
would copy data Elysium does not own into a directory the customer did
not choose.

**VERIFIED BY RESTORING:** a backup copied into a fresh directory,
pointed at the silos, built a generation and served four transactions
with its mirror timestamp intact.

**AND RESTORE IS A SCRIPT NOW**, whose value is the CHECKING rather
than the copying. Every database must open AND hold tables --
`sqlite3.connect()` succeeds on a file that is not a database at all,
failing only when something reads.

**EVERY PROBLEM IS REPORTED, NOT THE FIRST.** Somebody fixing a backup
one error at a time, with a restore between each, gives up before the
third.

**A MISSING credentials.db IS NAMED SPECIFICALLY**, because that
backup restores silently and then nobody can log in -- which looks
like a different failure entirely.

**Verified end to end:** a restored backup, pointed at the silos,
builds a generation and serves four transactions.

**THE CHANGELOG IS THE ONE THING THAT CANNOT BE REBUILT.** Bronze and
silver derive from the silos; history does not.

**Depends on:** 1.2, so that what is captured is itself consistent.

### 1.4 ~~Secret indirection in configuration~~ DONE

`data_silos.yaml` holds hosts and credentials with no `${ENV_VAR}`
expansion or secret-store reference. Anyone pointing Elysium at a real
database puts that password in a config file — and the manifest work
means it can now reach the lake.

**Depends on:** 0.1, which is when real credentials first exist.

---

## Phase 2 — Decisions already made, waiting to be built

### 2.1 Query's two buildable parts

QUERY_PLAN.md. Deployment-stated example questions, and keeping the
last question in the box so refining one clause is the default.

The deployment ALREADY states good questions, in
`example_queries.yaml`, and nothing in the web UI reads it. It needs a
display-safe subset rather than straight reuse, because its entries
are user-paired for the CLI runner.

### 2.2 The measurement session's remaining questions

Two of four answered. Aggregates ARE chosen correctly. The one-hop
failure was a wildcard field name, now refused.

Outstanding: whether the pre-flight verdicts earn their keep, and
whether a small model can work without the schema in the prompt. Both
need a re-run; neither was reached.

**AND A MODEL LARGE ENOUGH TO ANSWER THEM.** phi4-mini is ~3.8B, below
the threshold where multi-step tool use works reliably — the observed
duplicate-spiral after a rejection is the documented failure mode of
that model class, not only a prompt defect.

### 2.3 ~~json_each for the write log~~ DONE

Deferred by decision, not forgotten. Removes two `S608` suppressions,
the chunking loop and the variable limit, in exchange for a minimum
SQLite of 3.38 (2022). Verified working.

### 2.4 ~~The remaining UI halves~~ DONE, patches 289-291

Vertex-lite's second half, the view-state matrix's other half, and
which other screens show the checkbox-above-the-row problem. Each
small, each verifiable now that browser tests exist.

---

## Phase 3 — Needs research, then a plan, then building

### 3.0 ~~Triggers~~ DONE, patches 264-280

**DESIGNED, NOT BUILT** -- see TRIGGERS_AND_PLUGINS.md.

Elysium has none. Foundry's Automate is condition + effect, and the
conditions are ontology-shaped: objects added to, removed from, or
modified in a SET. A set is a saved search, and Elysium already has
saved explorations.

**THE PERMISSION SPLIT IS THE PART TO COPY EXACTLY.** Conditions
evaluate as the owner; action effects execute as the owner;
NOTIFICATION EFFECTS USE EACH RECIPIENT'S OWN PERMISSIONS. With MAC
that is not a nicety -- a notification counting matching rows must
count differently for someone who can see less.

**NOT A FLAW WE HAVE:** an earlier framing asked whether proposing
rather than executing weakens us against Foundry. `auto_execute`
already exists per action type, defaulting to confirmation, enforced
in Python. An automation uses the action's own setting.

**SAVED VIEWS ARE NOT SERVER-SIDE**, which an earlier version of this
entry got wrong. `SavedView` is `{name, url}` in a browser's
localStorage, so nothing scheduled can reference one. Moving them
server-side is the real prerequisite for object-set conditions --
which is a second reason mirror health goes first, since it needs
none.

**AND PER-RECIPIENT EVALUATION IS NOT NOVEL WORK.**
`search_object(user_record, ...)` already takes a user, so evaluating
a condition as the owner and then as each recipient is one existing
function called with a different first argument. No second permission
path to get wrong.

**THE REAL RISKS ARE VOLUME:** MAX_SUB_WRITES is 20 and the queue TTL
is 15 minutes, so an automation across a thousand objects floods or
expires. And four-eyes means an owner cannot approve their own
automation's proposal.

### 3.1 The plugin API

**DESIGNED UNDER A STRICTER PREMISE -- see
THIRD_PARTY_EXTENSIONS.md.** Every component untrusted, first-party
included. Module federation is DISQUALIFIED; a third-party adapter is
a SILO; the channel comes before the boundary.

The largest item. Research done; no plan written.

**DESIGNED -- see TRIGGERS_AND_PLUGINS.md.** The UI boundary already
exists: five sub-apps importing only from `@elysium/shell-api`, 113
imports across three modules, each lazy-loaded. The work is hardening
a boundary rather than inventing one.

**DECLARE THE CURRENT BOUNDARY THE API, THEN FIND WHERE THE SUB-APPS
CHEAT.** That list is discoverable today; building first and
converting afterwards finds the same list later and more expensively.

**A PLUGIN MUST NOT GET A PRIVATE CHANNEL TO THE AGENT.** It extends
the ONTOLOGY through existing mechanisms -- object types, actions,
functions -- so agent awareness comes free and MAC, submission
criteria, approvals and audit all keep applying.

**THE HONEST SMALL VERSION FIRST:** the adapter registry already IS a
plugin point, loading implementations by name. Formalising THAT —
versioning the contract separately from the app, a manifest declaring
which contract it needs — is much smaller than designing a new surface
and is testable against a second implementation, which 0.1 supplies.

Superset is the closest analogue and instructively modest: extensions
off by default, running in-process, sandboxing planned rather than
shipped, administrators responsible for vetting.

**Depends on:** 0.1, which produces the second adapter that proves the
abstraction is not single-use.

### 3.2 Multiple workers, and the storage question under it

**RE-CHECKED AGAINST THE CODE, patch 292.** The entry is right that
the concurrency limiter is per-process, and misleading elsewhere:

  ALREADY SHARED -- sessions, login lockout and the query rate limiter
  all live in credentials.db with atomic transactions. Pending writes
  became database-authoritative in 276.

  NOT SHARED, AND NOT IN THIS ENTRY -- the CONFIGURATION. A reload
  swapped it in the one worker that handled it, so an approved role
  change reached one worker and the rest kept enforcing the old roles,
  withdrawn grants included. FIXED in 292: a shared reload epoch every
  worker follows before its next request.

  STILL OPEN, each small:
    - ~~the role-approval lock is per process~~ FIXED, patch 293: a
      flock on data_dir/roles.lock, following run_sync.py's own lock.
      NOT the database -- BEGIN IMMEDIATE on roles.db would deadlock
      against RoleStore.save()'s own connection.
    - ~~generation numbers per process~~ FIXED, patch 294 -- and it
      was WORSE than recorded: not only a multi-worker problem. A single
      worker restarting reused 1, 2, 3, and INSERT OR IGNORE silently
      dropped the new records under numbers already taken. Numbers now
      come from a shared sequence in config_history.db.
    - ~~the concurrency cap applies per worker~~ FIXED, patch 295.
      Named caps are shared through flock slot files. Dividing by the
      worker count could not work: every declared cap defaults to 1.
      And a single worker was already wrong -- the step and synthesis
      models each held their own semaphore for one server.

  ALL FOUR BLOCKERS FIXED (292-295). --workers is safe to try; running
  it for real is the verification that remains.


UI_ROADMAP.md states it: `--workers` breaks SQLite's single-writer
assumption and the concurrency limiter's per-process state. One
uvicorn, one core, no horizontal scale, and a deploy is downtime.

The decision underneath is parallelising inside a request or across
them. Across is worth more and forces the storage question.

**Depends on:** 1.1, which is the first piece of state that has to
move anyway.

### 3.25 A help assistant, separate from Query

**DESIGNED -- see TRIGGERS_AND_PLUGINS.md part three.** A chat that
answers questions ABOUT ELYSIUM rather than about a deployment's data.

Precedent is AIP Assist, and the security property is the whole
design: Palantir state it "does not access your data". No MAC, no
submission criteria, no audit of data access, no per-recipient
evaluation.

**A DIFFERENT SUB-APP, NOT A MODE OF QUERY**, because a different
threat model one wrong branch away from leaking is not a mode.

Context without data: knowing which SCREEN a user is on, never which
object. A deployment may register its own runbooks as additional
content, as Foundry allows custom content sources.

**IT MATTERS MORE THAN IT LOOKS.** Elysium's operational surface is
scripts needing a terminal and knowledge of when to use them. An
assistant that can answer "the mirror is stale, what do I do" is the
difference between a product an administrator can run and one they
need us for.

### 3.3 Schema migrations

`CREATE TABLE IF NOT EXISTS` plus hand-written migration functions.
Fine for five tables; a liability the first time a customer holds data
across a version boundary.

---

## Phase 3.5 — ~~Non-user-derived constraints~~ DONE

**ALL FOUR PIECES.** Trace id (built earlier), the write-down check
(compartments, levels deferred following Foundry), attenuation (found
already true and pinned), and the grant algebra -- now four UNIVERSAL
tests that fail when a NEW mechanism appears rather than when an
existing one breaks.

**THREE OF THE FOUR WERE SMALLER THAN WRITTEN.** Recorded in
SECURITY_ARCHITECTURE.md in place rather than deleted.

**ASSESSED, NOT BUILT -- see SECURITY_ARCHITECTURE.md.**

**ONE REAL HOLE.** Every MAC check compares an object to the USER's
security value; nothing compares two objects to each other. So an
analyst cleared for two partitions can run an action that reads one
and writes the other, and data crosses a boundary with every check
passing.

That is Bell-LaPadula's \*-property -- no write down. Elysium enforces
its partner (no read up) and not it, and neither term appears in the
codebase: not a decision, an omission.

**BUILD ORDER:** a request-scoped trace id first (smallest, and it
makes the rest observable); then the write-down check; then
intersection for action authority; then the grant algebra, once there
is something worth specifying.

**WHAT NOT TO BUILD:** actions carrying authority their caller lacks,
which is a confused deputy. Attenuation only.

## Phase 3.6 — Fusion and identity

**DESIGNED, NOT BUILT -- see FUSION_AND_IDENTITY.md.** Elysium follows
links someone wrote down and infers none. The precedent says identity
resolution is a PIPELINE problem, which places it in the GOLD layer
Elysium does not have.

**THE PERMISSIONS FEAR DISSOLVES:** column-wise MDO already exists, so
a merged subject is one object whose FIELDS keep the classification of
their source. No write-down. What does NOT dissolve is the
classification of the identity link itself.

**HAND-WRITTEN JOINS ARE THE PRIMARY PATH**, working with zero
inference. Inference is off by default and its proposals always go
through the approvals queue -- which answers unresolution natively,
since un-merging is another write.

## ~~The pending-write store is not multi-process safe~~ FIXED, 276

**FOUND WHILE WIRING TRIGGER ACTIONS, and it blocks them.** Recorded
before anything else so it is the first thing picked up.

### The problem

`PendingWriteStore` keeps writes in a locked dict and MIRRORS them to
`pending_writes.db`. The API reads that file ONCE, at startup
(`_restore_locked`), and every read after answers from memory.

The sync runs as a SEPARATE PROCESS when cron starts it. So a trigger
firing during a cron-run sync would propose a write into
`pending_writes.db` -- and the running API would never see it until
restarted. The proposal would sit on disk, absent from Approvals.

"Sync now" is unaffected: it runs the sync on a thread INSIDE the API
process. The cron path is the one that breaks, and it is the one that
matters for anything happening while everybody is asleep.

### What precedent says, and it says my design was backwards

Every SQLite-backed queue researched states it the same way: "the
database is still the source of truth. The queue only stores candidate
job IDs", with "the claim logic checks the database before starting a
job and skips anything that is no longer pending". A queue library
explaining what multi-process support would require names it
directly: "removal of the in memory caches".

**`PendingWriteStore` INVERTS THIS.** Memory is the truth and SQLite
is a mirror, which is exactly why a second process cannot be seen.

Its concurrency was described in this project as "getting it right".
That was true of THREADS in one process. It was never multi-process
safe, and nothing said so.

### The fix

**MAKE THE DATABASE AUTHORITATIVE.** Reads come from SQLite; the dict
goes. WAL mode lets the API read while the sync writes -- readers get
snapshots that are not blocked by the writer.

**RESERVING BECOMES A DATABASE-BACKED CLAIM:** `UPDATE ... SET
reserved = 1 WHERE write_id = ? AND reserved = 0`, which either claims
the row atomically or matches nothing because somebody else did.
SQLite serialises writers, so that is safe across processes by
construction.

### What it dissolves

The obvious patch -- have `awaiting()` merge in rows another process
added -- would need a TOMBSTONE set: deciding a write removes it from
memory and then deletes the row best-effort, so a failed delete would
bring a DECIDED write back. A zombie approval somebody already acted on
is worse than a missing one.

**WITH THE DATABASE AUTHORITATIVE, THAT CANNOT HAPPEN.** Deciding
deletes the row, and there is no second copy to disagree with. The
complexity the merge needed was a symptom of the inversion, not a
property of the problem.

### Why it is a session of its own

It rewrites the store under the approvals queue, where a mistake loses
or duplicates DECISIONS. It deserves its own commit, its own controls,
and a concurrency test that runs two real processes rather than two
threads -- the test that would have caught this in the first place.

### What is parked behind it

Trigger ACTION effects, step 1 of four. Built, tested and discarded
rather than committed inert, because it called `pending_store.store()`
and that call changes with this fix. What it was, for redoing:

    triggers table   action_type, action_parameter, action_values
                     columns, added through add_column_if_missing so
                     a triggers.db from patch 271 survives -- verified
    evaluator        proposes ONLY when `told` is non-zero, so never
                     on a baseline or a suppressed repeat; as the
                     owner; never raising, so a refused proposal costs
                     one trigger its action

**ALL DONE, patches 276-280.** The store became database-authoritative
first (276), then: action effects proposed as the owner (277), role
recipients each counted as themselves with the action hanging on the
owner alone (278), triggers declared in config.yaml naming an owner
that may be a service account (279), and the Watch dialog choosing an
action and recipients (280).

TRIGGERS ARE COMPLETE: made in the product or declared in
configuration, notifying the owner and named roles, proposing actions
into Approvals -- all through one evaluator, all attenuated to the
owner.

---

## ~~A narrow race in role deletion~~ FIXED, patch 287

**THE RACE.** Account creation now takes the role-change lock, so it
waits for any approval to finish saving and reloading -- and a role
just deleted is already gone when it checks. A test holds the lock and
checks a creation WAITS; a sequential test would pass without the fix.

**AND FIXING IT FOUND A WORSE PATH, WHICH WAS NOT A RACE.** The stranded
check counted only ACTIVE holders -- the lockout check's count, reused.
So a role held only by DISABLED accounts could be deleted, and
re-enabling one stranded it. Every time, not by timing. Stranding now
counts every account; lockout still counts only active ones.

---

## What to build next, in dependency order

The phases above are grouped by SUBJECT. This is the same work grouped
by WHAT BLOCKS WHAT, which is the more useful question once several
phases are half-done.

**Rewritten September 19, after phases 0, 1 and 3.5 closed.** The
previous version had become a list of DONE markers, which is a record
rather than a plan.

### Ready now — nothing blocks these

    R3    runtime role editing   UNBLOCKED: 3.5 is done, and its
                                 question -- whether a grant edit
                                 should itself pass through the
                                 approvals queue -- is now answerable
                                 against a settled model
    2.4   ~~the remaining UI~~  DONE, patches 289-291. The view-state
          ~~halves~~             matrix reopened by my own patch 280 and
                                 closed; the checkbox checks run in a
                                 real browser (the Watch one not yet
                                 confirmed); Vertex-lite's trail, 291
    1.3   ~~restore verification~~  DONE, patch 288 -- and a real
                                 restore found that restore only ADDED
                                 and replayed leftover logs

### Ready, but each needs ONE decision from a person

    R2    the context-rot fix    MEASURED: the loop can exceed its own
                                 4096-token window at HOP FOUR. Three
                                 paths -- summarise older hops, cap
                                 what enters `gathered`, raise the
                                 window -- with different costs
    3.0   triggers               mirror health first, notification
                                 effects only, because that condition
                                 admits no action effect. Needs a
                                 DELIVERY CHANNEL, which does not
                                 exist at all
    2.1   Query's starters       DEFERRED on a leak: a starter naming
                                 an id says it exists. The shape of an
                                 answer is in QUERY_PLAN.md

### Blocked on something genuinely absent

    2.2   the measurement        A MODEL. phi4-mini is ~3.8B, and the
          session's questions    published floor for reliable
                                 multi-step tool use is 14B -- or a
                                 small model with real tool-call
                                 training (Qwen 3.5 4B scored 97.5%)
    3.0   object-set conditions  SAVED VIEWS SERVER-SIDE. They are
                                 {name, url} in a browser today, where
                                 nothing scheduled can reach them
    3.6   fusion                 THE GOLD LAYER, which nothing has
    3.2   multiple workers       closer than it was -- pending writes
                                 now persist -- but still a storage
                                 question

### Designed, unbuilt, and worth VERIFYING before building

    3.1   the plugin API         THIRD_PARTY_EXTENSIONS.md
    3.6   fusion and identity    FUSION_AND_IDENTITY.md
    3.3   schema migrations      no design yet

**THE REASON THAT LAST GROUP IS SEPARATE:** of the last several design
entries picked up and built, MOST WERE SMALLER THAN WRITTEN -- 0.3's
cache bound, 0.5.5's drift report, 3.5's ordered-vs-incomparable
question, and 3.5's intersection item. Each described a defect that
reading the code carefully ruled out.

So a design document is a claim like any other. Verify it against the
code before building from it, and expect the work to be smaller.

**THE HONEST READING:** three items are ready now, three need one
decision each, and four are blocked on something real. Nothing in the
first group depends on anything in the last.

The largest single unlock is **saved views server-side** -- it is the
prerequisite for object-set triggers, and the same machinery is what a
notification's per-recipient evaluation would run.

## Found on review, September 19 — four things no phase held

Re-read of the nineteen planning documents against this roadmap. Four
real items had no entry, and they are placed by what they depend on
rather than by how interesting they are.

### R1. ~~`search_around` is not capped~~ DONE

**THE FRONT DOOR IS SHUT AND THIS ONE IS OPEN.** Phase 0.2 capped
`search_object` and `search_object_free_text` at MAX_SEARCH_SCAN.
`search_around` -- the link traversal -- has no limit at all.

That matters because it is the exact path ROADMAP.md profiled:

    _io.open      1.21s   (200,006 calls -- audit logging)
    file close    0.71s
    SQL query     0.66s
    json encode   0.56s

**A 200,000-object traversal writes 200,006 audit lines.** Authorization
was fixed, the engine was never the problem, and what remains is the
audit trail's own volume. The entry in ROADMAP.md has "been wrong
twice, each time because a fix moved the bottleneck somewhere the
previous profile could not see" -- and phase 0.2 moved it again,
without touching this path.

**CAPPED ON THE TARGETS, NOT THE SOURCES.** Capping sources further
would answer a different question wrongly -- somebody asking about ten
customers with a hundred transactions each wants all thousand, and the
limit that matters is on what comes back.

**MEASURED BEFORE BUILDING:** an audit line costs about 11
microseconds, so a million-target traversal spends ELEVEN SECONDS
writing its own trail before any data reaches the caller.

**AND IT REPORTS**, through the same `scan_truncated` the searches
use.

### R2. ~~Context rot in the agent loop~~ MEASURED

UI_ROADMAP names it as "a risk to what already exists, not a feature":
current research describes "a model's effective recall degrading as
the token count grows, WELL BEFORE the hard context limit is reached".

**Our agent accumulates `gathered` across every step and feeds it back
each hop.** A query touching many objects degrades the ANSWER before
it errors -- "the failure mode is a worse answer, not a crash, which
is the hard kind to notice. We have never measured where that begins."

**MEASURED, on the shipped deployment with num_ctx 4096:**

    system prompt alone          ~1,138 tokens    28% of the window
    + one heavy hop              ~2,030            50%
    + four heavy hops            ~4,664           114%  OVERFLOWS
    + eight (default max_hops)   ~8,176           200%

**THE LOOP CAN EXCEED ITS OWN CONFIGURED WINDOW AT HOP FOUR**, well
before it stops on its own. `MAX_OBJECT_IDS` of 20 and `max_hops` of 8
were chosen for other reasons and do not bound this.

**A WARNING AT 80% IS BUILT**, which is AWS's published threshold for
exactly this. Past the window the server TRUNCATES rather than
failing, so the warning says that -- a note that a prompt is large
reads as a performance remark.

**STILL OPEN: what to DO about it.** Summarise older hops, cap what
enters `gathered`, or raise the window. That is a separate decision,
and it needed this measurement first -- a fix without one is a guess
about a threshold nobody had found.

### R3. ~~Runtime role editing~~ DONE, patches 281-286

**BUILT, FOLLOWING FOUNDRY.** Roles live in a store once somebody edits
one, with policy.yaml as the bootstrap (282). `manage:roles` is its own
grant, separate from manage:users (283). An edit is a PROPOSAL that
somebody else must approve, with stale, lockout and stranded-user
guards, applied by reload and undone if the reload fails (284). Inside
the approval lock it reads the NEWEST roles, because the per-request
pin was silently undoing concurrent approvals (285). Admin -> Roles
shows a change as what it adds and removes (286).

**FOUND ON THE WAY:** four databases missing from the backup (281), a
dead-vocabulary guard that checked verbs rather than grants (283), and
a schema cache keyed by path that broke two stores sharing a file (284).

(Original entry, kept for its reasoning:)


UI_ROADMAP item 13: policy.yaml becomes editable while the
application runs. The reload machinery it needs is built and has its
own plan document.

**NOT SCHEDULED HERE**, because it is a UI feature with a security
question attached -- who may edit grants, and whether a grant edit
should itself pass through the approvals queue. That question belongs
with phase 3.5's work on non-user-derived constraints rather than
before it.

### R4. ~~A restore script~~ DONE

The backup exists; restore is `cp -a`. Honest for a stopped
deployment, and it leaves the inventory unchecked: the backup NAMES
what was absent, and nothing verifies a restore is complete before
somebody depends on it.

Small, and the natural completion of 1.3.

---

## Deliberately not doing

Recorded so each is a decision rather than an omission.

**Clarifying questions before answering** — an extra model call per
question, on a system where the model is already the slow part, for a
problem nobody has reported.

**A conversation thread in Query** — Elysium answers questions about
an ontology; the trace beats a transcript, and threading makes "which
generation answered this" much harder to state.

**Roving focus** — results are cards with links, not a grid. Adopting
`role="grid"` without the full keyboard contract would be worse than
the native semantics it replaces.

**Multi-tenancy** — single-tenant by construction, stated in the code.
A business-model decision rather than a defect, but it means one
deployment per customer and that shapes pricing.

---

## Waiting on a trigger, with the trigger named

Sync memory batching (a table too big to hold). The changelog's later
phases (a current view reading through it). Partitioning (a few
hundred megabytes of Parquet). Snapshot expiry (a warehouse whose
history costs more than it is worth).

None of these triggers is met, and building ahead of them would be
guessing at a shape the data has not yet taken.

---

## What the ordering says

Phase 0 is four items, none of them interesting, all of them blocking.
Elysium's ontology, security model, approvals, audit and lake work are
substantially ahead of its ability to read anything a customer owns.

Phase 0.5 is the other half of the same gap. The mirror is the right
architecture, it is built, it is PROVEN correct on the two properties
that matter -- an unsafe value cannot reach a reader, and a sync
cannot disturb one in progress -- and it ships turned off with no way
to see it working.

**THE PATTERN ACROSS BOTH:** what Elysium reasons about is ahead of
what it can reach and what it can show. The ontology, the approvals,
the audit trail and the lake are the hard parts and they are largely
done. Connecting to a database, bounding a query, typing a date, and
letting an administrator see any of it are the ordinary parts, and
they are where the work is.

That gap is the roadmap.
