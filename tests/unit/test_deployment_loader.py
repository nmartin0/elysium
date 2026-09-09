from core.deployment_loader import resolve_runtime_paths


def test_secrets_dir_is_created_private(tmp_path, monkeypatch):
    """0700, and enforced on EVERY startup rather than only at creation.

    Creating it correctly once is not enough: a restore from backup, an
    unpacked archive or a careless chmod leaves it readable, and that
    failure is silent -- nothing breaks, the secrets are just exposed.
    """
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(tmp_path / "etc"))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(tmp_path / "log"))

    paths = resolve_runtime_paths()

    assert paths.secrets_dir.is_dir()
    assert paths.secrets_dir.stat().st_mode & 0o777 == 0o700


def test_secrets_dir_permissions_are_repaired_on_startup(tmp_path, monkeypatch):
    # The case the enforcement exists for.
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(tmp_path / "etc"))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(tmp_path / "log"))
    resolve_runtime_paths().secrets_dir.chmod(0o755)

    paths = resolve_runtime_paths()

    assert paths.secrets_dir.stat().st_mode & 0o777 == 0o700


def test_secrets_dir_sits_under_data_not_config(tmp_path, monkeypatch):
    """A secret is STATE the application produces, not configuration an
    operator supplies -- so it belongs with the databases.

    It is derived rather than a fourth environment variable: giving it
    its own would invite pointing it somewhere world-readable.
    """
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(tmp_path / "etc"))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(tmp_path / "log"))

    paths = resolve_runtime_paths()

    assert paths.secrets_dir.parent == paths.data_dir
