"""
ontology_adapter.py  (acme_corp-specific -- one line, binds this org's engine)

All the actual query/security logic is generic, in
core/ontology/sql_adapter.py's OntologyEngine class. This file's only
job is to construct the engine with acme_corp's own database and
schema -- `engine.search_object` and `engine.get_field` are bound
methods, which work as drop-in callables anywhere a plain function was
expected before (e.g. core/agent/agentic_loop.py's AgentLoop).
"""

from core.ontology.sql_adapter import OntologyEngine
from deployments.acme_corp.deployment import config

engine = OntologyEngine(config.db_path, config.schema)
