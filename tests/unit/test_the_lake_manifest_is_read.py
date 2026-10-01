"""
Something reads the lake's manifest (the lake-metadata design note, "what a
fresh Elysium does with it").

MANIFESTS HAVE BEEN WRITTEN SINCE PATCH 427 AND NOTHING EVER READ ONE.
That is the sixth time in this codebase: a record nothing reads
(NEW-7), an adapter nothing constructs (AL-R1), an atomic method the
route ignored (F-05), retention properties nothing acted on (477), a
repair tool the failure never mentioned (475), and now this.

THE NOTE HAD ALREADY ANSWERED IT, before there was a reader:

    "Reads it and REPORTS, never loads it silently.
    `scripts/check_mirror` is the natural home: a lake whose manifest
    describes types the running ontology does not have is exactly the
    mismatch someone needs told about, and refusing to start over it
    would turn a stale copy into an outage."

The reader, its home, and why it must report rather than refuse were
all written down. Only the code was missing.

IT REPORTS AND NEVER REFUSES, which is the whole design: a preserved
lake inspected before a new Elysium is configured on it SHOULD say
what it was, and turning that into a startup failure would make a
stale copy an outage.

BY HIGHEST GENERATION, not by modification time: manifests are named
`manifest-<generation>.json` and a restored lake can carry any
timestamps at all.
"""

import json

import pytest

from core.mirror.manifest import describes_a_different_deployment


class TestWhatIsReported:
    def test_a_manifest_naming_tables_the_catalog_lacks(self):
        """THE CASE THIS EXISTS FOR: a lake preserved through a
        teardown, inspected before anything is configured on it."""
        manifest = {"generation": 3,
                     "tables": ["p.customers", "p.accounts", "gold.Account"]}

        problem = describes_a_different_deployment(manifest, {"p.customers"})

        assert problem is not None
        assert "2 table(s)" in problem

    def test_the_message_names_the_generation(self):
        """Which configuration wrote this lake is the question the
        manifest exists to answer."""
        manifest = {"generation": 7, "tables": ["p.gone"]}

        assert "generation 7" in describes_a_different_deployment(manifest, set())

    def test_it_shows_a_few_names_not_all_of_them(self):
        """A manifest can describe a large ontology. The count is the
        finding; the examples are for recognising it."""
        manifest = {"generation": 1,
                     "tables": [f"p.t{n}" for n in range(40)]}

        problem = describes_a_different_deployment(manifest, set())

        assert "40 table(s)" in problem
        assert problem.count("p.t") == 5


class TestWhatIsQuiet:
    def test_a_manifest_that_matches(self):
        manifest = {"generation": 1, "tables": ["p.customers", "gold.Customer"]}

        assert describes_a_different_deployment(
            manifest, {"p.customers", "gold.Customer"}) is None

    def test_a_catalog_holding_MORE_than_the_manifest(self):
        """A table added since the manifest was written is ordinary --
        manifests are per configuration generation, not per sync."""
        manifest = {"generation": 1, "tables": ["p.customers"]}

        assert describes_a_different_deployment(
            manifest, {"p.customers", "p.added_later"}) is None

    def test_a_manifest_with_no_tables_key(self):
        """Written by a version that did not record them. Not a
        mismatch, just nothing to compare."""
        assert describes_a_different_deployment({"generation": 1}, set()) is None


class TestItNeverRefuses:
    def test_it_returns_a_sentence_rather_than_raising(self):
        """'Refusing to start over it would turn a stale copy into an
        outage' -- the note's reasoning, and why this is a string."""
        problem = describes_a_different_deployment(
            {"generation": 1, "tables": ["p.gone"]}, set())

        assert isinstance(problem, str)

    def test_check_mirror_calls_it(self):
        """THE REGRESSION TEST. The manifest was written for patches
        and read by nothing."""
        from pathlib import Path

        source = Path("core/mirror/integrity.py").read_text()

        assert "_check_the_lake_manifest(" in source
        assert "describes_a_different_deployment" in source

    def test_it_compares_against_every_catalogued_table(self):
        """Passing `silver | bronze` reported both gold tables as
        missing on a healthy lake -- the same mistake patch 476 fixed
        in the warehouse check, made again four patches later.

        AND IT IS LISTED LAZILY, inside the function and only once a
        manifest exists: computing it up front ran `list_namespaces`
        on every check and broke three tests whose stub catalog has no
        such method."""
        from pathlib import Path

        source = Path("core/mirror/integrity.py").read_text()
        body = source[source.index("def _check_the_lake_manifest("):]
        body = body[:body.index("\ndef ", 10)]

        assert "_every_catalogued_table(catalog)" in body
        assert body.index("latest_published") < body.index(
            "_every_catalogued_table")


class TestFindingTheNewestManifest:
    @pytest.mark.parametrize("names,expected", [
        (["manifest-1.json", "manifest-2.json"], 2),
        (["manifest-9.json", "manifest-10.json"], 10),
        (["manifest-3.json"], 3),
    ])
    def test_by_generation_not_by_name_or_time(self, tmp_path, names, expected):
        """`manifest-10` sorts before `manifest-9` as a string, and a
        restored lake can carry any timestamps at all."""
        from core.mirror.manifest import MANIFEST_PREFIX

        directory = tmp_path / MANIFEST_PREFIX
        directory.mkdir()
        for name in names:
            generation = int(name.split("-")[1].split(".")[0])
            (directory / name).write_text(json.dumps({"generation": generation}))

        found = max(
            int(p.name.split("-")[1].split(".")[0])
            for p in directory.glob("manifest-*.json"))

        assert found == expected
