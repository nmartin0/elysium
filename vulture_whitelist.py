"""
vulture_whitelist.py  (tells Vulture these names are genuinely used,
even though it can't see how)

Vulture does whole-program analysis by NAME, not by call graph -- it's
what makes it able to catch a function nothing calls anywhere in the
project (something pyflakes/Ruff's local-scope F401/F841 genuinely
cannot do). But that same by-name approach means it has no way to see
three real, common patterns where a name IS used, just not by a direct
Python call Vulture can trace:
  - a framework invoking something via decorator registration (FastAPI
    routes, dispatched by the router at request time, not by any
    Python code calling the function's name directly)
  - a name accessed dynamically through a mock/library object rather
    than declared and read locally (unittest.mock's return_value/
    side_effect, sqlite3.Connection's row_factory)
  - a name declared as part of an interface/contract that not every
    consumer needs yet (this project's own DataSiloAdapter/MemoryEntry
    fields)

Every entry below was verified directly against this codebase before
being added here -- confirmed either genuinely used elsewhere (just
not in a way Vulture can trace) or a deliberate, documented "declared
but not yet consumed" field, never added just to silence a warning
without checking first.

Run `vulture` (config: pyproject.toml's [tool.vulture]) to check.
"""

# --- FastAPI route handlers -- invoked by the router via @router.post/
# get/delete decorators at request time, never called directly by name
# anywhere in this project's own Python code (even test_api.py goes
# through a TestClient issuing real HTTP requests, not a direct call).
login
logout
logout_all
list_users_route
create_user_route
visible_schema_route
logout_all_for_user
disable_user_route
enable_user_route
delete_user_route
confirm_write_route
search_objects_route
my_visible_schema_route

# --- unittest.mock attribute assignment -- `some_mock.return_value = x`
# / `some_mock.side_effect = fn` are how tests configure a MagicMock;
# the mock framework reads them internally at call time, not this
# project's own code, so Vulture can never see the "usage."
_.return_value
_.side_effect

# --- pytest's own special module-level variable -- marks every test
# in a file with the listed markers; read by pytest's collection
# machinery, not by any of this project's own code.
pytestmark

# --- stdlib sqlite3.Connection's own attribute -- `conn.row_factory =
# sqlite3.Row` configures how sqlite3 itself constructs result rows;
# consumed inside the sqlite3 C extension, not Python code Vulture can
# trace.
_.row_factory

# --- DataSiloAdapter interface fields (core/ontology/interface.py) --
# declared, deliberate contract fields, verified directly before being
# whitelisted (not assumed): neither is actually read by any runtime
# logic anywhere in this codebase today -- both are genuine, forward-
# looking scaffolding, declared ahead of the capability that will
# consume them (a read-concurrency limiter, and a real conditional-
# write dispatch that branches on this flag) rather than leftovers
# from something removed. Re-verify with a real grep before assuming
# this reasoning still holds if either is ever actually wired up.
max_concurrent_reads
supports_atomic_conditional_write

# --- MemoryEntry.captured_security_value (core/memory/interface.py) --
# explicitly, deliberately "audit/debugging ONLY" per its own
# docstring -- MemoryGuard is documented to NEVER read it in real
# authorization logic (always re-derives security live instead), so
# it genuinely has no in-logic reader by design, not by omission.
captured_security_value
