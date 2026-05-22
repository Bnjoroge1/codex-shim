from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

try:
    import tomli_w
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "codex-shim requires 'tomli_w' for TOML config management. "
        "Install it: pip install tomli_w"
    ) from exc


_SHIM_TOP_LEVEL_KEYS = {"model", "model_provider", "model_catalog_json"}
_SHIM_PROVIDER_TABLE = "vibeproxy_shim"
_DEFAULT_NATIVE_MODEL = "gpt-5.5"


class CodexConfig:
    """Structured manipulation of the user's ~/.codex/config.toml."""

    def __init__(self, path: Path, backup_path: Path | None = None) -> None:
        self.path = path
        self.backup_path = backup_path

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def read_active_model(self) -> str | None:
        """Return the current top-level *model* value, or None."""
        data = self._load()
        if data is None:
            return None
        value = data.get("model")
        return str(value).strip('"') if value is not None else None

    def is_shim_enabled(self) -> bool:
        """Return True when the active top-level config routes through the shim."""
        data = self._load()
        if data is None:
            return False
        providers = data.get("model_providers")
        return (
            data.get("model_provider") == _SHIM_PROVIDER_TABLE
            or data.get("model_catalog_json") is not None
            or isinstance(providers, dict) and _SHIM_PROVIDER_TABLE in providers
        )

    def install_shim(
        self,
        default_slug: str,
        base_url: str,
        catalog_path: Path,
        provider_name: str | None = None,
    ) -> None:
        """Write shim-managed keys into the config, backing up first."""
        self._maybe_backup()
        data = self._load()
        if data is None:
            print(
                f"Warning: skipping shim install because {self.path} is not valid TOML.",
                file=sys.stderr,
            )
            return
        data = self._remove_shim_data(data)
        data["model"] = default_slug
        data["model_provider"] = "vibeproxy_shim"
        data["model_catalog_json"] = str(catalog_path)
        providers = data.setdefault("model_providers", {})
        providers[_SHIM_PROVIDER_TABLE] = {
            "name": provider_name or default_slug,
            "base_url": base_url,
            "wire_api": "responses",
            "experimental_bearer_token": "dummy",
            "request_max_retries": 3,
            "stream_max_retries": 3,
            "stream_idle_timeout_ms": 600_000,
        }
        self._save(data)
        print(f"Installed shim config into {self.path}.")
        if self.backup_path is not None and self.backup_path.exists():
            print(f"Original backup: {self.backup_path}")

    def remove_shim(self) -> None:
        """Restore backup if present, otherwise strip shim keys from config."""
        if self.backup_path is not None and self.backup_path.exists():
            self.path.write_text(self.backup_path.read_text())
            self.backup_path.unlink()
            print(f"Restored original {self.path}.")
            return

        data = self._load()
        if data is None:
            print(
                f"Warning: skipping shim removal because {self.path} is not valid TOML.",
                file=sys.stderr,
            )
            return

        data = self._remove_shim_data(data)
        self._save(data)
        print(f"Removed shim config from {self.path}.")

    def disable_shim(self, fallback_model: str = _DEFAULT_NATIVE_MODEL) -> None:
        """Disable shim routing without restoring an old full-file backup."""
        data = self._load()
        if data is None:
            print(
                f"Warning: skipping shim disable because {self.path} is not valid TOML.",
                file=sys.stderr,
            )
            return

        data = self._remove_shim_data(data)
        data["model"] = fallback_model
        self._save(data)
        print(f"Disabled shim config in {self.path}.")

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def _maybe_backup(self) -> None:
        if self.backup_path is None or self.backup_path.exists():
            return
        if self.path.exists():
            self.backup_path.write_text(self.path.read_text())

    def _load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            print(f"Warning: failed to parse {self.path}: {exc}", file=sys.stderr)
            return None

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as f:
            tomli_w.dump(data, f)

    def _remove_shim_data(self, data: dict[str, Any]) -> dict[str, Any]:
        for key in _SHIM_TOP_LEVEL_KEYS:
            data.pop(key, None)
        providers = data.get("model_providers")
        if isinstance(providers, dict):
            providers.pop(_SHIM_PROVIDER_TABLE, None)
            if not providers:
                data.pop("model_providers")
        return data
