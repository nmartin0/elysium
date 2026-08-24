"""
deployment.py  (acme_corp-specific -- supplies this org's own path, nothing else)

All the actual loading logic lives in core/deployment_loader.py, which is
fully generic. This file's only job is to say WHERE acme_corp's config
files live.

Exposes a single object, `config` -- a DeploymentConfig instance with
every setting as a typed field (config.step_model, config.schema, etc.)
-- instead of manually re-listing each field here, which used to mean
keeping two files in sync by hand every time a setting was added.
"""

from pathlib import Path

from core.deployment_loader import load_deployment

config = load_deployment(Path(__file__).resolve().parent)
