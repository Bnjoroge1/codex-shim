from __future__ import annotations

import json
from pathlib import Path
import tomllib

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from codex_shim.catalog import catalog_entry, write_config
from codex_shim.settings import VibeProxySettings


def test_catalog_preserves_context_and_visibility():
    model = VibeProxyModelFixture.one()
    entry = catalog_entry(model)
    assert entry["slug"] == "gpt-5.5"
    assert entry["visibility"] == "list"
    assert entry["context_window"] == 400000
    assert "free" in entry["available_in_plans"]


def test_kimi_gets_context():
    model = VibeProxyModelFixture.kimi()
    entry = catalog_entry(model)
    assert entry["context_window"] == 256000


def test_write_config_outputs_valid_toml(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    catalog_path = tmp_path / "catalog.json"

    write_config(
        [VibeProxyModelFixture.one()],
        config_path,
        catalog_path,
        "http://localhost:8317/v1",
        provider_name="gpt-5.5",
    )

    data = tomllib.loads(config_path.read_text())
    assert data["model"] == "gpt-5.5"
    assert data["model_providers"]["vibeproxy_shim"]["name"] == "gpt-5.5"


async def test_fetch_models_from_vibeproxy():
    async def models(request):
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {"id": "gpt-5.5", "object": "model", "created": 1, "owned_by": "openai"},
                    {"id": "kimi-k2", "object": "model", "created": 2, "owned_by": "moonshot"},
                ],
            }
        )

    app = web.Application()
    app.router.add_get("/v1/models", models)
    client = TestClient(TestServer(app))
    await client.start_server()

    settings = VibeProxySettings(str(client.make_url("")))
    models_list = await settings.aload()
    assert [m.model for m in models_list] == ["gpt-5.5", "kimi-k2"]
    assert models_list[0].slug == "gpt-5.5"

    await client.close()


class VibeProxyModelFixture:
    @staticmethod
    def one():
        from codex_shim.settings import VibeProxyModel

        return VibeProxyModel(
            slug="gpt-5.5",
            model="gpt-5.5",
            display_name="GPT-5.5",
            owned_by="openai",
            index=0,
        )

    @staticmethod
    def kimi():
        from codex_shim.settings import VibeProxyModel

        return VibeProxyModel(
            slug="kimi-k2",
            model="kimi-k2",
            display_name="Kimi K2 (moonshot)",
            owned_by="moonshot",
            index=1,
        )
