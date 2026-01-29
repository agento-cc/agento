from __future__ import annotations

import httpx
import pytest
import respx

from agento.modules.jira.src.toolbox_client import ToolboxAPIError, ToolboxClient


@respx.mock
def test_jira_search_success(jira_todo):
    respx.post("http://toolbox:3001/api/jira/search").mock(
        return_value=httpx.Response(200, json=jira_todo)
    )

    client = ToolboxClient("http://toolbox:3001")
    result = client.jira_search(
        jql='project = AI AND status = "To Do"',
        fields=["key", "summary"],
    )

    assert len(result["issues"]) == 2
    assert result["issues"][0]["key"] == "AI-10"


@respx.mock
def test_jira_search_sends_correct_payload():
    route = respx.post("http://toolbox:3001/api/jira/search").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )

    client = ToolboxClient("http://toolbox:3001")
    client.jira_search(jql="project = X", fields=["key"], max_results=10)

    request = route.calls[0].request
    body = request.content.decode()
    import json
    payload = json.loads(body)
    assert payload["jql"] == "project = X"
    assert payload["fields"] == ["key"]
    assert payload["maxResults"] == 10


@respx.mock
def test_jira_search_http_error():
    respx.post("http://toolbox:3001/api/jira/search").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = ToolboxClient("http://toolbox:3001")
    with pytest.raises(ToolboxAPIError) as exc_info:
        client.jira_search(jql="bad", fields=[])

    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in exc_info.value.body
