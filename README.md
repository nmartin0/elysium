# Elysium

Elysium answers questions, and with permission makes changes, against an
organization's data. It sits between a language model and the real
databases: the data is described once as an **ontology** of objects,
fields and links, and every read and write goes through server code that
checks who is asking.

The model never gets direct database access. One server instance runs
one organization's data.

## The ideas

- **Objects and links.** Typed things (a customer, an expense report)
  and the relations between them, declared in YAML, read from your
  databases where they live.
- **Actions.** The only way anything is written: named, typed,
  independently governed operations.
- **Object sets.** A query is a first-class thing you can name, save
  and export; what a reader sees is what the set holds for them.
- **One place that decides.** Access to every read and write is decided
  by plain server code, never by the model, and checked again when a
  change is approved.
- **Proposals.** A write is proposed first and takes effect only when an
  approver, re-checked at that moment, accepts it.
- **The server decides, the browser renders.** The web UI is a thin
  client of the HTTP API.

## Status

Pre-1.0 and under active refactor. There are no deployments, so nothing
is kept for compatibility: formats change in place. See
[the limitations](docs/limitations.md) and [the roadmap](docs/roadmap.md).

## Try it in development

You need Python 3.12 or later, Node.js (see `ui/package.json`), and
[Ollama](https://ollama.com) for the model. The first run uses the
example deployment in `deployment/`.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e .
export ELYSIUM_CONFIG_DIR=deployment/etc ELYSIUM_DATA_DIR=deployment/var/lib ELYSIUM_LOG_DIR=deployment/var/log
python -m elysium.scripts.bootstrap_root          # creates the first account
uvicorn elysium.api.app:app --reload              # the API, terminal 1
cd ui && npm ci && npm run dev                    # the browser UI, terminal 2
```

Restart `uvicorn` after changing anything under `src/elysium/api/` or
`src/elysium/core/`. Pulling a model and the rest of the setup are in
[the install guide](docs/install.md).

## Where to read next

- [docs/install.md](docs/install.md): requirements, install, running, tests
- [docs/architecture.md](docs/architecture.md): how it is organized
- [docs/configuration.md](docs/configuration.md): the deployment YAML files
- [docs/roadmap.md](docs/roadmap.md): what is planned and in what order
- [docs/principles.md](docs/principles.md): why the design is the way it is
- [docs/security/architecture.md](docs/security/architecture.md): the security model as built
- [docs/README.md](docs/README.md): the index of all documents
- [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md): how to work in this repository

## Licence

Proprietary, all rights reserved; see [LICENSE](LICENSE).
