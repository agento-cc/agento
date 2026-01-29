# Routing — Ingress Identity Resolution

Maps inbound traffic (Outlook, Teams, API) to the right `agent_view` using a deterministic, module-extensible router chain.

## How It Works

1. **Inbound request arrives** — a channel/module creates a `RoutingContext` with identity info
2. **Router chain runs** — all registered routers execute in order (not short-circuit, to detect ambiguity)
3. **First match wins** — the first router (by order) with candidates determines the `agent_view`
4. **Events fire** — `agento_routing_resolved`, `agento_routing_ambiguous`, or `agento_routing_failed`

## RoutingContext

The channel/module that triggers routing populates the context:

```python
from agento.framework.contracts import RoutingContext

ctx = RoutingContext(
    channel="outlook",
    workflow_type="followup",
    identity_type="email",
    identity_value="user@example.com",
    payload={"subject": "Re: Project update", "thread_id": "abc123"},
)
```

| Field | Description |
|-------|-------------|
| `channel` | Channel name (e.g. `jira`, `outlook`, `teams`) |
| `workflow_type` | Workflow type (e.g. `cron`, `todo`, `followup`) |
| `identity_type` | Identity key (e.g. `email`, `teams`, `api_client`) |
| `identity_value` | Identity value (e.g. `user@example.com`) |
| `payload` | Channel-specific data (module populates before calling `resolve_agent_view()`) |

## Router Protocol

Modules contribute routers by implementing the `Router` protocol:

```python
from agento.framework.contracts import Router, RoutingContext, RoutingResult, RoutingCandidate

class MyCustomRouter:
    @property
    def name(self) -> str:
        return "my_custom"

    def resolve(self, conn, context: RoutingContext) -> RoutingResult | None:
        # Return None if no match, or a RoutingResult with candidates
        if context.identity_type == "api_client":
            return RoutingResult(
                router_name=self.name,
                candidates=[RoutingCandidate(
                    agent_view_id=42,
                    confidence=1.0,
                    reason="API client mapping",
                )],
            )
        return None
```

Register in `di.json`:

```json
{
  "routers": [
    {"name": "my_custom", "class": "src.routers.my_custom_router.MyCustomRouter", "order": 200}
  ]
}
```

## Router Chain

`resolve_agent_view(conn, context)` runs the chain:

1. Iterates all routers sorted by `(order, name)`
2. Calls `resolve()` on each — exceptions are swallowed and logged
3. Collects all non-empty results
4. First result's first candidate wins
5. If multiple routers matched → `ambiguous=True` on the decision + `agento_routing_ambiguous` event
6. If no router matched → returns `None` + `agento_routing_failed` event

```python
from agento.framework.router import resolve_agent_view, RoutingContext

decision = resolve_agent_view(conn, ctx)
if decision:
    print(f"Resolved to agent_view {decision.agent_view_id} via {decision.matched_router}")
    if decision.ambiguous:
        print("Warning: multiple routers matched")
```

## Default Router: Identity

The core module ships an `IdentityRouter` (order=100) that looks up the `ingress_identity` table:

- Maps `(identity_type, identity_value)` → `agent_view_id`
- Returns `None` for unknown or inactive identities
- Confidence is always 1.0 (deterministic binding)

### CLI Commands

```bash
# Bind an identity to an agent_view
bin/agento ingress:bind email user@example.com default

# List all bindings
bin/agento ingress:list
bin/agento ingress:list --type email --json

# Remove a binding
bin/agento ingress:unbind email user@example.com
```

## Routing Events

| Event | When |
|-------|------|
| `agento_routing_resolved` | Successful resolution to an agent_view |
| `agento_routing_ambiguous` | Multiple routers matched (first still wins) |
| `agento_routing_failed` | No router matched |

All events carry the full `RoutingContext` for observability.

## Post-MVP: Semantic Router

A future semantic router could use LLM-based matching to route requests based on agent competence descriptions rather than explicit identity bindings. This is documented as post-MVP — the identity router covers deterministic use cases first.

## Source Files

| Component | File |
|-----------|------|
| Router protocol & chain | [src/agento/framework/router.py](../../src/agento/framework/router.py) |
| Router registry | [src/agento/framework/router_registry.py](../../src/agento/framework/router_registry.py) |
| Ingress identity model | [src/agento/framework/ingress_identity.py](../../src/agento/framework/ingress_identity.py) |
| Identity router | [src/agento/modules/core/src/routers/identity_router.py](../../src/agento/modules/core/src/routers/identity_router.py) |
| Routing events | [src/agento/framework/events.py](../../src/agento/framework/events.py) |
| DB migration | [src/agento/framework/sql/015_ingress_identity.sql](../../src/agento/framework/sql/015_ingress_identity.sql) |
