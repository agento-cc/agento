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

    def close(self) -> None:
        self._client.close()
