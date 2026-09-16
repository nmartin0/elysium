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

## What this does NOT change

Object storage already makes the lake portable — proved by deleting an
installation and reading its data from elsewhere. That is the harder
half of the teardown requirement and it is done.

This note is about the softer half: a portable lake that can also
explain itself.
