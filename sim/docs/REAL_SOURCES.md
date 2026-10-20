# How real sources behave, and how the simulator's compare

BLOCKING.md item 12, step one (19 October): research how each real kind
of source behaves, write it down, and probe the simulator against it.
This is that list. Each row says what the REAL thing does (with its
source and default), what the SIMULATOR does today (from reading its
code), and whether they agree.

- **Agrees** -- the simulator behaves as the real thing does.
- **Kinder** -- the simulator is easier on a reader than reality: a
  consumer passing against it can still fail in production. These are
  what this item exists to close.
- **Missing** -- the real behaviour cannot be produced at all.
- **Bug** -- the simulator is wrong about itself.

Where a primary source could not be fetched, the row says so. Nothing
here is the simulator's founding rule changing: the databases are still
its only interface, and it still does not know Elysium exists.

## Operating the world

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| O1 | Sources go away and come back: a database restarts (PostgreSQL clients see SQLSTATE 57P01 `admin_shutdown`), an API is down for maintenance, a share is unmounted. | `terminate()` exists for every kind (SIGQUIT, SIGKILL, rename to `.gone`, socket closed) but nothing outside the tests calls it. | Missing |
| O2 | Time can be stopped while someone looks. | No pause; `clock.py` defers it to a control server that does not exist. | Missing |
| O3 | A schema change made by a DBA lands while applications keep writing. | A live `simulator drift` from another terminal changes the database but not the running engine, which crashes on its next write to the moved column. | Bug |
| O4 | After a restart, history does not repeat. | Scheduled migrations are matched against elapsed time, which resets on `--resume`; from the code they look likely to fire again. Not yet reproduced. | Bug (suspected) |
| O5 | -- (the yardstick) | The oracle lives in memory and can be read only through the console; nothing outside the process can compare against it. `verify` is hard-wired to `/v1/invoices`. | Missing |

## PostgreSQL 16

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| P1 | A table created later is invisible to a reader -- SQLSTATE 42501 -- unless `ALTER DEFAULT PRIVILEGES` was set for that exact creator role ([ddl-priv](https://www.postgresql.org/docs/16/ddl-priv.html), [alterdefaultprivileges](https://www.postgresql.org/docs/16//sql-alterdefaultprivileges.html)). | Default privileges are granted before the schema exists, so every later table is readable. | Kinder |
| P2 | Row-level security with no policy for a role returns NO rows, without an error ([ddl-rowsecurity](https://www.postgresql.org/docs/16//ddl-rowsecurity.html)). | Never switched on. | Missing |
| P3 | `statement_timeout`, `idle_session_timeout`, `idle_in_transaction_session_timeout` default to 0 ([runtime-config-client](https://www.postgresql.org/docs/16/runtime-config-client.html)); managed services and DBAs commonly set them; `max_connections` is typically 100. | Left at defaults. | Agrees (defaults); no way to set a managed-service profile |
| P4 | `TimeZone` is GMT built in, but initdb installs the system's zone; `timestamptz` is shown in the session's zone, `timestamp` ignores zones ([datatype-datetime](https://www.postgresql.org/docs/16//datatype-datetime.html)). | Whatever the host's zone is at initdb; timestamps written are UTC from the simulated clock. | Agrees, but unpinned (varies by host) |
| P5 | Read Committed by default; a multi-statement copy is consistent only under Repeatable Read ([transaction-iso](https://www.postgresql.org/docs/16/transaction-iso.html)). | Real PostgreSQL; writes commit once per tick. | Agrees |
| P6 | `ALTER TABLE` takes ACCESS EXCLUSIVE and waits for open readers; DROP COLUMN is instant, ALTER TYPE rewrites ([sql-altertable](https://www.postgresql.org/docs/16/sql-altertable.html)). | Real PostgreSQL executes the drift. | Agrees |
| P7 | A read replica lags its primary, and a long read on it is cancelled after `max_standby_streaming_delay` (30 s) when `hot_standby_feedback` is off ([hot-standby](https://www.postgresql.org/docs/16/hot-standby.html)). | A "replica" is a separate silo emptied and refilled in the same tick transaction: no streaming lag, no recovery conflicts; and it does not follow drift (a source drift should break its next refresh). | Kinder, and Bug |
| P8 | Password auth is scram-sha-256; pg_hba has no fall-through ([auth-pg-hba-conf](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html)). | scram-sha-256 rules for reader and writer, trust for the superuser. | Agrees |

## MariaDB 10.11

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| M1 | `character_set_server` defaults to `latin1` (Debian packages override to utf8mb4); `utf8` means utf8mb3, which cannot hold emoji ([server-system-variables](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables), [unicode](https://mariadb.com/docs/server/reference/data-types/string-data-types/character-sets/unicode)). | Every table is created utf8mb4. | Kinder |
| M2 | The default `sql_mode` does not include NO_ZERO_DATE, so `0000-00-00` dates are accepted, and break many drivers ([sql_mode](https://mariadb.com/docs/server/server-management/variables-and-modes/sql_mode)). | Never written. | Missing |
| M3 | An idle connection is closed after `wait_timeout`; the next statement gets error 2006, "MySQL server has gone away" ([transaction-timeouts](https://mariadb.com/docs/server/reference/sql-statements/transactions/transaction-timeouts)). The 28800 default could not be confirmed from the truncated page. | Left at default. | Agrees (default); not settable |
| M4 | `time_zone` defaults to SYSTEM; TIMESTAMP is converted through the session zone, DATETIME is stored literally ([time-zones](https://mariadb.com/docs/server/reference/data-types/string-data-types/character-sets/internationalization-and-localization/time-zones)). | Timestamps are DATETIME holding UTC wall-clock values. | Agrees (one of the real choices) |
| M5 | REPEATABLE READ by default; the snapshot is taken at the first read, not at BEGIN ([set-transaction](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/set-commands/set-transaction)). | Real MariaDB. | Agrees |
| M6 | BOOLEAN is TINYINT(1); JSON is LONGTEXT with a check ([boolean](https://mariadb.com/docs/server/reference/data-types/numeric-data-types/boolean), [json](https://mariadb.com/docs/server/reference/data-types/string-data-types/json)). | BOOLEAN; no JSON type in the simulator. | Agrees; JSON missing |
| M7 | The server's behaviour is whatever its configuration says. | The server reads the host's `/etc/mysql` configuration (no `--no-defaults`), so a world differs from machine to machine. | Bug |
| M8 | Withholding one table from a reader does not change what it can see of tables added later. | `withheld:` replaces the database-wide grant with per-table grants, so later tables are readable by nobody. | Bug (or an accidental P1) |

## CSV drops

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| F1 | A partial file is visible during an SFTP upload (Files.com keeps partial uploads "enabled by default"); S3 never shows a half-written object ([files.com](https://www.files.com/docs/services/sftp/preserve-partial-sftp-uploads-after-disconnects), [S3 multipart](https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuAndPermissions.html)). | Always write-then-rename; `atomic=False` exists but nothing can reach it. | Kinder |
| F2 | Files are re-sent, replaced in place, arrive late, or vanish to retention (S3 expiry is asynchronous) ([S3 lifecycle](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html)). | One file per firing, never re-sent, never late, never deleted. | Missing |
| F3 | Excel's plain CSV is a Windows code page; "CSV UTF-8" carries a BOM; the delimiter is the regional list separator -- a semicolon where the decimal mark is a comma ([Excel formats](https://support.microsoft.com/en-US/Excel/file-formats-supported-in-excel-for-mac)). The code-page and BOM details are not confirmed from a primary page. | UTF-8 with BOM, comma, CRLF, always. | Kinder |
| F4 | A file opened and saved in Excel loses leading zeros, turns long numbers into scientific notation, and turns codes into dates ([automatic data conversions](https://support.microsoft.com/en-US/Excel/set-automatic-data-conversions)). | Never. | Missing |
| F5 | Headers change between exports: columns added, renamed, reordered. (Practitioner knowledge; no primary source.) | Columns are fixed by the pack; a drift that drops or renames one makes the export FAIL instead. | Missing, and Bug |
| F6 | Exports arrive zipped (QuickBooks Online exports "Excel files in one .zip file") ([QuickBooks](https://quickbooks.intuit.com/learn-support/en-us/exporting-reports/export-reports-lists-and-more/00/187949)). | CSV only. | Missing |

## REST APIs

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| R1 | Access tokens expire: Xero 30 minutes, QuickBooks 1 hour; refresh tokens rotate ([Xero](https://devblog.xero.com/xero-api-token-management-best-practices-and-troubleshooting-01853f4244a9), [Intuit](https://github.com/IntuitDeveloper/OAuth2-Dotnet_UsingSDK/blob/master/docs/help/Tokens.md)). | A fixed token that never expires. | Kinder |
| R2 | Rate limits are per window and say so: Shopify's leaky bucket with `X-Shopify-Shop-Api-Call-Limit` and `Retry-After: 2.0`; Xero 60 calls/minute with `Retry-After`; GitHub 403 or 429 with `x-ratelimit-reset` ([Shopify](https://shopify.dev/docs/api/admin-rest/usage/rate-limits), [Xero](https://developer.xero.com/faq/limits), [GitHub](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). | Off by default; when on, a counter that never resets, so the API refuses forever. | Bug |
| R3 | Servers fail: 500/502/503/504, timeouts (GitHub ends requests over 10 s), and 429 that is a lock, not a limit (Stripe) ([Stripe errors](https://docs.stripe.com/api/errors?lang=node)). | No 5xx, no slowness. | Missing |
| R4 | Paging while records change can skip or repeat them -- Stripe says so of search ([Stripe search](https://docs.stripe.com/search)). | An offset inside an opaque cursor over a list replaced whole at each republication: a republish mid-read skips or repeats. | Agrees |
| R5 | Formats vary: Stripe money in integer minor units and timestamps as epoch seconds, nulls present ([Stripe currencies](https://docs.stripe.com/currencies.md)); many accounting APIs use decimal strings and ISO dates. | Decimal strings, ISO 8601. | Agrees (one real choice); not variable |
| R6 | Deletions are visible in some APIs (`deleted: true`, QuickBooks CDC `status: Deleted`), invisible in others ([Stripe delete](https://docs.stripe.com/api/customers/delete)). | A deleted row simply disappears at the next publication. | Agrees (one real choice) |
| R7 | Many APIs filter by change time (`If-Modified-Since` on Xero, `changedSince` on QuickBooks CDC). | No filter. | Missing |

## What most often breaks a consumer, per the research

Databases: tables added later being unreadable (P1); row-level security
returning nothing silently (P2); zone handling (P4, M4); zero dates
(M2); idle disconnects (M3); long reads on a replica being cancelled
(P7). Files: partial files (F1), re-sent and late files (F2), encodings
and regional delimiters (F3), Excel's conversions (F4), changing headers
(F5). APIs: expiring tokens (R1), rate limits in their many forms (R2),
records shifting during paging (R4), formats (R5) and deletions (R6).
