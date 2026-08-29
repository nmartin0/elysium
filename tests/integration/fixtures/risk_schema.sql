-- risk_schema.sql  (tests/integration's OWN dev fixture for the
-- risk_sql silo -- a GENUINELY SEPARATE database from
-- schema.sql/mediator.db and support_schema.sql/support.db, for
-- tests/integration/test_mdo_e2e.py.
--
-- Rebuilt FRESH into an isolated temp SQLite database for every single
-- test (see conftest.py), matching the other two fixture files'
-- discipline exactly.
--
-- Deliberately mismatched naming from primary_sql -- this is the
-- WHOLE POINT of this fixture, same as tests/unit/test_mdo.py:
--   - cust_ref, not customer_id -- the id COLUMN NAME can differ
--     across silos; only the identity VALUE must be shared.
--   - score_val, not risk_score -- a real external silo won't always
--     happen to name a column exactly like our own field name.
CREATE TABLE IF NOT EXISTS customer_risk (
    cust_ref  TEXT PRIMARY KEY,
    score_val REAL NOT NULL
);
-- cust_001 (Ada Okafor, us-west, in primary_sql) gets a real risk
-- score here -- something genuine for a real model to read, with zero
-- indication in its own prompt this field lives anywhere different
-- from region/name/email.
INSERT INTO customer_risk (cust_ref, score_val) VALUES
    ('cust_001', 0.35),
    ('cust_003', 0.71);
