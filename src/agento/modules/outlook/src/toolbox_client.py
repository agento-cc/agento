from __future__ import annotations

import httpx


class ToolboxAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Toolbox API HTTP {status_code}: {body}")


class OutlookToolboxClient:
    """HTTP client for the toolbox Outlook REST API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def list_unread(self, top: int = 10) -> list[dict]:
        response = self._client.post("/api/outlook/unread", json={"top": top})
        if response.status_code != 200:
            raise ToolboxAPIError(response.status_code, response.text)
        return response.json().get("messages", [])

    def close(self) -> None:
        self._client.close()
