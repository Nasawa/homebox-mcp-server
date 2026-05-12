"""Test that create_item auto-follows POST with PUT for extras.

Homebox v0.25's POST /api/v1/items endpoint only accepts {name, description,
locationId, labelIds}. All other fields are silently dropped. create_item
should detect non-default extras and follow up with a PUT so callers see the
final state.
"""

from __future__ import annotations

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
async def test_create_item_minimal_no_extras_no_followup_put(client: HomeboxClient) -> None:
    """With no extras, only the POST should fire — no PUT, no GET-for-merge."""
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "t"}))
    post_route = respx.post(f"{BASE}/api/v1/items").mock(
        return_value=httpx.Response(201, json={"id": "abc", "name": "MinimalItem", "purchasePrice": 0}),
    )
    put_route = respx.put(f"{BASE}/api/v1/items/abc")

    item = await server.create_item(name="MinimalItem", location_id="loc-1")

    assert post_route.called
    assert not put_route.called
    assert item["id"] == "abc"
    await client.close()


@respx.mock
async def test_create_item_with_extras_triggers_followup_put(client: HomeboxClient) -> None:
    """Manufacturer/notes/purchasePrice are non-default → PUT should fire."""
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "t"}))
    respx.post(f"{BASE}/api/v1/items").mock(
        return_value=httpx.Response(201, json={"id": "xyz", "name": "Razer", "purchasePrice": 0}),
    )
    # update_item does a GET-for-merge first, then PUT.
    respx.get(f"{BASE}/api/v1/items/xyz").mock(
        return_value=httpx.Response(200, json={
            "id": "xyz", "name": "Razer", "purchasePrice": 0, "manufacturer": "",
            "location": {"id": "loc-1"}, "labels": [],
        }),
    )
    put_route = respx.put(f"{BASE}/api/v1/items/xyz").mock(
        return_value=httpx.Response(200, json={
            "id": "xyz", "name": "Razer", "purchasePrice": 34.99,
            "manufacturer": "Razer", "modelNumber": "Basilisk V3",
            "notes": "amazon-asin: B09C13PZX7",
            "purchaseTime": "2026-05-01",
        }),
    )

    item = await server.create_item(
        name="Razer",
        location_id="loc-1",
        manufacturer="Razer",
        model_number="Basilisk V3",
        purchase_price=34.99,
        purchase_time="2026-05-01",
        notes="amazon-asin: B09C13PZX7",
    )

    assert put_route.called
    # Verify the PUT body had the extras
    put_body = put_route.calls[0].request.read().decode()
    assert "Razer" in put_body
    assert "Basilisk V3" in put_body
    assert "34.99" in put_body
    assert "B09C13PZX7" in put_body
    # Returned item should reflect post-update state
    assert item["purchasePrice"] == 34.99
    assert item["manufacturer"] == "Razer"
    await client.close()


@respx.mock
async def test_create_item_label_ids_go_on_post_not_put(client: HomeboxClient) -> None:
    """labelIds is a CREATE-accepted field, so it shouldn't trigger a follow-up PUT."""
    respx.post(f"{BASE}/api/v1/users/login").mock(return_value=httpx.Response(200, json={"token": "t"}))
    post_route = respx.post(f"{BASE}/api/v1/items").mock(
        return_value=httpx.Response(201, json={"id": "lbl", "name": "Tagged", "labels": [{"id": "L1"}]}),
    )
    put_route = respx.put(f"{BASE}/api/v1/items/lbl")

    await server.create_item(name="Tagged", location_id="loc-1", label_ids=["L1"])

    assert post_route.called
    post_body = post_route.calls[0].request.read().decode()
    assert '"tagIds":["L1"]' in post_body
    assert not put_route.called
    await client.close()
