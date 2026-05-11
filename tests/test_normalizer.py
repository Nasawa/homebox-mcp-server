"""Tests for the Homebox v0.25 body-shape normalizer."""

from __future__ import annotations

from homebox_mcp.normalizer import (
    ZERO_DATE_SENTINELS,
    _coerce_date,
    normalize_item_body,
)


class TestCoerceDate:
    def test_zero_date_sentinels_become_empty(self) -> None:
        for sentinel in ZERO_DATE_SENTINELS:
            assert _coerce_date(sentinel) == ""

    def test_empty_string_passes_through(self) -> None:
        assert _coerce_date("") == ""

    def test_rfc3339_truncates_to_date(self) -> None:
        assert _coerce_date("2026-05-10T18:47:00Z") == "2026-05-10"
        assert _coerce_date("2026-05-10T18:47:00+00:00") == "2026-05-10"

    def test_already_yyyy_mm_dd_passes_through(self) -> None:
        assert _coerce_date("2026-05-10") == "2026-05-10"

    def test_non_string_passes_through(self) -> None:
        assert _coerce_date(None) is None
        assert _coerce_date(42) == 42


class TestNormalizeItemBody:
    def test_purchase_time_rfc3339_truncates(self) -> None:
        out = normalize_item_body({"purchaseTime": "2026-05-10T18:47:00Z"})
        assert out["purchaseTime"] == "2026-05-10"

    def test_purchase_time_zero_date_clears(self) -> None:
        out = normalize_item_body({"purchaseTime": "0001-01-01T00:00:00Z"})
        assert out["purchaseTime"] == ""

    def test_tags_with_uuids_become_labelIds(self) -> None:
        uuid1 = "11111111-1111-1111-1111-111111111111"
        uuid2 = "22222222-2222-2222-2222-222222222222"
        out = normalize_item_body({"tags": [uuid1, uuid2]})
        assert "tags" not in out
        assert out["labelIds"] == [uuid1, uuid2]

    def test_tags_with_non_uuid_dropped(self) -> None:
        # Tags that look like display names get DROPPED (caller should have used labelIds).
        out = normalize_item_body({"tags": ["foo", "bar"]})
        assert "tags" not in out
        assert "labelIds" not in out

    def test_existing_labelIds_not_overwritten(self) -> None:
        uuid_existing = "33333333-3333-3333-3333-333333333333"
        uuid_in_tags = "44444444-4444-4444-4444-444444444444"
        out = normalize_item_body({"labelIds": [uuid_existing], "tags": [uuid_in_tags]})
        assert "tags" not in out
        assert out["labelIds"] == [uuid_existing]

    def test_other_date_fields_coerced(self) -> None:
        out = normalize_item_body({"warrantyExpireDate": "2027-01-01T00:00:00Z", "soldTime": "0001-01-01T00:00:00Z"})
        assert out["warrantyExpireDate"] == "2027-01-01"
        assert out["soldTime"] == ""

    def test_unrelated_fields_passthrough(self) -> None:
        body = {"name": "Foo", "quantity": 3, "purchasePrice": 12.34, "purchaseTime": "2026-05-10"}
        assert normalize_item_body(body) == body

    def test_input_not_mutated(self) -> None:
        body = {"purchaseTime": "0001-01-01T00:00:00Z"}
        normalize_item_body(body)
        assert body == {"purchaseTime": "0001-01-01T00:00:00Z"}
