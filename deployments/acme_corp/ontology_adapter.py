"""
ontology_adapter.py  (acme_corp-specific -- binds this org's db + schema)

All the actual query/security logic is now generic, in
core/ontology/sql_adapter.py. This file's only job is to supply
acme_corp's own database path and schema, producing functions that
match the (user_security_value, object_type, ...) calling convention
core/agent/loop.py already expects -- functools.partial pre-fills the
first two arguments so callers see the same 3-arg/4-arg signatures as
before this refactor.
"""

from functools import partial
from pathlib import Path

from core.ontology.sql_adapter import search_object as _search_object, get_field as _get_field
from deployments.acme_corp.deployment import SCHEMA

DB_PATH = Path(__file__).resolve().parent / "dev_fixtures" / "mediator.db"

search_object = partial(_search_object, DB_PATH, SCHEMA)
get_field = partial(_get_field, DB_PATH, SCHEMA)
