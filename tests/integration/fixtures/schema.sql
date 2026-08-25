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
