"""The control panel's server keeps Elysium's add-on contract (BLOCKING.md
item 3, step 2): checked by Elysium's own contract checks, which the
panel carries a copy of (panel/elysium_addon_checks.py) as an add-on in
its own repository would -- the simulator imports nothing of Elysium's.
No world is started: the contract is the server's."""

import sys
import tempfile
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1] / "panel"
sys.path.insert(0, str(PANEL))

from elysium_addon_checks import AddonContract  # noqa: E402

_WORLDS = tempfile.mkdtemp(prefix="panel-contract-")


class TestThePanelKeepsTheAddonContract(AddonContract):
    manifest = PANEL / "module.json"
    protected = ["/state"]
    options = {"directory": f"{_WORLDS}/world"}
