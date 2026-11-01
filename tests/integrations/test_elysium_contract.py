# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""Heliograph's server keeps Elysium's add-on contract, as checked by Elysium's own
contract checks (a copy beside this file; see its PROVENANCE note)."""

import tempfile
from pathlib import Path

from tests.integrations.elysium_addon_checks import AddonContract

HERE = Path(__file__).resolve().parent

_DATA = tempfile.mkdtemp(prefix="heliograph-contract-")


class TestHeliographKeepsTheAddonContract(AddonContract):
    manifest = HERE.parents[1] / "integrations" / "elysium" / "module.json"
    protected = ["/api/backtests"]  # noqa: RUF012
    permissions = ["module:heliograph:use"]  # noqa: RUF012
    options = {"data": f"{_DATA}/data"}  # noqa: RUF012
