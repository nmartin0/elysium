"""
ontology_adapter.py  (acme_corp-specific -- binds this org's db + schema)

All the actual query/security logic is generic, in
core/ontology/sql_adapter.py. This file's only job is to supply
acme_corp's own database path and schema (both sourced from
deployment.py, which loaded them from YAML) -- producing functions that
match the (user_security_value, object_type, ...) calling convention
core/agent/loop.py already expects.
"""

from functools import partial

from core.ontology.sql_adapter import search_object as _search_object, get_field as _get_field
from deployments.acme_corp.deployment import DB_PATH, SCHEMA

search_object = partial(_search_object, DB_PATH, SCHEMA)
get_field = partial(_get_field, DB_PATH, SCHEMA)
