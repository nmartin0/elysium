"""
config.py  (generic YAML loading -- org-agnostic)

The ONLY thing this file knows how to do is read a YAML file into a
plain Python dict. It has no idea what the contents mean -- no concept
of "users", "schema", or "model names". That interpretation happens
wherever this is called from.

SECURITY: always yaml.safe_load(), never yaml.load(). Plain load() can
execute arbitrary Python via YAML tags if the file is ever untrusted --
safe_load() only ever produces plain data structures.

Called by: deployments/<org>/deployment.py (the one place config gets
           read and turned into explicit parameters for core/ functions)
"""

from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
