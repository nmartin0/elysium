-- schema.sql  (tests/integration/'s OWN dev fixture -- see config.yaml's
-- header for why this is a fully separate fixture from the real
-- deployment/var/lib/dev_fixtures/schema.sql that ships to a new
-- deployer as example data to explore)
--
-- Rebuilt FRESH into an isolated temp SQLite database for every single
-- test (see conftest.py) -- never a shared, persistent file a test
-- could accidentally corrupt for the NEXT test run.
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL,
    email       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     TEXT NOT NULL,
    amount          REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    category        TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_customer_id
    ON transactions (customer_id);
-- accounts -- for tests/integration/test_transfer_funds_e2e.py and
-- tests/unit/test_transfer_funds.py: the first REAL, deliberately-
-- authored multi-object action_type (TransferFunds, two sub_writes,
-- both Account) exercised through the actual apply path (_apply_
-- batch(), sorted-order locking with two REAL, different locks) --
-- not just the synthetic fixtures test_write_log_batches.py and
-- test_action_types_validation.py already used to prove the
-- mechanism itself. Both seed accounts owned by the SAME customer
-- (cust_001) -- a genuine, real MAC chain (via_field: owner_
-- customer_id, same pattern as transactions/tickets above), just
-- deliberately not ALSO exercising a cross-customer-ownership
-- variant, which isn't this addition's own point to prove.
CREATE TABLE IF NOT EXISTS accounts (
    account_id        TEXT PRIMARY KEY,
    owner_customer_id TEXT NOT NULL,
    balance           REAL NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'USD',
    FOREIGN KEY (owner_customer_id) REFERENCES customers (customer_id)
);
CREATE INDEX IF NOT EXISTS idx_accounts_owner_customer_id
    ON accounts (owner_customer_id);
INSERT INTO customers (customer_id, name, region, email) VALUES
    ('cust_001', 'Ada Okafor',   'us-west', 'ada.okafor@example.com'),
    ('cust_002', 'Bram Feldman', 'us-west', 'bram.feldman@example.com'),
    ('cust_003', 'Chidi Nwosu',  'us-east', 'chidi.nwosu@example.com'),
    ('cust_004', 'Dana Petrova', 'eu',      'dana.petrova@example.com');
INSERT INTO transactions (customer_id, amount, currency, category, transaction_date) VALUES
    ('cust_001', 49.99,  'USD', 'subscription', '2026-05-01'),
    ('cust_001', 199.00, 'USD', 'hardware',     '2026-06-14'),
    ('cust_002', 49.99,  'USD', 'subscription', '2026-05-01'),
    ('cust_002', -20.00, 'USD', 'refund',       '2026-06-02'),
    ('cust_003', 49.99,  'USD', 'subscription', '2026-05-03'),
    ('cust_003', 349.00, 'USD', 'hardware',     '2026-07-10'),
    ('cust_004', 44.99,  'EUR', 'subscription', '2026-05-05');
INSERT INTO accounts (account_id, owner_customer_id, balance, currency) VALUES
    ('acc_checking', 'cust_001', 500.00,  'USD'),
    ('acc_savings',  'cust_001', 1000.00, 'USD');
