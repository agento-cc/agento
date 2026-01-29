"""Tests for router types and IdentityRouter."""
from datetime import datetime
from unittest.mock import MagicMock

from agento.framework.ingress_identity import IngressIdentity
from agento.framework.router import RoutingCandidate, RoutingContext, RoutingDecision, RoutingResult
from agento.modules.core.src.routers.identity_router import IdentityRouter


class TestRoutingDataclasses:
    def test_routing_context(self):
        ctx = RoutingContext(
            channel="jira", workflow_type="cron",
            identity_type="email", identity_value="user@example.com",
        )
        assert ctx.channel == "jira"
        assert ctx.payload == {}

    def test_routing_context_with_payload(self):
        ctx = RoutingContext(
            channel="outlook", workflow_type="followup",
            identity_type="email", identity_value="user@example.com",
            payload={"subject": "Test"},
        )
        assert ctx.payload["subject"] == "Test"

    def test_routing_candidate(self):
        c = RoutingCandidate(agent_view_id=1, confidence=1.0, reason="test")
        assert c.agent_view_id == 1
        assert c.confidence == 1.0

    def test_routing_result(self):
        r = RoutingResult(
            router_name="identity",
            candidates=[RoutingCandidate(agent_view_id=1, confidence=1.0, reason="test")],
        )
        assert r.router_name == "identity"
        assert len(r.candidates) == 1

    def test_routing_decision(self):
        d = RoutingDecision(
            agent_view_id=1, agent_view=None,
            matched_router="identity", all_results=[], reason="test",
        )
        assert d.ambiguous is False


class TestIdentityRouter:
    def _make_identity(self, *, is_active=True):
        return IngressIdentity(
            id=1, identity_type="email", identity_value="user@example.com",
            agent_view_id=10, is_active=is_active,
            created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 1, 1),
        )

    def test_name(self):
        assert IdentityRouter().name == "identity"

    def test_resolve_match(self, monkeypatch):
        identity = self._make_identity()
        monkeypatch.setattr(
            "agento.modules.core.src.routers.identity_router.get_ingress_identity",
            lambda conn, t, v: identity,
        )
        router = IdentityRouter()
        ctx = RoutingContext(channel="jira", workflow_type="cron", identity_type="email", identity_value="user@example.com")
        result = router.resolve(MagicMock(), ctx)
        assert result is not None
        assert result.candidates[0].agent_view_id == 10
        assert result.candidates[0].confidence == 1.0

    def test_resolve_no_match(self, monkeypatch):
        monkeypatch.setattr(
            "agento.modules.core.src.routers.identity_router.get_ingress_identity",
            lambda conn, t, v: None,
        )
        router = IdentityRouter()
        ctx = RoutingContext(channel="jira", workflow_type="cron", identity_type="email", identity_value="nobody@example.com")
        result = router.resolve(MagicMock(), ctx)
        assert result is None

    def test_resolve_inactive(self, monkeypatch):
        identity = self._make_identity(is_active=False)
        monkeypatch.setattr(
            "agento.modules.core.src.routers.identity_router.get_ingress_identity",
            lambda conn, t, v: identity,
        )
        router = IdentityRouter()
        ctx = RoutingContext(channel="jira", workflow_type="cron", identity_type="email", identity_value="user@example.com")
        result = router.resolve(MagicMock(), ctx)
        assert result is None
