"""Route-level tests for Homebox MCP tools."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from homebox_mcp import server
from homebox_mcp.client import HomeboxClient

BASE = "https://homebox.test"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> HomeboxClient:
    c = HomeboxClient(BASE, "u@example.com", "secret")
    monkeypatch.setattr(server, "_get_client", lambda: c)
    return c


@respx.mock
async def test_create_external_attachment_uses_entity_route(client: HomeboxClient) -> None:
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "t"}))
    route = respx.post(f"{BASE}/api/v1/entities/entity-1/attachments/external").mock(
        return_value=httpx.Response(201, json={"id": "entity-1", "attachments": []})
    )

    result = await server.create_external_attachment(
        item_id="entity-1",
        external_id="https://docs.example/receipt.pdf",
        source_type="url",
        title="Receipt",
        attachment_type="receipt",
    )

    assert result["id"] == "entity-1"
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "external_id": "https://docs.example/receipt.pdf",
        "source_type": "url",
        "title": "Receipt",
        "attachment_type": "receipt",
    }
    await client.close()
