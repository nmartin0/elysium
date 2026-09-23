# Open risks the gold layer created

Raised and researched September 22, after GOLD-1 and GOLD-2 shipped.
None of these is a bug in what was built. Each is a consequence of it
that has no owner yet, which is how consequences become incidents.

---

## 1. Quarantine is invisible, and invisible absence reads as loss

THE STATE TODAY: a declared `quarantine` rule holds rows back from
silver and writes a finding to quarantine_<silo>.<table>. The row stays
in bronze; nothing is lost. But the only traces are a log line at
warning level and a table nobody opens. `/api/health` does not mention
it, the mirror panel does not show it, and a SyncResult carries the
count only as far as run_sync's stdout.

WHY IT MATTERS BEFORE ANYONE USES IT: no field declares a rule yet, so
nothing is being held back. The moment somebody declares one, objects
start disappearing from the UI with no explanation on screen. An
operator's first hypothesis will be data loss, and they will be right
that something is missing and wrong about why -- which is the worst
combination for trust in a system that holds the customer's data.

THE WORK, small and worth doing first: quarantine counts on
/api/health, on the mirror panel, and beside the affected object type
in Browse, each linking to the rule that caught the rows.

---

## 2. Gold is a tidy, joined, business-shaped copy of everything

THE STATE TODAY: gold holds one table per object type, keyed by object
id, conformed, deduplicated, with lineage attached. The ontology
applies MAC on read -- but that is a property of the READ PATH, not of
the files.

THE PRECEDENT IS BLUNT ABOUT THIS. Iceberg's own design puts security
at the catalog and engine layer, not the file format: it "does not
control which users can read which rows, and it cannot mask column
values based on user identity", and if a process can read the Parquet
directly, "that engine reads all rows and all columns". Foundry
documents the same limit from the other side -- Iceberg tables cannot
directly back restricted views, and the supported route is object and
property security in the Ontology, or a separate dataset.

WHAT CHANGED WITH GOLD, and it is a real change rather than a
restatement: the mirror used to be a scattered copy of source tables
with source column names. Gold is the business picture, joined and
keyed, which is precisely the artefact worth stealing. The same bytes
became more valuable without anybody deciding that they should.

THE OPTIONS, in the order they cost:
  a. FILE PERMISSIONS AND A DOCUMENTED TRUST BOUNDARY: say plainly
     that read access to the warehouse directory IS read access to
     everything, and that the directory is therefore part of the
     deployment's security perimeter, not a cache. Cheap, honest, and
     it makes the risk somebody's decision.
  b. ENCRYPTION AT REST at the volume or bucket level: protects the
     stolen-disk case, not the logged-in-process case.
  c. ICEBERG TABLE ENCRYPTION (1.11+, envelope encryption with the
     catalog as key broker, column-level keys possible): the only
     option that survives a compromised store, and it requires a KMS
     and a catalog that brokers keys. Heavy for an on-prem deployment
     and not something to adopt without a reason.

MY READ: (a) now, written into INSTALL.md where an operator plans the
deployment, and (c) recorded as available if a customer's threat model
demands it. The dangerous outcome is not choosing (a) -- it is
assuming (a) is already true without saying so.

AND THE PRECEDENT'S OWN TEST IS WORTH COPYING: verify enforcement with
a low-privilege identity rather than assuming it, and keep the result
as evidence. Elysium has the machinery for exactly this test.

---

## 3. Nothing expires a gold snapshot, and tags never expire by default

THE STATE TODAY: every publication tags a snapshot. Tags protect their
snapshots from expiry -- which is deliberate, and is what keeps a
pinned reader safe (D3's second half). Nothing prunes them.

THE FAILURE MODE HAS A NAME IN THE PRECEDENT: "a tag somebody created
during an incident two years ago and forgot ... quietly pins a
snapshot and every file that snapshot uniquely references." Iceberg's
answer is `history.expire.max-ref-age-ms`, which ages non-main refs
out on their own schedule -- and PyIceberg DOES NOT ENFORCE IT: a
pull request opened in August 2026 notes that create_tag accepts
max_ref_age_ms and writes it to metadata, but "nothing in pyiceberg
acts on it", so a stale ref pins its snapshot indefinitely.

SO WE CANNOT INHERIT THE FIX; we have to run retention ourselves.

THE SHAPE OF THE ANSWER: publications are not equal. Keep the last N
publications per type plus any snapshot a live generation is pinned
to, and drop the rest -- the same rule the roadmap already states for
expiry, now with a mechanism. Two constraints from the precedent: keep
at least two snapshots and make the window longer than the longest
query, because "a long query planned before expiry can fail if it
reaches for a file that has since been deleted"; and remember that
expiry unreferences while ORPHAN CLEANUP is what actually reclaims
bytes.

---

## 4. The security comparison is the one genuinely dangerous line in
   GOLD-3

TODAY it reads: same adapter, and `security_config["storage"] !=
searched_config["storage"]` returns None -- "same silo AND same table",
because a column name means nothing outside one table.

ON GOLD every type is one table in one namespace, so that comparison
stops distinguishing anything. Left as written it does not fail
loudly.

CORRECTED, September 23, BY THE CONTROL FOR ITS OWN TESTS
(tests/unit/test_security_pushdown_guard.py). This entry first said
the failure was a silent WIDENING. It is not. check_access() runs per
candidate id unconditionally after the read, so MAC is enforced
whatever the pushdown does; the pushdown exists so the database
returns only permitted rows, which is what makes a LIMIT correct
rather than a guess.

So a lost guard pushes a column name into a table that may hold a
different column of the same name, and the query silently DROPS rows
the user is entitled to. A silent DENIAL, not a silent grant --
measured: with the guard removed, a us-east user searching by a
support field got [] instead of their own customer.

Still a real fault, and harder to notice than an exception, because
NOBODY REPORTS THE ROWS THEY NEVER SAW. But the direction matters for
how it is tested and how urgently it is treated.

HOW TO DO IT SAFELY, and in this order:
  1. Write the tests FIRST, against the current source-shaped code,
     pinning what is refused today: a chain across two storages, a
     chain across two silos, a field whose name collides between
     types.
  2. Re-key the comparison to "same object type".
  3. Run the same tests against gold and confirm the same refusals,
     for the same reasons.
  4. And a CONTROL: remove the comparison entirely and confirm the
     tests fail. A security test that passes when the check is gone is
     not a test.

This one wants a second pair of eyes before it merges.
