from __future__ import annotations

import pytest
from pathlib import Path

from codex_shim.config import CodexConfig


@pytest.fixture
def config_pair(tmp_path: Path):
    """Return a (config_path, backup_path) pair."""
    config = tmp_path / "config.toml"
    backup = tmp_path / "config.toml.backup"
    return config, backup


class TestReadActiveModel:
    def test_returns_model_when_present(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('model = "gpt-4"\n')
        cc = CodexConfig(config_path, backup_path)
        assert cc.read_active_model() == "gpt-4"

    def test_returns_none_when_missing(self, config_pair):
        config_path, backup_path = config_pair
        cc = CodexConfig(config_path, backup_path)
        assert cc.read_active_model() is None

    def test_returns_none_for_invalid_toml(self, config_pair, capsys):
        config_path, backup_path = config_pair
        config_path.write_text("model = [broken\n")
        cc = CodexConfig(config_path, backup_path)
        assert cc.read_active_model() is None
        captured = capsys.readouterr()
        assert "failed to parse" in captured.err


class TestInstallShim:
    def test_installs_shim_keys(self, config_pair):
        config_path, backup_path = config_pair
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        text = config_path.read_text()
        assert 'model = "gpt-5.5"' in text
        assert 'model_provider = "vibeproxy_shim"' in text
        assert "[model_providers.vibeproxy_shim]" in text
        assert 'name = "gpt-5.5"' in text

    def test_installs_custom_provider_name(self, config_pair):
        config_path, backup_path = config_pair
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json", provider_name="CustomName")

        text = config_path.read_text()
        assert 'name = "CustomName"' in text

    def test_creates_backup(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('model = "gpt-4"\n[model_providers.openai]\nname = "OpenAI"\n')
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        assert backup_path.exists()
        assert 'model = "gpt-4"' in backup_path.read_text()

    def test_reinstall_replaces_old_shim(self, config_pair):
        config_path, backup_path = config_pair
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")
        cc.install_shim("kimi-k2", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        text = config_path.read_text()
        assert 'model = "kimi-k2"' in text
        assert 'model = "gpt-5.5"' not in text

    def test_preserves_other_providers(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('[model_providers.openai]\nname = "OpenAI"\n')
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        text = config_path.read_text()
        assert "[model_providers.openai]" in text
        assert "[model_providers.vibeproxy_shim]" in text

    def test_skips_invalid_toml(self, config_pair, capsys):
        config_path, backup_path = config_pair
        config_path.write_text("invalid [ toml\n")
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        # Should not have overwritten with shim config
        text = config_path.read_text()
        assert "vibeproxy_shim" not in text
        captured = capsys.readouterr()
        assert "not valid TOML" in captured.err

    def test_detects_enabled_shim(self, config_pair):
        config_path, backup_path = config_pair
        cc = CodexConfig(config_path, backup_path)
        assert cc.is_shim_enabled() is False

        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        assert cc.is_shim_enabled() is True


class TestRemoveShim:
    def test_restores_backup(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('model = "gpt-4"\n')
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")

        cc2 = CodexConfig(config_path, backup_path)
        cc2.remove_shim()

        assert not backup_path.exists()
        text = config_path.read_text()
        assert 'model = "gpt-4"' in text
        assert "vibeproxy_shim" not in text

    def test_removes_shim_without_backup(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('theme = "dark"\n')  # ensure backup is created
        cc = CodexConfig(config_path, backup_path)
        cc.install_shim("gpt-5.5", "http://localhost:8317/v1", config_path.parent / "catalog.json")
        backup_path.unlink(missing_ok=True)  # delete backup

        cc2 = CodexConfig(config_path, backup_path)
        cc2.remove_shim()

        text = config_path.read_text()
        assert "vibeproxy_shim" not in text
        assert 'model = "gpt-5.5"' not in text

    def test_preserves_other_keys_when_no_backup(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('theme = "dark"\nmodel = "gpt-5.5"\nmodel_provider = "vibeproxy_shim"\n')
        cc = CodexConfig(config_path, backup_path)
        cc.remove_shim()

        text = config_path.read_text()
        assert 'theme = "dark"' in text
        assert "vibeproxy_shim" not in text
        assert 'model = "gpt-5.5"' not in text

    def test_disable_shim_preserves_other_settings(self, config_pair):
        config_path, backup_path = config_pair
        config_path.write_text('theme = "dark"\nmodel = "gpt-5.3-codex"\nmodel_provider = "vibeproxy_shim"\nmodel_catalog_json = "/tmp/catalog.json"\n[model_providers.vibeproxy_shim]\nname = "VibeProxy"\n')
        cc = CodexConfig(config_path, backup_path)

        cc.disable_shim()

        text = config_path.read_text()
        assert 'theme = "dark"' in text
        assert 'model = "gpt-5.5"' in text
        assert "vibeproxy_shim" not in text
        assert "model_catalog_json" not in text
