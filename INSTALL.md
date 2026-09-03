# Installing and running Elysium

Setup, running it locally, running the test suites, code quality
tooling, and a real production install — in that order. See
`README.md` for the architecture, the security model, and how to
configure it for your own organization; this file is purely
operational.

---

## 1. Prerequisites

- **Python 3.10 or later**
- **Node.js 22.22.2 or later (22.x, 24.15.0+, or 26+)** for the `ui/` frontend -- see `ui/package.json`'s own `engines` field for the exact, binding constraint (driven by `jsdom`'s own requirement). If you use `nvm`, `ui/.nvmrc` picks the right version automatically (`nvm use`, from inside `ui/`).
- **[Ollama](https://ollama.com)** installed and running locally
- Enough free RAM for whatever model you choose to run

---

## 2. Installation (local development)

```bash
git clone <your-repo-url>
cd <repo-directory>

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1

pip install -r requirements.txt

cd ui && npm install && cd ..
```

For a real, running production install, see section 7 instead.

---

## 3. Setting up Ollama

```bash
ollama pull phi4-mini      # example: step-selection model
ollama pull qwen2.5:3b     # example: answer-synthesis model
```

Smaller, "reasoning-flavored" models have generally worked better for
step-selection than larger general-purpose ones — this is genuinely
trial-and-error; try a model, run the test suite, see how it does.

---

## 4. Running the included example

```bash
python3 -m scripts.run_deployment
```

No arguments — config, data, and logs are all resolved automatically.
Runs a few example questions through the full pipeline and prints the
answers.

---

## 5. Running the tests

```bash
# Fast -- no LLM, no network, run these constantly while developing
python3 -m pytest tests/unit/ -v

# Slow -- real LLM calls against tests/integration/'s own isolated fixture
python3 -m pytest tests/integration/ -v -m integration

# api/ layer -- real FastAPI TestClient, mocked LLM, no Ollama needed
python3 -m pytest tests/integration/test_api.py -v
```

The `ui/` frontend has its own, separate suite — real user flows
through React Testing Library (typing, clicking, waiting for a real
async response), not shallow rendering:

```bash
cd ui && npm test
```

---

## 6. Code quality: linting, type checking, dead code, import boundaries

```bash
pip install -r requirements.txt -r requirements-dev.txt

./lint.sh
```

Four separate tools, each catching something genuinely different — see
`lint.sh`'s own top comment for why each one earns its place, and
`pyproject.toml`'s `[tool.ruff.lint]`, `[tool.mypy]`, and
`[tool.importlinter]` sections for the specific configuration and
reasoning behind each. In short: Ruff (style, real Python gotchas,
import order), MyPy (does the types agree), Vulture (does anything
still use this), Import Linter (is this module even allowed to import
that one — the real, current architectural contracts live in
`pyproject.toml`'s own `[tool.importlinter]` section, mapped directly
against this project's real import graph, not designed from
assumption).

`ruff format` is intentionally never run by `./lint.sh` or anywhere
else — see `pyproject.toml`'s own `[tool.ruff]` section for why.

The `ui/` frontend has its own, separate tooling — a real, standing
`tsc --noEmit` type check (not optional or best-effort; TypeScript
throughout, `strict: true`), style/correctness (`oxlint`), dead-code
detection for files/exports/dependencies (`knip`), and formatting
(`oxfmt`):

```bash
cd ui
npm run lint          # oxlint, then tsc --noEmit
npm run knip
npm run format:check  # verify without changing anything
```

See `ui/README.md`'s own "Testing, linting, and type checking" section
for the full breakdown, and `ui/tsconfig.json`'s own comments for the
specific compiler options chosen and why.

---

## 7. Installing as a real, running service

`install/install.sh` (run as root, from a checked-out copy of this
repository) sets up a genuine production install:

- A dedicated **system user and group** (`elysium`), no login shell —
  the service runs unprivileged, under its own identity, never as the
  human who ran the install.
- The **FHS layout** — `/opt/elysium` (code + venv), `/etc/elysium`
  (config), `/var/lib/elysium` (data — `700` permissions, no group
  access at all, since this is where `credentials.db` lives),
  `/var/log/elysium` (logs).
- A **systemd service** (`install/elysium.service`) running
  `uvicorn api.app:app` under the `elysium` user, bound to
  `127.0.0.1` by default.
- **Root bootstrap** — a real, cryptographically random password,
  generated once, printed once (never a hardcoded default).

```bash
sudo ./install/install.sh
sudo systemctl start elysium.service
```

### Where this deviates from POSIX, explicitly

This install script's **shell syntax** is POSIX `sh` throughout, but
several **commands** it calls are Linux-specific, with no POSIX
equivalent: **systemd** (not part of POSIX at all), **the FHS layout
itself** (a Linux Foundation convention, not POSIX-mandated),
**`useradd`/`groupadd`/`getent`** (from `shadow-utils`/glibc, not
POSIX-specified), and **`$SUDO_USER`** (`sudo`-specific).
