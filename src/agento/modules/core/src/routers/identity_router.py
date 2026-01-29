"""Default identity router — resolves agent_view from ingress_identity table."""
from __future__ import annotations

from agento.framework.ingress_identity import get_ingress_identity
from agento.framework.router import RoutingCandidate, RoutingContext, RoutingResult


class IdentityRouter:
    @property
    def name(self) -> str:
        return "identity"

    def resolve(self, conn: object, context: RoutingContext) -> RoutingResult | None:
        identity = get_ingress_identity(conn, context.identity_type, context.identity_value)
        if identity is None or not identity.is_active:
            return None
        return RoutingResult(
            router_name=self.name,
            candidates=[
                RoutingCandidate(
                    agent_view_id=identity.agent_view_id,
                    confidence=1.0,
                    reason=f"identity binding: {context.identity_type}={context.identity_value}",
                )
            ],
        )
