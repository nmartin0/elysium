-- support_schema.sql  (tests/integration/'s OWN dev fixture for the
-- support_crm silo -- a GENUINELY SEPARATE database from
-- schema.sql/mediator.db, for tests/integration/test_cross_silo_e2e.py.
--
-- Rebuilt FRESH into an isolated temp SQLite database for every single
-- test (see conftest.py), matching schema.sql's own discipline exactly.
--
-- customer_id here is NOT a foreign key into a customers table in
-- THIS database -- that table lives in the OTHER silo (primary_sql).
-- It's just a plain TEXT column; the cross-silo link resolution
-- (core/ontology/mediator.py) is what gives it meaning at query time.
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    subject     TEXT NOT NULL,
    status      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_customer_id
    ON tickets (customer_id);
-- cust_001 (Ada Okafor, us-west, in the OTHER silo) gets two real
-- tickets -- something genuine for a real model to discover and
-- follow. cust_003 (us-east) gets one, for a future cross-silo MAC
-- boundary test if ever needed.
INSERT INTO tickets (customer_id, subject, status) VALUES
    ('cust_001', 'Login page returns a 500 error', 'open'),
    ('cust_001', 'Requesting a refund for hardware order', 'closed'),
    ('cust_003', 'Cannot update billing address', 'open');
