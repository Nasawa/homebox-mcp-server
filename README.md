# homebox-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[Homebox](https://github.com/sysadminsmedia/homebox) — the open-source
inventory management system for home users.

Exposes ~22 tools across items, locations, labels, attachments, and QR-code /
label-image generation. Item create/update bodies are normalized to satisfy
Homebox v0.25 schema rules (`labelIds` vs `tags`, `YYYY-MM-DD` `purchaseTime`,
zero-date sentinels) so the silent-PUT trap can't bite callers.

## Status

**Alpha (v0.1.0).** Tested against Homebox v0.25.0. Unit tests cover the
normalizer + client; tool integration tests require a live Homebox instance
and are not included.

## Install

```bash
pip install homebox-mcp-server
```

Or run without install via [uvx](https://docs.astral.sh/uv/):

```bash
uvx homebox-mcp-server
```

## Configuration

The server reads three environment variables on first use:

| Variable | Purpose |
|---|---|
| `HOMEBOX_URL` | Homebox base URL (e.g. `https://homebox.example.com`) |
| `HOMEBOX_USERNAME` | Homebox account email |
| `HOMEBOX_PASSWORD` | Homebox account password |

Homebox uses session-based auth: the server logs in on first request and
auto-refreshes on 401. There is no static API-token surface in Homebox v0.25.

## Wire-up with an MCP client

For Claude Desktop / Claude Code, add to `mcpServers` in your config:

```json
{
  "mcpServers": {
    "homebox": {
      "type": "stdio",
      "command": "uvx",
      "args": ["homebox-mcp-server"],
      "env": {
        "HOMEBOX_URL": "https://homebox.example.com",
        "HOMEBOX_USERNAME": "you@example.com",
        "HOMEBOX_PASSWORD": "..."
      }
    }
  }
}
```

## Tool reference

### Items

| Tool | Purpose |
|---|---|
| `list_items(location, labels, archived, page, page_size)` | List with filters |
| `get_item(item_id)` | Full detail for one item |
| `get_item_by_asset_id(asset_id)` | Lookup by `000-142`-style asset ID |
| `search_items(query, page, page_size)` | Free-text search |
| `create_item(name, location_id, ...)` | Create — body normalized |
| `update_item(item_id, fields)` | Merge-and-PUT — body normalized |
| `delete_item(item_id)` | Permanent delete |

### Locations

`list_locations`, `get_location`, `create_location`, `update_location`, `delete_location`

### Labels

`list_labels`, `get_label`, `create_label`, `update_label`, `delete_label`

### Attachments

| Tool | Purpose |
|---|---|
| `list_attachments(item_id)` | Returns the item's attachments list |
| `upload_attachment(item_id, filename, attachment_type, content_base64\|content_url)` | Upload a file. `attachment_type` is one of `attachment`/`photo`/`manual`/`receipt`. Caller specifies — no extension-based inference. |
| `delete_attachment(item_id, attachment_id)` | Delete one attachment |
| `set_primary_image(item_id, attachment_id)` | Mark an existing attachment as the item's primary image |

### QR codes & label images

| Tool | Purpose |
|---|---|
| `get_qrcode(data)` | Generate a QR code via Homebox's `/qrcode` endpoint. Returns `image_base64` + `content_type`. |
| `get_asset_label_image(asset_id)` | The canonical Homebox printable label PNG (526×200) including QR + asset ID + name. |

The `get_asset_label_image` flow lets agents drive label printing
end-to-end without leaving the MCP surface — pair the returned PNG with
whatever label printer your agent can reach (CUPS / `lpr`, a printer-specific
MCP, etc.).

## The v0.25 silent-PUT trap

Homebox v0.25 silently drops PUT body fields whose name or format doesn't
match the schema, which makes "the request returned 200 but my change didn't
persist" a real failure mode. This server bakes the workarounds into one
normalizer:

* `tagIds` field name (not `tags`) — though `tags` is auto-renamed if the
  values are UUIDs
* `purchaseTime` (and other `*Time` / `*Date` fields) must be `YYYY-MM-DD`,
  not RFC3339 — RFC3339 strings are truncated automatically
* `0001-01-01T00:00:00Z` zero-date sentinels are converted to empty string

See `src/homebox_mcp/normalizer.py` for the full rule set.

## Recipe: notes-marker dedup pattern

If you're using this MCP from an agent that processes external data (e.g.
Amazon order receipts), a useful convention is to write a marker line into
the item's `notes` field:

```
amazon-asin: B0CXYZ12345
```

Then `get_item(item_id)` lets you read it back to detect duplicates without
needing a separate database. The normalizer leaves `notes` untouched —
markers persist exactly as written.

## Development

```bash
git clone https://gitea.anigeek.com/Claw/homebox-mcp-server.git
cd homebox-mcp-server
uv sync --dev
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

## License

MIT. See `LICENSE`.
