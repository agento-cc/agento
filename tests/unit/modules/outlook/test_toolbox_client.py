import httpx
import pytest
import respx

from agento.modules.outlook.src.toolbox_client import (
    OutlookToolboxClient,
    ToolboxAPIError,
)


@respx.mock
def test_list_unread_posts_top_and_returns_messages():
    route = respx.post("http://toolbox:3001/api/outlook/unread").mock(
        return_value=httpx.Response(200, json={"messages": [{
            "id": "m1", "subject": "A",
            "from": {"name": "X", "address": "x@y.com"},
            "receivedDateTime": "2026-01-01T00:00:00Z",
            "conversationId": "c1", "dmarc": "pass",
        }]})
    )
    client = OutlookToolboxClient("http://toolbox:3001")
    msgs = client.list_unread(top=10)
    client.close()
    assert route.called
    assert msgs[0]["id"] == "m1"
    assert msgs[0]["dmarc"] == "pass"


@respx.mock
def test_list_unread_sends_top_in_body():
    captured = {}

    def _handler(request):
        import json as _json
        captured.update(_json.loads(request.content))
        return httpx.Response(200, json={"messages": []})

    respx.post("http://toolbox:3001/api/outlook/unread").mock(side_effect=_handler)
    client = OutlookToolboxClient("http://toolbox:3001")
    msgs = client.list_unread(top=7)
    client.close()
    assert captured == {"top": 7}
    assert msgs == []


@respx.mock
def test_list_unread_missing_messages_key_returns_empty():
    respx.post("http://toolbox:3001/api/outlook/unread").mock(
        return_value=httpx.Response(200, json={})
    )
    client = OutlookToolboxClient("http://toolbox:3001")
    assert client.list_unread() == []
    client.close()


@respx.mock
def test_list_unread_raises_on_non_200():
    respx.post("http://toolbox:3001/api/outlook/unread").mock(
        return_value=httpx.Response(500, text="boom")
    )
    client = OutlookToolboxClient("http://toolbox:3001")
    with pytest.raises(ToolboxAPIError) as exc:
        client.list_unread()
    client.close()
    assert exc.value.status_code == 500
