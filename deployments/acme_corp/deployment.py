"""
deployment.py  (acme_corp-specific -- supplies this org's own path, nothing else)

All the actual loading logic lives in core/deployment_loader.py, which is
fully generic. This file's only job is to say WHERE acme_corp's config
files live and re-expose the results under the same names test_run.py
already expects.
"""

from pathlib import Path

from core.deployment_loader import load_deployment

_deployment = load_deployment(Path(__file__).resolve().parent)

OLLAMA_URL = _deployment.OLLAMA_URL
STEP_MODEL = _deployment.STEP_MODEL
SYNTHESIS_MODEL = _deployment.SYNTHESIS_MODEL
REQUEST_TIMEOUT_SECONDS = _deployment.REQUEST_TIMEOUT_SECONDS
MAX_HOPS = _deployment.MAX_HOPS
MAX_CONSECUTIVE_DUPLICATES = _deployment.MAX_CONSECUTIVE_DUPLICATES
SCHEMA = _deployment.SCHEMA
USERS = _deployment.USERS
