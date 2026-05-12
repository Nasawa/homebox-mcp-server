"""Body-shape rules for Homebox v0.25 item PUT/POST bodies.

Homebox v0.25 silently drops fields whose name or format doesn't match the schema:
* Tag membership is set via ``tagIds`` (list of tag UUIDs), NOT ``tags`` or
  ``labelIds``. Empirically verified 2026-05-12 against running v0.25: the API
  resource is ``/v1/tags`` (renamed from ``/v1/labels`` in an earlier point
  release), items return a ``tags`` array of full tag objects on GET, and the
  write field is ``tagIds`` on both POST and PUT. The "labelIds" name carried
  forward from a pre-v0.25 postmortem was wrong — those PUTs silently dropped.
* ``purchaseTime`` must be ``YYYY-MM-DD`` (not RFC3339)
* The zero-date sentinel ``0001-01-01T00:00:00Z`` must be converted to an empty string
  before a PUT — otherwise the server rejects the body and the update silently fails

These rules live HERE, in one function, so individual tool implementations can never
re-violate them. Every Item-shaped body that travels to Homebox passes through
:func:`normalize_item_body` first.
"""

from __future__ import annotations

import re
from typing import Any

ZERO_DATE_SENTINELS = (
    "0001-01-01T00:00:00Z",
    "0001-01-01T00:00:00+00:00",
    "0001-01-01",
)

_RFC3339_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})T")


def _coerce_date(value: Any) -> Any:
    """Coerce a date-like value to either ``YYYY-MM-DD`` or empty string.

    * Zero-date sentinels become ``""``.
    * RFC3339 timestamps are truncated to the date portion.
    * Already-YYYY-MM-DD values pass through unchanged.
    * Non-string values pass through unchanged (caller's problem).
    """
    if not isinstance(value, str):
        return value
    if value in ZERO_DATE_SENTINELS or value == "":
        return ""
    m = _RFC3339_DATE_PREFIX.match(value)
    if m:
        return m.group(1)
    return value


def normalize_item_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *body* with Homebox v0.25 schema rules applied.

    * ``tags`` (list of tag objects from a GET response, OR list of UUID strings) is
      promoted to ``tagIds`` (list of UUIDs) when entries look like UUIDs, OR
      flattened from ``[{"id": "...", ...}]`` shape to ``[id, ...]``.
    * ``labelIds`` (legacy from pre-v0.25 postmortems) is renamed to ``tagIds``.
    * ``purchaseTime`` is coerced via :func:`_coerce_date`.
    * Any other ``*Time`` / ``*Date`` field that looks date-shaped is coerced too.
    """
    out = dict(body)

    # Legacy: rename labelIds → tagIds (the pre-v0.25 name).
    if "labelIds" in out and "tagIds" not in out:
        out["tagIds"] = out.pop("labelIds")
    elif "labelIds" in out:
        # Both present: caller is being explicit with tagIds, drop the legacy alias.
        out.pop("labelIds")

    # ``tags`` is the GET-response shape; on write we want ``tagIds``. Convert.
    if "tags" in out:
        tags = out.pop("tags")
        if "tagIds" not in out and isinstance(tags, list) and tags:
            # Two accepted shapes: list of UUID strings, or list of {id: ...} dicts.
            if all(isinstance(t, str) and len(t) == 36 and t.count("-") == 4 for t in tags):
                out["tagIds"] = tags
            elif all(isinstance(t, dict) and t.get("id") for t in tags):
                out["tagIds"] = [t["id"] for t in tags]

    # purchaseTime is the dominant case
    if "purchaseTime" in out:
        out["purchaseTime"] = _coerce_date(out["purchaseTime"])

    # Any remaining *Time / *Date keys
    for key, value in list(out.items()):
        if key == "purchaseTime":
            continue
        if (key.endswith("Time") or key.endswith("Date")) and isinstance(value, str):
            coerced = _coerce_date(value)
            if coerced != value:
                out[key] = coerced

    return out
