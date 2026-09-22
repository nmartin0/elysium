"""
Importing api.app builds nothing; asking for api.app.app builds it once.

E-08c. The module's last line was `app = create_app()`, so IMPORTING it
-- as every integration test does, for create_app -- started a whole
application against the default deployment: credentials.db,
write_log.db, metrics.db, config_history.db and a mirror appeared in the
developer's data directory. Measured on a fresh clone, from the import
alone.

Each check runs in a SUBPROCESS: a module is imported once per process,
so only a fresh interpreter can show what importing does.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _python(code: str, deployment: Path) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "ELYSIUM_DATA_DIR": str(deployment / "data"),
           "ELYSIUM_LOG_DIR": str(deployment / "log")}
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def test_importing_the_module_creates_nothing(tmp_path):
    (tmp_path / "data").mkdir()

    result = _python("import api.app", tmp_path)

    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "data").iterdir()) == []


def test_importing_create_app_creates_nothing(tmp_path):
    """WHAT THE INTEGRATION TESTS ACTUALLY DO."""
    (tmp_path / "data").mkdir()

    result = _python("from api.app import create_app", tmp_path)

    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "data").iterdir()) == []


def test_asking_for_the_app_builds_it_once(tmp_path):
    result = _python(
        "import api.app\n"
        "from fastapi import FastAPI\n"
        "first = api.app.app\n"
        "assert isinstance(first, FastAPI), type(first)\n"
        "assert api.app.app is first\n"
        "print('ok')\n",
        tmp_path,
    )

    assert result.stdout.strip() == "ok", result.stderr


def test_uvicorn_finds_it_by_name(tmp_path):
    """`uvicorn api.app:app` resolves the attribute through its own
    importer -- the exact path a real start takes."""
    result = _python(
        "from fastapi import FastAPI\n"
        "from uvicorn.importer import import_from_string\n"
        "assert isinstance(import_from_string('api.app:app'), FastAPI)\n"
        "print('ok')\n",
        tmp_path,
    )

    assert result.stdout.strip() == "ok", result.stderr


def test_an_unknown_attribute_is_refused_not_built(tmp_path):
    (tmp_path / "data").mkdir()

    result = _python(
        "import api.app\n"
        "try:\n"
        "    api.app.nothing_here\n"
        "except AttributeError:\n"
        "    print('refused')\n",
        tmp_path,
    )

    assert result.stdout.strip() == "refused", result.stderr
    assert list((tmp_path / "data").iterdir()) == []
