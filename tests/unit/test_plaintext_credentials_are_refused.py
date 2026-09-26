"""A literal credential is refused at load, not copied into the lake
(SEC-05).

THE COMPOSITION THIS CLOSES HALF OF. `core/mirror/manifest.py` lists
`data_silos.yaml` in PUBLISHABLE and copies file CONTENTS into the
lake, with nothing redacting on the way. Its own comment four lines
below that list states the rule: "credentials.db, secrets/ -- a lake
reader must never become a credential reader, and the whole point of a
lake is that many things read it." Excluding credentials.db is careful
and right; including data_silos.yaml reopens the same door, because
that file is exactly where a database URL with an inline password
lives. And a lake Elysium did not create may be world-readable --
run_sync prints that at every sync.

REPRODUCED before fixing:

    expand_secrets({'url': 'postgresql+psycopg://u:hunter2@h/db'})
    -> {'url': 'postgresql+psycopg://u:hunter2@h/db'}

`${VAR}` support existed and was opt-in. Nothing made anyone use it.

WHY BEFORE SUBSTITUTION, and it is the whole reason this is a separate
pass rather than a check on the result: after expansion a correctly
written `${DB_PW}` config ALSO contains a real password, and the two
are indistinguishable. Only the raw value can tell them apart. The
control for that is below and it is the one that matters.

THE OTHER HALF IS BACKEND'S -- redacting on publish in manifest.py, so
the allow-list stops depending on the file being clean. They fail
differently: this stops the credential existing in the file, theirs
stops it leaving if it does anyway.
"""

import pytest

from core.secret_references import MissingSecret, PlaintextSecret, expand_secrets


class TestWhatIsRefused:
    def test_a_url_with_an_inline_password(self):
        with pytest.raises(PlaintextSecret):
            expand_secrets({"url": "postgresql+psycopg://elysium:hunter2@db/warehouse"})

    def test_a_key_named_for_a_secret_holding_a_literal(self):
        with pytest.raises(PlaintextSecret):
            expand_secrets({"password": "hunter2"})

    def test_it_is_refused_wherever_it_is_nested(self):
        """A connection block is a dict and nothing guarantees the
        credential sits at the top level -- the same reason
        expand_secrets recurses at all."""
        with pytest.raises(PlaintextSecret):
            expand_secrets({"data_silos": {"warehouse": {"connection": {
                "url": "postgresql://u:hunter2@h/db"}}}})

    def test_the_refusal_names_where_and_what_to_do(self):
        """A refusal nobody can act on becomes a support ticket. This
        follows MissingSecret's own reasoning: refusing at load names
        the variable, where substituting an empty string produces an
        error naming the database instead."""
        with pytest.raises(PlaintextSecret) as raised:
            expand_secrets({"url": "postgresql://elysium:hunter2@db/warehouse"},
                           where="data_silos.yaml: warehouse.connection")

        message = str(raised.value)
        assert "data_silos.yaml: warehouse.connection" in message
        assert "${ELYSIUM_DB_PASSWORD}" in message
        assert "hunter2" not in message, "the refusal must not repeat the secret"


class TestWhatMustStillLoad:
    """THE OPPOSITE DIRECTION, and it is most of the surface. A check
    that refused everything would stop every deployment starting."""

    def test_a_reference_is_the_whole_point(self, monkeypatch):
        monkeypatch.setenv("DB_PW", "from-env")

        expanded = expand_secrets({"url": "postgresql://elysium:${DB_PW}@db/warehouse"})

        assert expanded == {"url": "postgresql://elysium:from-env@db/warehouse"}

    def test_a_secret_key_by_reference(self, monkeypatch):
        monkeypatch.setenv("DB_PW", "from-env")

        assert expand_secrets({"password": "${DB_PW}"}) == {"password": "from-env"}

    def test_a_url_with_no_password(self):
        expand_secrets({"url": "postgresql+psycopg://db.internal/warehouse"})

    def test_a_url_with_a_username_and_no_password(self):
        expand_secrets({"url": "postgresql://elysium@db.internal/warehouse"})

    def test_a_sqlite_path(self):
        """What every shipped deployment actually declares."""
        assert expand_secrets({"path": "dev_fixtures/mediator.db"}) == {
            "path": "dev_fixtures/mediator.db"}

    def test_a_non_string_is_untouched(self):
        """A port is an int and must stay one."""
        assert expand_secrets({"port": 5432, "pool": [1, 2]}) == {"port": 5432, "pool": [1, 2]}

    def test_an_empty_secret_key_is_not_a_credential(self):
        assert expand_secrets({"password": ""}) == {"password": ""}

    def test_an_ordinary_field_holding_a_password_like_string(self):
        """NOT A GENERAL SECRET SCANNER. A high-entropy string in a
        field named `note` is somebody else's problem, and guessing at
        it would fail loads for no reason."""
        expand_secrets({"note": "hunter2"})


class TestTheOrderIsThePoint:
    def test_a_missing_variable_still_raises_its_own_error(self):
        """The new check must not swallow MissingSecret. A reference to
        an unset variable is a different failure with a different
        remedy, and its message names the variable."""
        with pytest.raises(MissingSecret):
            expand_secrets({"url": "postgresql://u:${NOT_SET_ANYWHERE}@h/db"})

    def test_an_expanded_value_is_not_re_examined(self, monkeypatch):
        """THE CONTROL THAT MATTERS, as a test. If the check ran AFTER
        substitution it would refuse this -- the expanded URL carries a
        real password and is byte-identical to the literal form that is
        correctly refused. A correctly-configured deployment would fail
        to start."""
        monkeypatch.setenv("DB_PW", "hunter2")

        expanded = expand_secrets({"url": "postgresql://elysium:${DB_PW}@db/warehouse"})

        assert expanded == {"url": "postgresql://elysium:hunter2@db/warehouse"}
