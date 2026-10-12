"""Previewing an ontology change against the real sources (R20).

The candidate is the shipped configuration with one property added and
one standardisation changed; the preview must report exactly those, and
the live mirror must be byte-for-byte what it was.
"""

import contextlib
import hashlib
import io
import shutil

from scripts.preview_ontology import run


def _fingerprint(directory) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _candidate(synced_deployment, tmp_path, edit):
    candidate = tmp_path / "candidate"
    shutil.copytree(synced_deployment.config_dir, candidate)
    ontology = candidate / "ontology_schema.yaml"
    ontology.write_text(edit(ontology.read_text()))
    return candidate


def _preview(paths, candidate) -> tuple[int, str]:
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = run(candidate, paths)
    return code, printed.getvalue()


def test_a_change_to_values_is_reported_and_nothing_live_changes(synced_deployment, tmp_path):
    """A declared sentinel: "USD" now means "no currency". Every
    transaction's currency would become empty, and the preview says so
    before a reader sees it."""
    candidate = _candidate(synced_deployment, tmp_path, lambda text: text.replace(
        "      currency:\n        type: data\n",
        "      currency:\n        type: data\n        standardise:\n          null_if: [USD]\n", 1))
    before = _fingerprint(synced_deployment.data_dir / "mirror")

    code, report = _preview(synced_deployment, candidate)

    assert code == 0, report
    assert "~ Transaction" in report
    import re
    assert re.search(r"currency: [1-9][0-9]* value\(s\) would change", report), report
    assert "= Customer: unchanged" in report
    assert _fingerprint(synced_deployment.data_dir / "mirror") == before


def test_an_unchanged_candidate_changes_nothing(synced_deployment, tmp_path):
    """THE CONTROL: the shipped configuration previewed against itself."""
    candidate = _candidate(synced_deployment, tmp_path, lambda text: text)

    code, report = _preview(synced_deployment, candidate)

    assert code == 0, report
    assert "= Customer: unchanged" in report and "= Transaction: unchanged" in report


def test_a_candidate_that_does_not_load_is_refused(synced_deployment, tmp_path):
    candidate = _candidate(synced_deployment, tmp_path, lambda text: text + "\n  : : :\n")

    code, report = _preview(synced_deployment, candidate)

    assert code == 1 and "does not load" in report
