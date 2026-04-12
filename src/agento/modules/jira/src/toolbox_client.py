from __future__ import annotations

import httpx


class ToolboxAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Toolbox API HTTP {status_code}: {body}")


class ToolboxClient:
    """HTTP client for the toolbox REST API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def jira_search(self, jql: str, fields: list[str], max_results: int = 50) -> dict:
        response = self._client.post(
            "/api/jira/search",
            json={"jql": jql, "fields": fields, "maxResults": max_results},
        )
        if response.status_code != 200:
            raise ToolboxAPIError(response.status_code, response.text)
        return response.json()

    def jira_get_comments(self, issue_key: str) -> list[dict]:
        response = self._client.post(
            "/api/jira/issue/comments",
            json={"issue_key": issue_key},
        )
        if response.status_code != 200:
            raise ToolboxAPIError(response.status_code, response.text)
        return response.json().get("comments", [])

    def jira_request(
        self, method: str, path: str, body: dict | None = None,
        *, auth_user: str | None = None, auth_token: str | None = None,
        jira_host: str | None = None,
    ) -> dict:
        payload: dict = {"method": method, "path": path}
        if body is not None:
            payload["body"] = body
        if auth_user:
            payload["auth_user"] = auth_user
        if auth_token:
            payload["auth_token"] = auth_token
        if jira_host:
            payload["jira_host"] = jira_host
        response = self._client.post("/api/jira/request", json=payload)
        if response.status_code != 200:
            raise ToolboxAPIError(response.status_code, response.text)
        data = response.json()
        if not data.get("ok", True):
            raise ToolboxAPIError(data.get("status", 0), str(data.get("data", "")))
        return data.get("data", {})

    def close(self) -> None:
        self._client.close()
