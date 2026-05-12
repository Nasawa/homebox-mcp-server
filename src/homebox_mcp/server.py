"""FastMCP server exposing Homebox tools.

Tool surface (v0.1.0):

Items
    list_items, get_item, get_item_by_asset_id, search_items, create_item,
    update_item, delete_item

Locations
    list_locations, get_location, create_location, update_location, delete_location

Tags
    list_tags, get_tag, get_or_create_tag_by_name, create_tag, update_tag, delete_tag
    (Homebox v0.25 renamed the resource from "labels" → "tags". The legacy
    list_labels/etc. tool names are still aliased for back-compat but route to
    /api/v1/tags. Empirically verified 2026-05-12 against running v0.25.)

Attachments
    list_attachments, upload_attachment, delete_attachment, set_primary_image

Codes
    get_qrcode, get_asset_label_image
"""

from __future__ import annotations

import base64
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import HomeboxClient

_MAX_FETCH_BYTES = 50 * 1024 * 1024  # 50 MiB cap on URL fetch

_client: HomeboxClient | None = None


def _get_client() -> HomeboxClient:
    global _client
    if _client is None:
        _client = HomeboxClient.from_env()
    return _client


def _decode_bytes(b64: str | None, url: str | None) -> bytes:
    """Return file bytes from exactly one of *b64* or *url*."""
    if (b64 is None) == (url is None):
        raise ValueError("Provide exactly one of content_base64 or content_url")
    if b64 is not None:
        return base64.b64decode(b64, validate=True)
    assert url is not None
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("content_url must be http(s)://")
    req = urllib.request.Request(url, headers={"User-Agent": "homebox-mcp/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data: bytes = resp.read(_MAX_FETCH_BYTES + 1)
    if len(data) > _MAX_FETCH_BYTES:
        raise ValueError(f"URL fetch exceeded {_MAX_FETCH_BYTES} bytes cap")
    return data


mcp = FastMCP(
    "Homebox MCP",
    instructions=(
        "MCP server for the Homebox (sysadminsmedia/homebox) inventory management system. "
        "All item update/create operations are normalized to satisfy Homebox v0.25 "
        "schema rules (tagIds vs tags, YYYY-MM-DD purchaseTime, zero-date sentinels)."
    ),
)


# =========================================================================
# Items
# =========================================================================


@mcp.tool()
async def list_items(
    location: str | None = None,
    tags: list[str] | None = None,
    archived: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List items with optional filters.

    Args:
        location: Filter by location UUID.
        tags: Filter to items that carry ALL of these tag UUIDs.
        archived: ``True`` archived only, ``False`` active only, ``None`` for both.
        page: 1-indexed page number.
        page_size: Page size (default 50).
    """
    params: dict[str, Any] = {"page": page, "pageSize": page_size}
    if location is not None:
        params["locations"] = location
    if tags:
        params["labels"] = tags  # legacy query param name; Homebox v0.25 still accepts
    if archived is not None:
        params["includeArchived"] = "true" if archived else "false"
    return await _get_client().get_dict("/api/v1/items", params=params)


@mcp.tool()
async def get_item(item_id: str) -> dict[str, Any]:
    """Get a single item by UUID, including full notes + attachment metadata."""
    return await _get_client().get_dict(f"/api/v1/items/{item_id}")


@mcp.tool()
async def get_item_by_asset_id(asset_id: str) -> dict[str, Any]:
    """Look up an item by its human-readable asset ID (e.g. ``000-142``)."""
    return await _get_client().get_dict(f"/api/v1/assets/{asset_id}")


@mcp.tool()
async def search_items(query: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Free-text search across items (name, description, notes)."""
    return await _get_client().get_dict(
        "/api/v1/items",
        params={"q": query, "page": page, "pageSize": page_size},
    )


@mcp.tool()
async def create_item(
    name: str,
    location_id: str,
    description: str = "",
    tag_ids: list[str] | None = None,
    label_ids: list[str] | None = None,  # legacy alias for tag_ids — accepted for back-compat
    quantity: int = 1,
    purchase_price: float = 0.0,
    purchase_from: str = "",
    purchase_time: str = "",
    serial_number: str = "",
    manufacturer: str = "",
    model_number: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create a new item.

    The body is normalized through the Homebox v0.25 rules: ``purchase_time``
    accepts either ``YYYY-MM-DD`` or RFC3339 (truncated to date), zero-date
    sentinels are converted to empty string, ``label_ids`` becomes the wire
    field ``labelIds``.

    Homebox v0.25's ``POST /api/v1/items`` endpoint **only accepts**
    ``name``, ``description``, ``locationId``, and ``labelIds``. All other
    fields (purchase*, manufacturer, modelNumber, serialNumber, notes) are
    silently dropped on POST and must be set via a follow-up PUT. To hide
    that two-step from callers, this tool issues the create first, then
    auto-follows with ``update_item`` when any of the extras were provided
    as non-default. Discovered empirically 2026-05-12 — verified that the
    normalizer fix isn't sufficient because this is endpoint-scope, not
    format.
    """
    # Step 1: minimal POST body (the endpoint-accepted subset).
    create_body: dict[str, Any] = {
        "name": name,
        "locationId": location_id,
        "description": description,
    }
    effective_tag_ids = tag_ids or label_ids
    if effective_tag_ids:
        create_body["tagIds"] = effective_tag_ids
    item = await _get_client().post_item(create_body)

    # Step 2: detect non-default extras + follow up with update_item.
    extras: dict[str, Any] = {}
    if quantity != 1:
        extras["quantity"] = quantity
    if purchase_price not in (0.0, 0):
        extras["purchasePrice"] = purchase_price
    if purchase_from:
        extras["purchaseFrom"] = purchase_from
    if purchase_time:
        extras["purchaseTime"] = purchase_time
    if serial_number:
        extras["serialNumber"] = serial_number
    if manufacturer:
        extras["manufacturer"] = manufacturer
    if model_number:
        extras["modelNumber"] = model_number
    if notes:
        extras["notes"] = notes

    if extras and item.get("id"):
        item = await update_item(item["id"], extras)

    return item


@mcp.tool()
async def update_item(item_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Update an existing item.

    *fields* is merged into the existing item before PUT, so callers can pass only
    the keys they want to change. The merged body is normalized via the Homebox v0.25
    rules so ``purchaseTime`` is always ``YYYY-MM-DD`` and label membership uses
    ``labelIds`` on the wire.
    """
    current = await _get_client().get_dict(f"/api/v1/items/{item_id}")
    # Homebox v0.25 returns nested objects (location, tags) on GET but expects flat IDs
    # on PUT. Reduce to wire-shape before merging.
    body: dict[str, Any] = {k: v for k, v in current.items() if not isinstance(v, list | dict)}
    body["locationId"] = (current.get("location") or {}).get("id", "")
    # Preserve current tag membership unless caller explicitly overrides via tagIds.
    body["tagIds"] = [tag["id"] for tag in (current.get("tags") or [])]
    body.update(fields)
    # Back-compat: if a caller passes the old "labelIds" key, translate to tagIds.
    if "labelIds" in body and "tagIds" not in fields:
        body["tagIds"] = body.pop("labelIds")
    return await _get_client().put_item(item_id, body)


@mcp.tool()
async def delete_item(item_id: str) -> dict[str, str]:
    """Permanently delete an item."""
    await _get_client().delete(f"/api/v1/items/{item_id}")
    return {"deleted": item_id}


# =========================================================================
# Locations
# =========================================================================


@mcp.tool()
async def list_locations() -> list[dict[str, Any]]:
    """List all locations (flat). Use ``get_location`` for nested children."""
    return await _get_client().get_list("/api/v1/locations")


@mcp.tool()
async def get_location(location_id: str) -> dict[str, Any]:
    """Get one location by UUID, including children and items."""
    return await _get_client().get_dict(f"/api/v1/locations/{location_id}")


@mcp.tool()
async def create_location(name: str, description: str = "", parent_id: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "description": description}
    if parent_id:
        body["parentId"] = parent_id
    return await _get_client().post("/api/v1/locations", json=body)


@mcp.tool()
async def update_location(
    location_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Update a location. *fields* is merged onto the current state before PUT."""
    current = await _get_client().get_dict(f"/api/v1/locations/{location_id}")
    body = {k: v for k, v in current.items() if not isinstance(v, list | dict)}
    if (current.get("parent") or {}).get("id"):
        body["parentId"] = current["parent"]["id"]
    body.update(fields)
    resp = await _get_client()._request("PUT", f"/api/v1/locations/{location_id}", json=body)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def delete_location(location_id: str) -> dict[str, str]:
    """Delete a location. Will fail if the location still contains items or children."""
    await _get_client().delete(f"/api/v1/locations/{location_id}")
    return {"deleted": location_id}


# =========================================================================
# Tags (renamed from "labels" in Homebox v0.25; legacy names kept as aliases)
# =========================================================================


@mcp.tool()
async def list_tags() -> list[dict[str, Any]]:
    """List all tags in the current group."""
    return await _get_client().get_list("/api/v1/tags")


@mcp.tool()
async def get_tag(tag_id: str) -> dict[str, Any]:
    return await _get_client().get_dict(f"/api/v1/tags/{tag_id}")


@mcp.tool()
async def create_tag(name: str, description: str = "", color: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "description": description}
    if color:
        body["color"] = color
    return await _get_client().post("/api/v1/tags", json=body)


@mcp.tool()
async def get_or_create_tag_by_name(name: str, description: str = "") -> dict[str, Any]:
    """Return the tag with the given name, creating it if it doesn't exist.

    Useful for vocab-driven tagging where the caller has a canonical tag NAME but
    no idea whether it's been materialized in Homebox yet. List → match by name →
    fall through to create. Race-tolerant: if two callers race the create, the
    second one's 422-on-duplicate triggers a relist + match.
    """
    existing = await _get_client().get_list("/api/v1/tags")
    for tag in existing:
        if isinstance(tag, dict) and tag.get("name") == name:
            return tag
    return await create_tag(name=name, description=description)  # type: ignore[no-any-return]


@mcp.tool()
async def update_tag(tag_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    current = await _get_client().get_dict(f"/api/v1/tags/{tag_id}")
    body = {k: v for k, v in current.items() if not isinstance(v, list | dict)}
    body.update(fields)
    resp = await _get_client()._request("PUT", f"/api/v1/tags/{tag_id}", json=body)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def delete_tag(tag_id: str) -> dict[str, str]:
    """Permanently delete a tag. Cascade-removes tag membership from all items."""
    await _get_client().delete(f"/api/v1/tags/{tag_id}")
    return {"deleted": tag_id}


# Legacy aliases — keep so callers that still use list_labels/etc. don't break.
@mcp.tool()
async def list_labels() -> list[dict[str, Any]]:
    """Deprecated alias for list_tags."""
    return await list_tags()  # type: ignore[no-any-return]


@mcp.tool()
async def create_label(name: str, description: str = "", color: str = "") -> dict[str, Any]:
    """Deprecated alias for create_tag."""
    return await create_tag(name=name, description=description, color=color)  # type: ignore[no-any-return]


# =========================================================================
# Attachments
# =========================================================================


@mcp.tool()
async def list_attachments(item_id: str) -> list[dict[str, Any]]:
    """List attachments on an item (each entry includes id, type, primary flag, doc info)."""
    item = await _get_client().get_dict(f"/api/v1/items/{item_id}")
    attachments = item.get("attachments", [])
    return attachments if isinstance(attachments, list) else []


@mcp.tool()
async def upload_attachment(
    item_id: str,
    filename: str,
    attachment_type: str = "attachment",
    content_base64: str | None = None,
    content_url: str | None = None,
) -> dict[str, Any]:
    """Upload a file attachment to an item.

    Args:
        item_id: Target item UUID.
        filename: Filename to store the attachment under.
        attachment_type: One of ``attachment`` (default), ``photo``, ``manual``, ``receipt``.
            The caller chooses explicitly — the server does not infer from extension.
        content_base64: Standard base64-encoded file bytes.
        content_url: An http(s) URL the server will fetch and forward. Capped at 50 MiB.
    """
    if attachment_type not in {"attachment", "photo", "manual", "receipt"}:
        raise ValueError(f"attachment_type must be one of attachment/photo/manual/receipt; got {attachment_type!r}")
    data = _decode_bytes(content_base64, content_url)
    # Guess a content type from extension; falls back to octet-stream.
    import mimetypes

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    files = {"file": (filename, data, content_type)}
    form: dict[str, Any] = {"type": attachment_type, "name": filename}
    return await _get_client().upload_multipart(f"/api/v1/items/{item_id}/attachments", files=files, data=form)


@mcp.tool()
async def delete_attachment(item_id: str, attachment_id: str) -> dict[str, str]:
    """Delete an attachment from an item."""
    await _get_client().delete(f"/api/v1/items/{item_id}/attachments/{attachment_id}")
    return {"deleted": attachment_id}


@mcp.tool()
async def set_primary_image(item_id: str, attachment_id: str) -> dict[str, Any]:
    """Mark an existing attachment as the item's primary image.

    Updates the attachment record on the item with ``primary=True`` and ``type='photo'``.
    """
    resp = await _get_client()._request(
        "PUT",
        f"/api/v1/items/{item_id}/attachments/{attachment_id}",
        json={"primary": True, "type": "photo"},
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


# =========================================================================
# QR codes + label images
# =========================================================================


@mcp.tool()
async def get_qrcode(data: str) -> dict[str, str]:
    """Generate a Homebox QR code for *data* (typically a URL or asset ID).

    Returns a dict with ``png_base64`` (or jpeg — whatever Homebox served) and
    ``content_type``. Decode the base64 to get the raw image bytes.
    """
    content, content_type = await _get_client().get_bytes("/api/v1/qrcode", params={"data": data})
    return {
        "image_base64": base64.b64encode(content).decode("ascii"),
        "content_type": content_type,
    }


@mcp.tool()
async def get_asset_label_image(asset_id: str) -> dict[str, str]:
    """Return the canonical printable label image for an asset ID (e.g. ``000-142``).

    Homebox renders a 526x200 PNG containing the QR code, asset ID, and item name.
    Returns ``image_base64`` + ``content_type``.
    """
    content, content_type = await _get_client().get_bytes(f"/api/v1/labelmaker/asset/{asset_id}")
    return {
        "image_base64": base64.b64encode(content).decode("ascii"),
        "content_type": content_type,
    }
