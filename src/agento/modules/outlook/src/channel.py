from __future__ import annotations

import hashlib
import logging
import re

from agento.framework.agent_view_runtime import resolve_publish_priority
from agento.framework.channels.base import PromptFragments
from agento.framework.db import get_connection
from agento.framework.job_models import AgentType, JobRequester, RequesterTrust
from agento.framework.publisher import publish
from agento.framework.router import RoutingContext, resolve_agent_view


def _matches_allowed(sender: str, allowed_senders: list[str] | None) -> bool:
    """Reproduce core's ``matchesWhitelist`` semantics (email.js).

    Each pattern is anchored (``^...$``), case-insensitive (caller passes a lowered sender),
    and ``*`` expands to ``[^@]*`` so ``*@kazar.com`` matches any local part but never crosses
    the ``@``. An empty/None allow-list matches nothing (fail-closed).
    """
    if not allowed_senders:
        return False
    for pattern in allowed_senders:
        escaped = re.sub(r"[.+^${}()|[\]\\]", r"\\\g<0>", pattern.lower())
        regex = "^" + escaped.replace("*", "[^@]*") + "$"
        if re.match(regex, sender):
            return True
    return False


class OutlookPromptChannel:
    """Channel concern: Polish prompt fragments for email tasks."""

    @property
    def name(self) -> str:
        return "outlook"

    def get_prompt_fragments(self, reference_id: str) -> PromptFragments:
        return PromptFragments(
            read_context=(
                f"Użyj outlook_get_message aby pobrać treść emaila o message_id: {reference_id}.\n"
                "Zapamiętaj: temat, nadawcę, treść, datę otrzymania."
            ),
            respond="Wynik odeślij odpowiadając na email (outlook_reply z message_id i treścią odpowiedzi).",
            transition_done="Oznacz email jako przetworzony (outlook_mark_processed z message_id).",
            ask_and_handback=(
                "Jeśli masz pytania lub wątpliwości:\n"
                "  a) Odpowiedz na email z pytaniami (outlook_reply).\n"
                "  b) ZAKOŃCZ — nie wykonuj dalszych kroków.\n"
                "Jeśli wcześniej zadałeś pytania i nie ma odpowiedzi: ZAKOŃCZ."
            ),
        )

    def get_followup_fragments(self, reference_id: str, instructions: str) -> PromptFragments:
        return PromptFragments(
            read_context=(
                f"Wczytaj email (outlook_get_message) — sprawdź obecny stan i kontekst. "
                f"Message ID: {reference_id}."
            ),
            respond="Wynik zwróć odpowiadając na email (outlook_reply).",
            transition_done="Oznacz email jako przetworzony (outlook_mark_processed).",
            extra=(
                "KONTEKST — instrukcje z momentu planowania:\n"
                "---\n"
                f"{instructions}\n"
                "---"
            ),
        )


class OutlookPublisher:
    """Publisher concern: enforce the inbound security gate, route by sender, publish one job/email."""

    @property
    def name(self) -> str:
        return "outlook"

    def build_idempotency_key(self, message_id: str) -> str:
        return f"outlook:mail:{message_id}"

    def _resolve_routing(
        self, db_config: object, sender_email: str | None,
        logger: logging.Logger | None = None,
    ) -> tuple[int | None, int]:
        try:
            conn = get_connection(db_config)
        except Exception:
            return None, 50
        try:
            ctx = RoutingContext(
                channel="outlook",
                workflow_type="todo",
                identity_type="email",
                identity_value=(sender_email or "").strip().lower(),
                payload={},
            )
            decision = resolve_agent_view(conn, ctx)
            if decision is None:
                return None, 50
            return decision.agent_view_id, resolve_publish_priority(conn, decision.agent_view_id)
        except Exception:
            if logger:
                logger.warning("Routing lookup failed; treating as unrouted (email left unread)", exc_info=True)
            return None, 50
        finally:
            conn.close()

    def publish_mail(
        self, db_config: object, message_id: str, sender_email: str | None = None,
        dmarc: str | None = None, allowed_senders: list[str] | None = None,
        require_dmarc: bool = True, logger: logging.Logger | None = None,
    ) -> bool:
        # 1. Normalize the claimed From address.
        sender = (sender_email or "").strip().lower()

        # 2. ALLOWED-SENDERS GATE (fail-closed). A sender that does not match is ordinary
        #    non-routing — NOT a breach. Log the domain only (the local part of an unauthorized
        #    external address is PII we never need), leave the email unread.
        if not _matches_allowed(sender, allowed_senders):
            if logger:
                sender_domain = sender.split("@")[-1] if "@" in sender else "?"
                logger.info(
                    "Outlook sender not in allowed_senders; leaving unread",
                    extra={"message_id": message_id[:40], "sender_domain": sender_domain},
                )
            return False

        # 3. DMARC GATE. A whitelisted identity that fails (or lacks a confirmed) DMARC pass is a
        #    probable SPOOF — log a SECURITY BREACH (greppable marker + structured fields) and do
        #    NOT publish. Capturing the full claimed From is justified for a flagged spoof.
        if require_dmarc and (dmarc or "").lower() != "pass":
            if logger:
                logger.error(
                    "SECURITY_BREACH: whitelisted outlook sender failed DMARC (probable spoof)",
                    extra={
                        "event": "security_breach",
                        "reason": "dmarc_not_pass",
                        "sender": sender,
                        "dmarc": dmarc,
                        "message_id": message_id[:40],
                    },
                )
            return False

        # 4. ROUTE. Authorized + DMARC-passed, but routing is still required (fail-closed): an
        #    unrouted external job would execute at global scope and the stable idempotency key
        #    would permanently block a later re-route. Leave unread for re-evaluation.
        agent_view_id, priority = self._resolve_routing(db_config, sender, logger)
        if agent_view_id is None:
            if logger:
                logger.warning(
                    "Authorized outlook sender has no agent_view route; leaving unread "
                    "(operator must ingress:bind email <sender> <agent_view>)",
                    extra={"message_id": message_id[:40]},
                )
            return False

        # 5. PUBLISH. DMARC pass cryptographically aligns the From domain -> trust=DOMAIN.
        normalized = sender
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        requester = JobRequester(
            key=f"outlook:email:{digest}",  # 14 + 64 = 78 chars, always < 255
            email=sender_email,  # JobRequester normalizes (strip+lower)
            trust=RequesterTrust.DOMAIN,
            meta={"basis": "email_from", "dmarc": "pass"},
        )
        return publish(
            db_config, AgentType.TODO, self.name,
            self.build_idempotency_key(message_id),
            reference_id=message_id, logger=logger,
            agent_view_id=agent_view_id, priority=priority,
            skip_if_active=True, requester=requester,
        )

    # Publisher protocol shims (the framework Publisher protocol expects these names).
    def publish_todo(self, config: object, reference_id: str | None = None, **kwargs) -> bool:
        if not reference_id:
            raise ValueError("outlook publish_todo requires a reference_id (message_id)")
        return self.publish_mail(
            config, reference_id,
            sender_email=kwargs.get("sender_email"),
            dmarc=kwargs.get("dmarc"),
            allowed_senders=kwargs.get("allowed_senders"),
            require_dmarc=kwargs.get("require_dmarc", True),
            logger=kwargs.get("logger"),
        )

    def publish_cron(self, config: object, reference_id: str, **kwargs) -> bool:
        raise NotImplementedError("outlook channel does not support cron publishing")


class OutlookChannel(OutlookPromptChannel, OutlookPublisher):
    """Facade combining the prompt + publisher concerns for the outlook channel."""

    pass
