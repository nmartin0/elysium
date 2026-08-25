# Configuration templates

Copy these into `deployment/etc/` (or `/etc/elysium/` for a real
install) and edit them for your organization. See the main project
README's "Configuring your organization's deployment" section for the
full explanation of each field -- these files use the SAME illustrative
`Employee`/`ExpenseReport` example that section walks through, so the
two stay consistent with each other rather than telling two different
stories.

- `config.yaml` -- operational settings (LLM backend, agent tuning, data silos, tools)
- `ontology_schema.yaml` -- what data exists and how it's structured
- `policy.yaml` -- who your users are, and exactly what they can do (MAC + fully-explicit RBAC)
- `example_queries.yaml` -- optional demo queries for `scripts/run_deployment.py`

Every YAML file below is real, valid, and would work if copied in as-is
-- it's a genuinely runnable minimal example, not just illustrative
prose, so you can confirm the whole pipeline works before replacing the
example content with your own.
