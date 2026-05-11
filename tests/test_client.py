"""Integration-style tests for HomeboxClient using respx to mock httpx."""

from __future__ import annotations

import httpx
import pytest
import respx

from homebox_mcp.client import HomeboxAuthError, HomeboxClient

BASE = "https://homebox.test"


@pytest.fixture
def client() -> HomeboxClient:
    return HomeboxClient(BASE, "u@example.com", "secret")


@respx.mock
async def test_login_succeeds_on_first_call(client: HomeboxClient) -> None:
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "abc123"}))
    respx.get(f"{BASE}/api/v1/labels").mock(return_value=httpx.Response(200, json=[]))

    result = await client.get("/api/v1/labels")
    assert result == []
    await client.close()


@respx.mock
async def test_login_failure_raises_auth_error(client: HomeboxClient) -> None:
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(401, text="bad password"))
    with pytest.raises(HomeboxAuthError):
        await client.get("/api/v1/labels")
    await client.close()


@respx.mock
async def test_401_triggers_relogin_and_retry(client: HomeboxClient) -> None:
    login_route = respx.post(f"{BASE}/api/v1/users/login").mock(
        side_effect=[
            httpx.Response(200, json={"token": "first"}),
            httpx.Response(200, json={"token": "second"}),
        ]
    )
    # First request 401, second succeeds.
    respx.get(f"{BASE}/api/v1/items").mock(
        side_effect=[
            httpx.Response(401, text="token expired"),
            httpx.Response(200, json={"items": []}),
        ]
    )
    result = await client.get("/api/v1/items")
    assert result == {"items": []}
    assert login_route.call_count == 2
    await client.close()


@respx.mock
async def test_put_item_normalizes_body(client: HomeboxClient) -> None:
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "tok"}))
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "deadbeef-...", "name": "Foo"})

    respx.put(f"{BASE}/api/v1/items/deadbeef").mock(side_effect=_capture)

    await client.put_item(
        "deadbeef",
        {
            "name": "Foo",
            "purchaseTime": "2026-05-10T18:47:00Z",  # → 2026-05-10
            "soldTime": "0001-01-01T00:00:00Z",  # → ""
            "tags": [  # → labelIds
                "11111111-1111-1111-1111-111111111111",
            ],
        },
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["purchaseTime"] == "2026-05-10"
    assert body["soldTime"] == ""
    assert body["labelIds"] == ["11111111-1111-1111-1111-111111111111"]
    assert "tags" not in body
    await client.close()


@respx.mock
async def test_get_bytes_returns_content_and_type(client: HomeboxClient) -> None:
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "tok"}))
    respx.get(f"{BASE}/api/v1/qrcode").mock(
        return_value=httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            headers={"content-type": "image/png"},
        )
    )
    content, ct = await client.get_bytes("/api/v1/qrcode", params={"data": "hello"})
    assert content.startswith(b"\x89PNG")
    assert ct == "image/png"
    await client.close()
