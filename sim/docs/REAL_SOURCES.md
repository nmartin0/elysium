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
| O1 | Sources go away and come back: a database restarts (PostgreSQL clients see SQLSTATE 57P01 `admin_shutdown`), an API is down for maintenance, a share is unmounted. | `outage` / `restore` through the control channel (simulator/outages.py), cutting off the reader only: PostgreSQL ends its sessions (57P01) and refuses logins, MariaDB locks the account and kills its connections, REST answers 503 with Retry-After, a share or SQLite file is moved aside while the business keeps writing to it. Stopping the world restores every outage. | Fixed (item 12 step 1) |
| O2 | Time can be stopped while someone looks. | `pause`, `resume` and `advance` through the control channel (simulator/control.py); a paused world does not tick and the pause is not owed back. | Fixed (item 12 step 1) |
| O3 | A schema change made by a DBA lands while applications keep writing. | A live `simulator drift` is sent to the running world and applied by it. The business then follows the change (simulator/lineage.py): it writes and reads under the new names, stops writing a dropped column, and keeps the record across a resume. This crash happened even for a rename the engine applied itself. | Fixed (item 12 step 1) |
| O4 | After a restart, history does not repeat. | Reproduced, then fixed: state.json now keeps the elapsed time, and a resume restores the whole history rather than restarting at zero. | Fixed (item 12 step 1) |
| O5 | -- (the yardstick) | `oracle` through the control channel returns every watched number's samples as JSON. The control channel's address and token are in `control.json` (owner-only), never in `connections.json`. | Fixed (item 12 step 1) |

Found while fixing these, by an independent review on 20 October, and
fixed with them: a world with a replica could never be resumed (a fresh
world's saved shape left the replica out), a schema change reached a
replica's database but not the world's record of it, a control command
that timed out still ran later, and an outage left by a killed run could
not be ended.

**Step 2, 20 October: realism options.** Every behaviour below marked
"when switched on" is a silo option in a pack (`options:` under the
silo), off unless a pack sets it -- the way Toxiproxy's toxics are off
until added -- so existing packs and their tests read exactly as before.
Two defaults did change, both to pin a world to the same behaviour on
every machine: PostgreSQL's and MariaDB's time zones are UTC rather than
the host's. And a replica must now run its source's engine, as every
real read replica does.

## PostgreSQL 16

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| P1 | A table created later is invisible to a reader -- SQLSTATE 42501 -- unless `ALTER DEFAULT PRIVILEGES` was set for that exact creator role ([ddl-priv](https://www.postgresql.org/docs/16/ddl-priv.html), [alterdefaultprivileges](https://www.postgresql.org/docs/16//sql-alterdefaultprivileges.html)). | Default privileges cover later tables unless a pack sets `reader_default_privileges: false`; then the pack's own tables are granted once they exist and a table added later refuses the reader with 42501. | Agrees when switched on (step 2) |
| P2 | Row-level security with no policy for a role returns NO rows, without an error ([ddl-rowsecurity](https://www.postgresql.org/docs/16//ddl-rowsecurity.html)). | `row_security: [table, ...]` turns row-level security on with no policy: the reader sees no rows and no error; the business, writing as the superuser, carries on. | Agrees when switched on (step 2) |
| P3 | `statement_timeout`, `idle_session_timeout`, `idle_in_transaction_session_timeout` default to 0 ([runtime-config-client](https://www.postgresql.org/docs/16/runtime-config-client.html)); managed services and DBAs commonly set them; `max_connections` is typically 100. | Defaults, unless a pack sets `reader_statement_timeout_ms`, `reader_idle_session_timeout_ms` or `reader_idle_in_transaction_timeout_ms`, which are set on the reader's role (QueryCanceled, and a closed idle session). | Agrees; settable (step 2) |
| P4 | `TimeZone` is GMT built in, but initdb installs the system's zone; `timestamptz` is shown in the session's zone, `timestamp` ignores zones ([datatype-datetime](https://www.postgresql.org/docs/16//datatype-datetime.html)). | Pinned to UTC, as RDS defaults, rather than the host's zone; a pack may set `timezone`. (On a host already in UTC the pin cannot be told from the default.) | Agrees, pinned (step 2) |
| P5 | Read Committed by default; a multi-statement copy is consistent only under Repeatable Read ([transaction-iso](https://www.postgresql.org/docs/16/transaction-iso.html)). | Real PostgreSQL; writes commit once per tick. | Agrees |
| P6 | `ALTER TABLE` takes ACCESS EXCLUSIVE and waits for open readers; DROP COLUMN is instant, ALTER TYPE rewrites ([sql-altertable](https://www.postgresql.org/docs/16/sql-altertable.html)). | Real PostgreSQL executes the drift. | Agrees |
| P7 | A read replica lags its primary, and a long read on it is cancelled after `max_standby_streaming_delay` (30 s) when `hot_standby_feedback` is off ([hot-standby](https://www.postgresql.org/docs/16/hot-standby.html)). | A "replica" is a separate silo emptied and refilled in the same tick transaction: no streaming lag and no recovery conflicts. A source's drift reaches it, and since 20 October so do its grants and row security, as a streamed replica's catalog does. | Kinder (lag and cancelled reads deferred) |
| P8 | Password auth is scram-sha-256; pg_hba has no fall-through ([auth-pg-hba-conf](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html)). | scram-sha-256 rules for reader and writer, trust for the superuser. | Agrees |

## MariaDB 10.11

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| M1 | `character_set_server` defaults to `latin1` (Debian packages override to utf8mb4); `utf8` means utf8mb3, which cannot hold emoji ([server-system-variables](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables), [unicode](https://mariadb.com/docs/server/reference/data-types/string-data-types/character-sets/unicode)). | Every table is created utf8mb4. | Kinder (deferred: a utf8mb3 option would fail the business's own writes of emoji, not a reader's) |
| M2 | The default `sql_mode` does not include NO_ZERO_DATE, so `0000-00-00` dates are accepted, and break many drivers ([sql_mode](https://mariadb.com/docs/server/server-management/variables-and-modes/sql_mode)). | `zero_dates: true` makes the business write 0000-00-00 where it has no date -- in the columns it leaves out as well as the ones it sets to none -- which the default sql_mode allows. | Agrees when switched on (step 2) |
| M3 | An idle connection is closed after `wait_timeout`; the next statement gets error 2006, "MySQL server has gone away" ([transaction-timeouts](https://mariadb.com/docs/server/reference/sql-statements/transactions/transaction-timeouts)). The 28800 default could not be confirmed from the truncated page. | Default unless a pack sets `reader_wait_timeout_seconds` (and `reader_max_statement_seconds`), applied through init_connect, which skips the business's superuser; an idle reader then gets error 2006/2013. | Agrees; settable (step 2) |
| M4 | `time_zone` defaults to SYSTEM; TIMESTAMP is converted through the session zone, DATETIME is stored literally ([time-zones](https://mariadb.com/docs/server/reference/data-types/string-data-types/character-sets/internationalization-and-localization/time-zones)). | Timestamps are DATETIME holding UTC wall-clock values; the server's zone is pinned to +00:00 (it was the host's) and settable as `time_zone`. | Agrees, pinned (step 2) |
| M5 | REPEATABLE READ by default; the snapshot is taken at the first read, not at BEGIN ([set-transaction](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/set-commands/set-transaction)). | Real MariaDB. | Agrees |
| M6 | BOOLEAN is TINYINT(1); JSON is LONGTEXT with a check ([boolean](https://mariadb.com/docs/server/reference/data-types/numeric-data-types/boolean), [json](https://mariadb.com/docs/server/reference/data-types/string-data-types/json)). | BOOLEAN; no JSON type in the simulator. | Agrees; JSON missing |
| M7 | The server's behaviour is whatever its configuration says. | The server starts with `--no-defaults`, so a world behaves the same on every machine (character_set_server reads latin1, MariaDB's own default). | Fixed (item 12 step 1) |
| M8 | Withholding one table from a reader does not change what it can see of tables added later. | `withheld:` replaces the database-wide grant with per-table grants, so later tables are readable by nobody -- which is what MariaDB itself forces, having no per-table deny. | Agrees (the engine's own limit) |

## CSV drops

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| F1 | A partial file is visible during an SFTP upload (Files.com keeps partial uploads "enabled by default"); S3 never shows a half-written object ([files.com](https://www.files.com/docs/services/sftp/preserve-partial-sftp-uploads-after-disconnects), [S3 multipart](https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuAndPermissions.html)). | Write-then-rename by default; `atomic_writes: false` leaves each file half-written, cut mid-row, until the next tick. | Agrees when switched on (step 2); Elysium refuses a file cut mid-line since 21 October |
| F2 | Files are re-sent, replaced in place, arrive late, or vanish to retention (S3 expiry is asynchronous) ([S3 lifecycle](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html)). | `duplicate_rate` re-sends a share of files as "name (1).csv"; `late_rate`/`late_seconds` deliver a share late in simulated time; `keep_last` keeps only the newest files. | Agrees when switched on (step 2) |
| F3 | Excel's plain CSV is a Windows code page; "CSV UTF-8" carries a BOM; the delimiter is the regional list separator -- a semicolon where the decimal mark is a comma ([Excel formats](https://support.microsoft.com/en-US/Excel/file-formats-supported-in-excel-for-mac)). The code-page and BOM details are not confirmed from a primary page. | UTF-8 with BOM, comma, CRLF by default; `encoding: cp1252` ("?" for what it cannot hold), `delimiter: ';'` or tab, `decimal_comma: true`. | Agrees when switched on (step 2) |
| F4 | A file opened and saved in Excel loses leading zeros, turns long numbers into scientific notation, and turns codes into dates ([automatic data conversions](https://support.microsoft.com/en-US/Excel/set-automatic-data-conversions)). | `excel_conversions: true` applies Microsoft's listed conversions -- leading zeros, 16+ digits, digits around E, JAN1 -- plus trailing zeros and US-format dates. | Agrees when switched on (step 2) |
| F5 | Headers change between exports: columns added, renamed, reordered. (Practitioner knowledge; no primary source.) | After a rename or drop the next header follows the database; `reorder_columns: true` changes the order in each file. Columns are never added on their own. | Mostly (additions deferred) |
| F6 | Exports arrive zipped (QuickBooks Online exports "Excel files in one .zip file") ([QuickBooks](https://quickbooks.intuit.com/learn-support/en-us/exporting-reports/export-reports-lists-and-more/00/187949)). | `zipped: true` delivers each file inside a .zip of the same name. | Agrees when switched on (step 2) |

## REST APIs

| # | Real behaviour | Simulator today | Verdict |
|---|---|---|---|
| R1 | Access tokens expire: Xero 30 minutes, QuickBooks 1 hour; refresh tokens rotate ([Xero](https://devblog.xero.com/xero-api-token-management-best-practices-and-troubleshooting-01853f4244a9), [Intuit](https://github.com/IntuitDeveloper/OAuth2-Dotnet_UsingSDK/blob/master/docs/help/Tokens.md)). | A fixed token by default; `token_lifetime_seconds` turns on the client-credentials grant at /oauth/token (as Xero's custom connections), with an expired token answered 401 and `WWW-Authenticate: Bearer error="invalid_token"`. | Agrees when switched on (step 2) |
| R2 | Rate limits are per window and say so: Shopify's leaky bucket with `X-Shopify-Shop-Api-Call-Limit` and `Retry-After: 2.0`; Xero 60 calls/minute with `Retry-After`; GitHub 403 or 429 with `x-ratelimit-reset` ([Shopify](https://shopify.dev/docs/api/admin-rest/usage/rate-limits), [Xero](https://developer.xero.com/faq/limits), [GitHub](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). | A rolling window (60 s by default) with X-RateLimit-Limit, -Remaining and -Reset headers and a Retry-After that counts down to the window's end. | Fixed (item 12 step 1) |
| R3 | Servers fail: 500/502/503/504, timeouts (GitHub ends requests over 10 s), and 429 that is a lock, not a limit (Stripe) ([Stripe errors](https://docs.stripe.com/api/errors?lang=node)). | `fault_rate` answers a share of requests with 500/502/503/504 (or `fault_statuses`); `latency_ms` +/- `latency_jitter_ms` delays every reply, as Toxiproxy's toxics do. | Agrees when switched on (step 2) |
| R4 | Paging while records change can skip or repeat them -- Stripe says so of search ([Stripe search](https://docs.stripe.com/search)). | An offset inside an opaque cursor over a list replaced whole at each republication: a republish mid-read skips or repeats. | Agrees |
| R5 | Formats vary: Stripe money in integer minor units and timestamps as epoch seconds, nulls present ([Stripe currencies](https://docs.stripe.com/currencies.md)); many accounting APIs use decimal strings and ISO dates. | Decimal strings, ISO 8601. | Agrees (one real choice); not variable |
| R6 | Deletions are visible in some APIs (`deleted: true`, QuickBooks CDC `status: Deleted`), invisible in others ([Stripe delete](https://docs.stripe.com/api/customers/delete)). | A deleted row simply disappears at the next publication. | Agrees (one real choice) |
| R7 | Many APIs filter by change time (`If-Modified-Since` on Xero, `changedSince` on QuickBooks CDC). | `modified_since_field` honours Xero's `If-Modified-Since` header (ISO 8601 or HTTP-date). | Agrees when switched on (step 2) |

## What most often breaks a consumer, per the research

Databases: tables added later being unreadable (P1); row-level security
returning nothing silently (P2); zone handling (P4, M4); zero dates
(M2); idle disconnects (M3); long reads on a replica being cancelled
(P7). Files: partial files (F1), re-sent and late files (F2), encodings
and regional delimiters (F3), Excel's conversions (F4), changing headers
(F5). APIs: expiring tokens (R1), rate limits in their many forms (R2),
records shifting during paging (R4), formats (R5) and deletions (R6).
