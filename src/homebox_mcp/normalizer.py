"""Body-shape rules for Homebox v0.25 item PUT/POST bodies.

Homebox v0.25 silently drops fields whose name or format doesn't match the schema:
* tag membership is set via ``labelIds`` (list of label UUIDs), NOT ``tags``
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

    * ``tags`` (list of label objects/names) is renamed to ``labelIds`` (list of UUIDs)
      if all entries look like UUIDs; otherwise it's dropped with no replacement and
      the caller is expected to have passed ``labelIds`` directly.
    * ``purchaseTime`` is coerced via :func:`_coerce_date`.
    * Any other ``*Time`` / ``*Date`` field that looks date-shaped is coerced too.
    """
    out = dict(body)

    # ``tags`` is never a valid Homebox v0.25 field name — always drop it.
    # If labelIds isn't already present AND the tags values look like UUIDs,
    # promote them to labelIds. Otherwise just drop the tags key.
    if "tags" in out:
        tags = out.pop("tags")
        if (
            "labelIds" not in out
            and isinstance(tags, list)
            and tags
            and all(isinstance(t, str) and len(t) == 36 and t.count("-") == 4 for t in tags)
        ):
            out["labelIds"] = tags

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
