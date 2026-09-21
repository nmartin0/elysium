"""
There is one systemd unit, the installer installs it, and it is hardened.

WHY THIS EXISTS. There were two units: install/elysium.service, which
install.sh installs, and deployment/systemd/elysium.service, which held
every least-privilege setting and was installed by NOTHING -- a later
commit wrote a second unit instead of updating the first. A real install
ran unhardened, and the log rotation beside it was never installed
either. The backup inventory's failure (patch 281) again: two copies of
one thing, and nothing comparing them to what is actually used.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
UNIT = ROOT / "install" / "elysium.service"
INSTALLER = (ROOT / "install" / "install.sh").read_text()
SKIP = {".git", "node_modules", ".venv", "venv"}


def _directives():
    values = {}
    for line in UNIT.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, _, value = line.partition("=")
            values.setdefault(key, []).append(value)
    return values


def test_there_is_exactly_one_unit():
    units = [p for p in ROOT.rglob("*.service") if not SKIP & set(p.parts)]

    assert units == [UNIT], f"a second unit drifts from the first: {units}"


def test_the_installer_installs_it():
    assert 'cp "$SOURCE_DIR/install/elysium.service"' in INSTALLER


def test_it_is_hardened():
    """THE SETTINGS THAT WERE INSTALLED BY NOTHING."""
    d = _directives()
    for key, value in {
        "NoNewPrivileges": "true",
        "ProtectSystem": "strict",
        "ProtectHome": "true",
        "PrivateTmp": "true",
        "PrivateDevices": "true",
    }.items():
        assert d.get(key) == [value], f"{key} should be {value}"
    assert "RestrictAddressFamilies" in d


def test_it_can_write_where_it_is_told_to_keep_things():
    """PROTECTSYSTEM=STRICT MAKES EVERYTHING READ-ONLY BUT READWRITEPATHS.
    Move the data directory and forget this line, and the application
    cannot write -- with nothing else to notice."""
    d = _directives()
    env = dict(e.split("=", 1) for e in d["Environment"])
    writable = d["ReadWritePaths"][0].split()

    assert env["ELYSIUM_DATA_DIR"] in writable
    assert env["ELYSIUM_LOG_DIR"] in writable


def test_uvicorn_ends_the_process_before_systemd_kills_it():
    """MEASURED: uvicorn waits for requests in flight, and at its timeout
    ends the process itself. systemd's stop timeout must be LONGER, or
    SIGKILL cuts whatever uvicorn was still waiting on."""
    d = _directives()
    graceful = re.search(r"--timeout-graceful-shutdown (\d+)", d["ExecStart"][0])
    assert graceful, "uvicorn needs a graceful-shutdown timeout"

    assert int(d["TimeoutStopSec"][0]) > int(graceful.group(1))


def test_the_installer_installs_log_rotation_that_exists():
    """WITHOUT IT THE AUDIT LOG FILLS THE DISK, and then writes fail
    while reads keep working."""
    match = re.search(r'cp "\$SOURCE_DIR/(\S+)" /etc/logrotate\.d/elysium', INSTALLER)
    assert match, "install.sh must install the logrotate config"

    assert (ROOT / match.group(1)).is_file()
