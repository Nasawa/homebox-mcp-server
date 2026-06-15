"""Authenticated HTTP client for the Homebox API.

Homebox uses session-based authentication: POST credentials to ``/api/v1/users/login``,
receive a token, send it as ``Authorization: <token>`` on subsequent calls (note: NO
``Bearer`` prefix — Homebox uses the bare token string).

This client handles login on first use, retries once on 401 with a fresh login, and
normalizes Entity PUT/POST bodies via :func:`homebox_mcp.normalizer.normalize_entity_body`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .normalizer import normalize_entity_body


class HomeboxAuthError(RuntimeError):
    """Raised when Homebox login fails or returns an unexpected shape."""


class HomeboxClient:
    """Minimal authenticated HTTP client for Homebox v0.26.

    Parameters
    ----------
    base_url
        Homebox base URL, e.g. ``https://homebox.example.com``. Trailing slash optional.
    username
        Homebox account email.
    password
        Homebox account password.
    timeout
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None
        self._client = httpx.AsyncClient(timeout=timeout, base_url=self.base_url)

    @classmethod
    def from_env(cls) -> HomeboxClient:
        """Build a client from ``HOMEBOX_URL`` / ``HOMEBOX_USERNAME`` / ``HOMEBOX_PASSWORD``."""
        url = os.environ.get("HOMEBOX_URL")
        user = os.environ.get("HOMEBOX_USERNAME")
        pw = os.environ.get("HOMEBOX_PASSWORD")
        if not (url and user and pw):
            raise HomeboxAuthError("Set HOMEBOX_URL, HOMEBOX_USERNAME, and HOMEBOX_PASSWORD.")
        return cls(url, user, pw)

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> str:
        resp = await self._client.post(
            "/api/v1/users/login",
            json={"username": self._username, "password": self._password},
        )
        if resp.status_code != 200:
            raise HomeboxAuthError(f"Login failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        token = data.get("token")
        if not isinstance(token, str):
            raise HomeboxAuthError(f"Login response missing 'token': {data}")
        self._token = token
        return token

    async def _ensure_token(self) -> str:
        if self._token is None:
            await self._login()
        assert self._token is not None
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._ensure_token()
        headers = {"Authorization": token}
        resp = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            files=files,
            data=data,
            headers=headers,
        )
        if resp.status_code == 401:
            # Token expired — log in again and retry once.
            self._token = None
            token = await self._ensure_token()
            headers["Authorization"] = token
            resp = await self._client.request(
                method,
                path,
                json=json,
                params=params,
                files=files,
                data=data,
                headers=headers,
            )
        return resp

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        resp = await self._request("GET", path, params=params)
        resp.raise_for_status()
        result: dict[str, Any] | list[Any] = resp.json()
        return result

    async def get_dict(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET endpoints that return a JSON object."""
        result = await self.get(path, params=params)
        if not isinstance(result, dict):
            raise TypeError(f"Expected JSON object at {path}, got {type(result).__name__}")
        return result

    async def get_list(self, path: str, *, params: dict[str, Any] | None = None) -> list[Any]:
        """GET endpoints that return a JSON array (e.g. /tags, /entity-types)."""
        result = await self.get(path, params=params)
        if not isinstance(result, list):
            raise TypeError(f"Expected JSON array at {path}, got {type(result).__name__}")
        return result

    async def get_bytes(self, path: str, *, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
        """Return ``(content_bytes, content_type)`` for endpoints that serve binary data
        (e.g. ``/qrcode``, ``/labelmaker/asset/{id}``)."""
        resp = await self._request("GET", path, params=params)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    async def post(self, path: str, *, json: dict[str, Any] | list[Any] | None = None) -> dict[str, Any]:
        resp = await self._request("POST", path, json=json)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def put_entity(self, entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """PUT an Entity body with normalization applied. Use this for ANY entity update."""
        normalized = normalize_entity_body(body)
        resp = await self._request("PUT", f"/api/v1/entities/{entity_id}", json=normalized)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def post_entity(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST a new Entity with normalization applied."""
        normalized = normalize_entity_body(body)
        resp = await self._request("POST", "/api/v1/entities", json=normalized)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def put_item(self, item_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Deprecated compatibility wrapper for entity updates."""
        return await self.put_entity(item_id, body)

    async def post_item(self, body: dict[str, Any]) -> dict[str, Any]:
        """Deprecated compatibility wrapper for entity creates."""
        return await self.post_entity(body)

    async def delete(self, path: str) -> None:
        resp = await self._request("DELETE", path)
        resp.raise_for_status()

    async def upload_multipart(
        self,
        path: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST a multipart/form-data body. *files* is ``{field: (filename, bytes, content_type)}``."""
        resp = await self._request("POST", path, files=files, data=data)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result
