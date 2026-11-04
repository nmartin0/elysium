"""qa_batches groups today's hits by directory under the limits."""

from collections import Counter

import qa_batches


def test_a_batch_holds_one_directory_and_stays_under_the_limit():
    hits = Counter({"src/a/one.py": 9, "src/a/two.py": 8, "src/a/three.py": 3, "src/b/four.py": 2})

    listed = qa_batches.batches(hits, 15)

    assert listed == [
        ("src/a", 12, ["src/a/one.py", "src/a/three.py"]),
        ("src/a", 8, ["src/a/two.py"]),
        ("src/b", 2, ["src/b/four.py"]),
    ]
    for directory, _, files in listed:
        assert all(f.rsplit("/", 1)[0] == directory for f in files)


def test_a_file_over_the_limit_is_a_batch_of_its_own():
    listed = qa_batches.batches(Counter({"x/big.py": 40, "x/small.py": 1}), 15)

    assert [(t, f) for _, t, f in listed] == [(40, ["x/big.py"]), (1, ["x/small.py"])]


def test_every_file_is_in_exactly_one_batch():
    hits = Counter({f"d{n % 3}/f{n}.py": n % 7 + 1 for n in range(40)})

    files = [f for _, _, fs in qa_batches.batches(hits, 15) for f in fs]

    assert sorted(files) == sorted(hits)


def test_the_real_lists_respect_the_limits(capsys):
    for kind, limit in qa_batches.LIMITS.items():
        for _, total, files in qa_batches.batches(
                qa_batches.err_hits() if kind == "err" else qa_batches.comment_hits(), limit):
            assert total <= limit or len(files) == 1, (kind, files)


def test_listing_and_selecting_a_batch(capsys):
    assert qa_batches.main(["err"]) == 0
    first = capsys.readouterr().out.splitlines()[0].split("\t")
    assert first[0] == "1"

    assert qa_batches.main(["err", "--batch", "1"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == int(first[3])


def test_an_unknown_batch_exits_1(capsys):
    assert qa_batches.main(["comments", "--batch", "99999"]) == 1
    assert "no batch" in capsys.readouterr().err


def test_check_fails_while_hits_are_left(monkeypatch, capsys):
    monkeypatch.setattr(qa_batches, "remaining", lambda kind, files: 3)

    assert qa_batches.main(["err", "--batch", "1", "--check"]) == 1
    assert "3 hit(s) left" in capsys.readouterr().err


def test_check_passes_when_the_batch_is_clean(monkeypatch, capsys):
    monkeypatch.setattr(qa_batches, "remaining", lambda kind, files: 0)

    assert qa_batches.main(["comments", "--batch", "1", "--check"]) == 0
