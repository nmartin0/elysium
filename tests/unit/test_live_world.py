"""scripts/live_world.py, the harness that runs Elysium over a simulated
world (BLOCKING.md, "Make the simulator's sources behave like real ones,
then run Elysium over it", step 3).

A HARNESS THAT CANNOT FAIL PROVES NOTHING, so its judging parts are
pinned here without a world: how it reads a pack, what deployment it
writes, how it spells values, and that a wrong row, a changed "last good"
copy and an oracle that disagrees are each reported. Running it against
real servers is by hand -- `python -m scripts.live_world --help` -- as a
user that is not root, because PostgreSQL refuses root.
"""

from decimal import Decimal
from pathlib import Path

import yaml

from scripts import live_world as live

FIELD_SERVICE = Path(__file__).resolve().parents[2] / "sim" / "packs" / "field_service.yaml"


def _spec():
    return yaml.safe_load(FIELD_SERVICE.read_text())


class TestWhatItReadsFromAPack:
    def test_every_kind_of_table_is_found(self):
        found = {(t.silo, t.name): t for t in live.tables_of(_spec())}

        assert ("dispatch", "invoices") in found
        assert ("office", "invoices") in found, "a replica's tables are its source's"
        assert found[("books", "invoices")].collection == "invoices"
        assert found[("payroll", "pay_lines")].files == "pay_lines_*.csv"
        assert found[("dispatch", "invoices")].id_column == "invoice_id"
        assert set(found[("books", "invoices")].columns) == {
            "invoice_id", "work_order_id", "total", "issued_at", "paid"}

    def test_realism_is_switched_on_per_kind(self, tmp_path):
        out = live.overlay(FIELD_SERVICE, tmp_path / "p.yaml", True,
                           {"filedrop": {"zipped": True}})
        silos = yaml.safe_load(out.read_text())["silos"]

        assert silos["books"]["options"]["page_size"] == 25, "the pack's own options stay"
        assert silos["books"]["options"]["token_lifetime_seconds"] == 1800
        assert silos["payroll"]["options"]["zipped"] is True


class TestWhatItAddsToAPack:
    def test_a_silo_can_run_as_another_kind(self, tmp_path):
        retail = FIELD_SERVICE.parent / "retail.yaml"
        silos = yaml.safe_load(live.overlay(retail, tmp_path / "p.yaml", False,
                                            kinds={"till": "sqlite"}).read_text())["silos"]

        assert silos["till"]["kind"] == "sqlite" and "database" not in silos["till"]

    def test_migrations_join_the_packs_own(self, tmp_path):
        rescale = {"at": "9d", "operation": "rescale_column", "table": "dispatch.invoices",
                   "column": "total", "factor": "100"}
        spec = yaml.safe_load(live.overlay(FIELD_SERVICE, tmp_path / "p.yaml", False,
                                           migrations=[rescale]).read_text())

        assert spec["migrations"][-1] == rescale


def test_a_replica_can_be_made_a_real_standby(tmp_path):
    silos = yaml.safe_load(live.overlay(FIELD_SERVICE, tmp_path / "p.yaml", False,
                                        streaming=("office",)).read_text())["silos"]

    assert silos["office"]["replication"] == "streaming"
    assert "refresh" not in silos["office"]
    assert silos["office"]["database"] == silos["dispatch"]["database"]


class TestTheDeploymentItWrites:
    CONNECTIONS = {
        "dispatch": {"kind": "postgresql", "host": "127.0.0.1", "port": 5, "database": "d",
                     "user": "reader", "password": "pg-secret"},
        "shop": {"kind": "mariadb", "host": "127.0.0.1", "port": 6, "database": "s",
                 "user": "reader", "password": "maria-secret"},
        "books": {"kind": "rest", "base_url": "http://127.0.0.1:7",
                  "auth": "oauth_client_credentials", "token_url": "http://127.0.0.1:7/t",
                  "client_id": "books-client", "client_secret": "api-secret"},
        "payroll": {"kind": "filedrop", "path": "/x", "format": "zip", "encoding": "cp1252",
                    "delimiter": ";"},
    }

    def _write(self, tmp_path):
        tables = [live.Table("dispatch", "invoices", {"invoice_id": "text", "total": "decimal"},
                             "invoice_id"),
                  live.Table("shop", "orders", {"order_id": "text", "placed_at": "timestamp"},
                             "order_id"),
                  live.Table("books", "invoices", {"invoice_id": "text"}, "invoice_id",
                             collection="invoices"),
                  live.Table("payroll", "pay_lines", {"pay_line_id": "text"}, "pay_line_id",
                             files="pay_lines_*.csv")]
        env = live.configure(tables, self.CONNECTIONS, tmp_path)
        return env, {name: yaml.safe_load((tmp_path / name).read_text())
                     for name in ("data_silos.yaml", "ontology_schema.yaml", "policy.yaml")}

    def test_no_credential_is_written_down(self, tmp_path):
        env, files = self._write(tmp_path)
        written = "".join((tmp_path / name).read_text() for name in files)

        assert sorted(env.values()) == ["api-secret", "maria-secret", "pg-secret"]
        assert not any(secret in written for secret in env.values())

    def test_each_source_is_described_as_an_operator_would(self, tmp_path):
        _, files = self._write(tmp_path)
        silos = files["data_silos.yaml"]["data_silos"]
        fields = files["ontology_schema.yaml"]["object_types"]["ShopOrders"]["fields"]

        assert silos["books"]["connection"]["auth"]["type"] == "oauth_client_credentials"
        assert silos["payroll"]["connection"]["tables"]["pay_lines"]["files"] == \
            "pay_lines_*.csv.zip"
        assert silos["payroll"]["locale"] == "de_DE", "a semicolon file decimals with commas"
        assert silos["shop"]["zero_dates_as_null"] is True
        assert fields["placed_at"] == {"type": "data", "data_type": "timestamptz",
                                       "timezone": "UTC"}

    def test_every_field_is_granted_to_the_reader(self, tmp_path):
        _, files = self._write(tmp_path)
        grants = files["policy.yaml"]["roles"][live.ROLE]["allowed_actions"]

        assert {"read:DispatchInvoices", "read:DispatchInvoices.total",
                "read:DispatchInvoices.invoice_id"} <= set(grants)


class TestHowItJudges:
    def test_values_are_spelled_one_way(self):
        assert live.canonical("12,50", "decimal") == live.canonical(Decimal("12.5"), "decimal")
        assert live.canonical("1/9/2026", "date") == "2026-01-09"
        assert live.canonical("0000-00-00 00:00:00", "timestamp") is None
        assert live.canonical("2026-01-01T05:00:00-05:00", "timestamp") == \
            live.canonical("2026-01-01 10:00:00", "timestamp")
        assert live.canonical("t", "boolean") is True

    def test_a_missing_an_extra_and_a_wrong_row_are_each_named(self):
        truth = {"a": {"v": 1}, "b": {"v": 2}}
        served = {"a": {"v": 9}, "c": {"v": 3}}

        said = " | ".join(live.differences(served, truth))

        assert "1 row(s) at the source not served" in said and "'b'" in said
        assert "1 row(s) served that the source does not have" in said and "'c'" in said
        assert "a.v: served 9, source 1" in said

    def test_agreement_says_nothing(self):
        assert live.differences({"a": {"v": 1}}, {"a": {"v": 1}}) == []

    def test_a_syncs_own_words_are_read(self):
        outcomes = live.Outcomes.parse(
            "synced  dispatch.invoices: 5 rows at x\n"
            "FAILED  books.invoices: rest ...: HTTP 503, still after 5 retries.\n"
            "REFUSED gold.OfficeInvoices: too few rows\n")
        books = live.Table("books", "invoices", {}, "id")
        office = live.Table("office", "invoices", {}, "id")
        dispatch = live.Table("dispatch", "invoices", {}, "id")

        assert "HTTP 503" in outcomes.stopped(books)
        assert outcomes.stopped(office) == "too few rows"
        assert outcomes.stopped(dispatch) is None

    def test_the_oracle_catches_what_both_readers_miss(self):
        """Row-level security hides rows from Elysium AND the plain reader
        alike; only the business's own count can say so."""
        table = live.Table("dispatch", "work_orders", {"work_order_id": "text"},
                           "work_order_id")
        oracle = {"count(dispatch.work_orders.work_order_id)":
                  [{"at": "x", "value": "76", "ok": True}]}

        said = live.oracle_findings(1, oracle, [table], {"DispatchWorkOrders": {}}, set())
        kept = live.oracle_findings(1, oracle, [table], {"DispatchWorkOrders": {}},
                                    {"DispatchWorkOrders"})

        assert len(said) == 1 and "76" in said[0].what
        assert kept == [], "a table kept at its last good copy is not judged by today's total"

    def test_a_sum_that_matches_is_not_reported(self):
        table = live.Table("dispatch", "invoices", {"invoice_id": "text", "total": "decimal"},
                           "invoice_id")
        oracle = {"sum(dispatch.invoices.total)": [{"at": "x", "value": "15.5000", "ok": True}]}
        served = {"DispatchInvoices": {"a": {"total": Decimal("10")},
                                       "b": {"total": Decimal("5.5")}}}

        assert live.oracle_findings(1, oracle, [table], served, set()) == []


def test_a_file_cut_mid_line_is_unverifiable_not_agreement(tmp_path):
    """Cut inside its last field, a row keeps the header's width and its
    value is wrong; only the missing line ending says so."""
    (tmp_path / "pay_1.csv").write_bytes(b"id;total\r\n1;12\r\n2;456")
    table = live.Table("payroll", "pay", {"id": "text", "total": "decimal"}, "id",
                       files="pay_*.csv")

    said = live.read_source(table, {"kind": "filedrop", "path": str(tmp_path),
                                    "encoding": "utf-8", "delimiter": ";"})

    assert isinstance(said, str) and said.startswith("UNVERIFIABLE") and "pay_1.csv" in said
