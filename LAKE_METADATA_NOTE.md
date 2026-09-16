# What belongs in the lake — a design note

**The question**: tear Elysium down, preserve the lake, stand a fresh
one up. What must the lake contain for that to work, and specifically:
should the ontology, the policy and the silo definitions live in it?

**The short answer**: a COPY, yes. Their HOME, no. And I said the
opposite earlier, which this note corrects.

---

## What I got wrong

In BACKLOG.md I reasoned from the control-plane argument — "the
catalog must be the control plane where security and data quality
rules are defined and enforced. Access control policies should be
linked directly to tables, views, or columns within the catalog
itself" — and concluded the ontology, policy and silos *belong* in the
lake.

That over-read it. **A catalog's control plane governs TABLES**:
schemas, locations, snapshots, partition specs, column-level access.
Our ontology is a different kind of artifact. It says a Customer is a
thing, that `region` secures it, that `transactions` links to another
type. That is a SEMANTIC MODEL, and semantic models have their own
strong precedent that points elsewhere.

## Where semantic models actually live

The industry has converged, and it converged on version control.

dbt: metrics "live in YAML files in your dbt project,
version-controlled in Git alongside your transformation SQL", and the
reason given is governance rather than convenience — "when a metric
definition changes, it goes through version control. You can see
exactly what changed, who approved it, and what downstream queries
will be affected before anything goes to production."

Cube: "cubes are defined in JavaScript or YAML, version-controlled
alongside application code, and deployed through continuous
integration pipelines."

The framing worth keeping: **"a model is the artifact that describes
meaning, a layer is the runtime that operationalizes and serves it"**.
Our `ontology_schema.yaml` is a model. Elysium is the layer.

So the ontology's home is a reviewed, versioned, diffable artifact —
which is what it already is.

## But this project already found the limit of that

`core/config_history.py` says it plainly, and its reasoning is better
than the one I reached for:

> **NOT SOLVED BY GIT**, and assuming otherwise was a real error in
> the reasoning behind HOT_RELOAD_PLAN.md. This project's own
> configuration happens to live in a repository; a DEPLOYED Elysium
> has /etc/elysium on an operator's machine and no relationship to any
> repository. "Configuration is files, therefore versionable" is true.
> "Therefore versioned" does not follow.

That is the whole tension. **Git is where the ontology should be
authored and reviewed. It is not where a deployed Elysium can be
relied upon to find it.**

And the same file rejects the other extreme:

> **NOT SOLVED BY ICEBERG EITHER**, which is the right tool for
> versioning DATA and the wrong one for four small YAML documents.

## The shape this points at

Three roles, not two, and conflating any pair of them is what made
this confusing:

**AUTHORED in version control.** The ontology, policy and silos are
edited, reviewed and rolled back like code, wherever the operator
keeps them. Elysium does not own this and should not try to.

**LOADED from `/etc/elysium`.** What the running system reads. Already
true, already digested per generation, already recorded in
config_history.

**PUBLISHED alongside the data, as a copy.** This is the missing
piece. When a sync writes to the lake, it also writes the
configuration that produced it — so a preserved lake is
SELF-DESCRIBING, and a fresh Elysium can say what it found rather
than only that it found something.

The published copy is not the source of truth. It is a **record of
what was true when these tables were written**, which is exactly the
same thing bronze is for the rows.

## Why "a copy" is the right word

The failure mode of putting configuration IN the lake as its home is
that two systems then own it and can disagree. The failure mode of
leaving it out entirely is the one the teardown test demonstrates: a
bucket of rows nobody can interpret.

A published copy avoids both. It is:

- **derivable** — it came from /etc/elysium, so nothing is lost if it
  is deleted
- **authoritative about the past** — it says what the ontology was
  when these snapshots were taken, which /etc/elysium cannot say
- **inert** — nothing reads it in normal operation, so it cannot
  drift into being a second source of truth

That is the bronze pattern applied to configuration, and the parallel
is exact: bronze does not replace the silo, it records what the silo
said at a moment.

## Precedent for the mechanism

Researched separately from the "should it be there at all" question,
because they have different answers.

**MICROSOFT'S COMMON DATA MODEL IS ALMOST A DESCRIPTION OF THE
REQUIREMENT.** It defines "self-describing data in an Azure Data Lake"
with a manifest alongside the data, and states the goal in the terms
this note has been groping toward: **"the format of a shared folder
helps each consumer avoid having to 'relearn' the meaning of the data
in the lake."**

That is exactly a fresh Elysium on a preserved bucket. The precedent
is a MANIFEST IN THE STORAGE, not an entry in a catalog.

**THE SIDECAR CONVENTION** is the general form: "a simple, universal
convention for keeping metadata and assets alongside a primary
document", for "metadata that can't easily be stored in a document
itself, due to size or because it is updated more often". Our
configuration is both.

**AND THE CATALOG-NATIVE OPTION EXISTS TOO.** pyiceberg's
`create_namespace` takes arbitrary properties, so the ontology could
live there. Checked rather than assumed.

## Which of the two, and why

**A manifest in storage, not namespace properties.** Three reasons,
in order of weight:

**IT SURVIVES CATALOG LOSS.** The catalog is a SQLite file, and losing
it is the failure `scripts/check_mirror` exists to warn about. A
manifest in the bucket is readable when the catalog is gone -- and
that is precisely the moment someone most needs to know what the
tables were. Namespace properties die with the catalog they live in.

**IT IS READABLE WITHOUT PYICEBERG.** A manifest is a file in a
bucket; an operator with `aws s3 cp` can read it during an incident.
Namespace properties require a working catalog connection and a
library, which is a lot of preconditions for "what is this data".

**IT MATCHES WHAT BRONZE ALREADY DOES.** Provenance is stamped on
tables as properties because it describes ONE table. Configuration
describes the WHOLE deployment, so it belongs at the deployment's
level -- the bucket -- rather than repeated per namespace.

The counter-argument, stated fairly: namespace properties are atomic
with catalog operations, and a manifest can drift from the tables it
describes. That is real, and the answer is that the manifest records
WHAT WAS TRUE AT A SYNC rather than claiming to be current -- the same
guarantee bronze gives, with the same honest limit.

## What it would mean concretely

Not designed here, deliberately — this note is about the shape. But
the obvious questions to answer next:

- **Where.** A reserved namespace in the catalog, or a table whose
  rows are configuration generations, or files beside the warehouse?
  The first two travel with the catalog; the third does not.
- **When.** Every sync writes an identical copy, which is waste; only
  on change needs a comparison, which config_history already does by
  digest.
- **Secrets stay out, absolutely.** `credentials.db` and `secrets/`
  must never be published. A lake reader would become a credential
  reader, and the whole point of the lake is that many things read it.
- **What a fresh Elysium does with it.** Read-only bootstrap
  suggestion, or something it will refuse to start without? The first
  is safer and probably right; the second turns a corrupt copy into an
  outage.

## The four open questions, now answerable

**WHERE.** A manifest object in the warehouse root -- reasoning above.
Something like `_elysium/manifest-<generation>.json`, one per
configuration generation rather than one overwritten file, because
"what was the ontology when this snapshot was written" is the question
it exists to answer and a single current file cannot answer it.

**WHEN.** On configuration change, not on every sync. config_history
already detects that by digest and already stores the content, so the
work is publishing what it holds rather than computing anything new.
A sync that changed no configuration writes no manifest.

**WHAT A FRESH ELYSIUM DOES WITH IT.** Reads it and REPORTS, never
loads it silently. `scripts/check_mirror` is the natural home: a lake
whose manifest describes types the running ontology does not have is
exactly the mismatch someone needs told about, and refusing to start
over it would turn a stale copy into an outage.

The stronger version -- bootstrapping a new deployment FROM the
manifest -- is tempting and should wait. A copy that can become a
source of truth is a copy that can disagree with one, and the whole
reason this is a copy is to avoid that.

**SECRETS.** Never published, and better than a rule: publish an
explicit ALLOW-LIST of files rather than an exclusion list. An
exclusion list fails open the day someone adds a file, and the file
they add will be the one with the credentials in it.

## What this does NOT change

Object storage already makes the lake portable — proved by deleting an
installation and reading its data from elsewhere. That is the harder
half of the teardown requirement and it is done.

This note is about the softer half: a portable lake that can also
explain itself.
