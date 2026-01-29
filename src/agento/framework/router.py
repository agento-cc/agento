"""Router protocol, types, and routing chain for ingress identity resolution."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from .event_manager import get_event_manager
from .events import RoutingAmbiguousEvent, RoutingFailedEvent, RoutingResolvedEvent
from .router_registry import get_routers
from .workspace import AgentView, get_agent_view

logger = logging.getLogger(__name__)


@dataclass
class RoutingContext:
    """Rich inbound request context, populated by the channel/module that triggers routing."""

    channel: str
    workflow_type: str
    identity_type: str
    identity_value: str
    payload: dict = field(default_factory=dict)


@dataclass
class RoutingCandidate:
    """Single candidate from a router."""

    agent_view_id: int
    confidence: float
    reason: str


@dataclass
class RoutingResult:
    """What a router returns."""

    router_name: str
    candidates: list[RoutingCandidate]


@dataclass
class RoutingDecision:
    """Final output of the routing chain."""

    agent_view_id: int
    agent_view: AgentView | None
    matched_router: str
    all_results: list[RoutingResult]
    reason: str
    ambiguous: bool = False


class Router(Protocol):
    @property
    def name(self) -> str: ...

    def resolve(self, conn: object, context: RoutingContext) -> RoutingResult | None: ...


def resolve_agent_view(conn: object, context: RoutingContext) -> RoutingDecision | None:
    """Run all registered routers and return the routing decision.

    Runs ALL routers (not short-circuit) to detect ambiguity.
    First matching router's first candidate wins.
    """
    routers = get_routers()
    all_results: list[RoutingResult] = []

    for router in routers:
        try:
            result = router.resolve(conn, context)
            if result and result.candidates:
                all_results.append(result)
        except Exception:
            logger.exception("Router %r raised an exception", router.name)

    em = get_event_manager()

    if not all_results:
        logger.info(
            "Routing failed: no router matched for %s/%s",
            context.identity_type, context.identity_value,
        )
        em.dispatch("agento_routing_failed", RoutingFailedEvent(context=context))
        return None

    winner = all_results[0]
    candidate = winner.candidates[0]
    agent_view = get_agent_view(conn, candidate.agent_view_id)
    ambiguous = len(all_results) > 1

    decision = RoutingDecision(
        agent_view_id=candidate.agent_view_id,
        agent_view=agent_view,
        matched_router=winner.router_name,
        all_results=all_results,
        reason=candidate.reason,
        ambiguous=ambiguous,
    )

    if ambiguous:
        logger.warning(
            "Routing ambiguous: %d routers matched for %s/%s, using %r",
            len(all_results), context.identity_type, context.identity_value,
            winner.router_name,
        )
        em.dispatch(
            "agento_routing_ambiguous",
            RoutingAmbiguousEvent(
                context=context,
                agent_view_id=candidate.agent_view_id,
                matched_router=winner.router_name,
                all_routers=[r.router_name for r in all_results],
                reason=candidate.reason,
            ),
        )
    else:
        logger.info(
            "Routing resolved: %s/%s → agent_view %d via %r",
            context.identity_type, context.identity_value,
            candidate.agent_view_id, winner.router_name,
        )
        em.dispatch(
            "agento_routing_resolved",
            RoutingResolvedEvent(
                context=context,
                agent_view_id=candidate.agent_view_id,
                matched_router=winner.router_name,
                reason=candidate.reason,
                candidate_count=sum(len(r.candidates) for r in all_results),
            ),
        )

    return decision
