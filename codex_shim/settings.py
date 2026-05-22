from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any
from urllib.request import urlopen


PROVIDER_NAME = "vibeproxy_shim"
VIBEPROXY_URL = "http://127.0.0.1:8318"
VIBEPROXY_API_URL = "http://127.0.0.1:8317"


_ACRONYMS = {"gpt", "ai", "api", "cli", "url", "http", "https", "json", "yaml", "sql", "css", "html", "js", "ts", "xml", "svg", "pdf", "png", "jpg", "jpeg", "gif", "webp", "mp3", "mp4", "wasm", "cpu", "gpu", "ram", "ssd", "ssh", "dns", "tcp", "udp", "ip", "id", "uuid", "jwt", "oauth", "saml", "sso", "ldap", "gpu", "tpu", "npu", "llm", "rlhf", "rag"}


def _title_case(value: str) -> str:
    """Title-case with small-word handling and known-acronym uppercasing."""
    small = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", "via", "in", "of"}
    words = value.split()
    if not words:
        return value
    result = []
    for i, w in enumerate(words):
        lower = w.lower()
        if lower in _ACRONYMS:
            result.append(lower.upper())
        elif lower in small and i != 0 and i != len(words) - 1:
            result.append(lower)
        else:
            result.append(w.capitalize())
    return " ".join(result)


@dataclass(frozen=True)
class VibeProxyModel:
    slug: str
    model: str
    display_name: str
    owned_by: str
    index: int = 0


class VibeProxySettings:
    def __init__(self, base_url: str = VIBEPROXY_URL):
        self.base_url = base_url.rstrip("/")

    def _fetch(self) -> dict[str, Any]:
        try:
            with urlopen(f"{self.base_url}/v1/models", timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch models from VibeProxy at {self.base_url}: {exc}"
            ) from exc

    def load(self) -> list[VibeProxyModel]:
        data = self._fetch()
        return self._parse(data)

    async def aload(self) -> list[VibeProxyModel]:
        data = await asyncio.to_thread(self._fetch)
        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> list[VibeProxyModel]:
        rows = data.get("data", [])
        models: list[VibeProxyModel] = []

        for idx, row in enumerate(rows):
            model_id = str(row.get("id") or "").strip()
            if not model_id:
                continue
            # Skip non-chat / non-coding models
            lower_id = model_id.lower()
            if any(x in lower_id for x in ("image", "embedding", "tts", "whisper", "dall")):
                continue

            owned_by = str(row.get("owned_by") or "unknown").strip()
            display_name = _title_case(model_id.replace("-", " "))
            if owned_by and owned_by.lower() not in ("openai", "unknown"):
                display_name = f"{display_name} ({owned_by})"

            models.append(
                VibeProxyModel(
                    slug=model_id,
                    model=model_id,
                    display_name=display_name,
                    owned_by=owned_by,
                    index=idx,
                )
            )
        return models


def default_model_slug(models: list[VibeProxyModel]) -> str:
    if not models:
        return "gpt-5.5"
    for m in models:
        if m.model == "gpt-5.5":
            return m.slug
    return models[0].slug
