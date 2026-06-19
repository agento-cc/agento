from __future__ import annotations

import hashlib
import logging
import re

from agento.framework.channels.base import PromptFragments
from agento.framework.event_manager import get_event_manager
from agento.framework.events import SecurityBreachEvent
from agento.framework.job_models import AgentType, JobRequester, RequesterTrust
from agento.framework.publisher import publish


def _matches_allowed(sender: str, allowed_senders: list[str] | None) -> bool:
    """Reproduce core's ``matchesWhitelist`` semantics (email.js).

    Each pattern is anchored (``^...$``), case-insensitive (caller passes a lowered sender),
    and ``*`` expands to ``[^@]*`` so ``*@mycompany.com`` matches any local part but never crosses
    the ``@``. An empty/None allow-list matches nothing (fail-closed).
    """
    if not allowed_senders:
        return False
    for pattern in allowed_senders:
        # Escape EVERY regex metachar in the literal segments (split on the glob ``*``) so a pattern
        # like ``a?b@x.com`` matches literally — never as a regex quantifier, which would WIDEN the
        # allow-list (the fail-OPEN direction). ``*`` expands to ``[^@]*`` (matches a local part but
        # never crosses the ``@``). Kept in lockstep with the JS ``matchesWhitelist`` (outlook.js).
        regex = "^" + "[^@]*".join(re.escape(seg) for seg in pattern.lower().split("*")) + "$"
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
    """Publisher concern: enforce the inbound security gate, publish one job/email to the mailbox's agent_view."""

    @property
    def name(self) -> str:
        return "outlook"

    def build_idempotency_key(self, message_id: str) -> str:
        return f"outlook:mail:{message_id}"

    def publish_mail(
        self, db_config: object, message_id: str, *, agent_view_id: int,
        priority: int = 50, sender_email: str | None = None,
        dmarc: str | None = None, allowed_senders: list[str] | None = None,
        logger: logging.Logger | None = None,
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

        # 3. DMARC GATE (unconditional — a hard DMARC pass is always required to publish). Two distinct
        #    non-pass cases, both fail-closed (never published):
        #      * EXPLICIT failure (fail/quarantine/reject) on a domain that publishes a DMARC policy is a
        #        probable SPOOF -> SECURITY_BREACH log (greppable marker + full claimed From, justified
        #        for a flagged spoof) AND an ops alert via the framework security_breach event.
        #      * Any other non-pass (none / bestguesspass / temperror / missing verdict) just means the
        #        sender's domain has no usable DMARC policy — NOT a spoof. Log info (domain only, no
        #        breach, no alert): EOP emits dmarc=bestguesspass for recordless domains on every poll,
        #        and flagging that as a breach would flood the log and dilute the marker.
        verdict = (dmarc or "").lower()
        if verdict != "pass":
            if verdict in ("fail", "quarantine", "reject"):
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
                self._alert_security_breach(message_id, sender, verdict, logger)
            elif logger:
                sender_domain = sender.split("@")[-1] if "@" in sender else "?"
                logger.info(
                    "Outlook sender has no confirmed DMARC pass; leaving unread (not a spoof)",
                    extra={"message_id": message_id[:40], "dmarc": verdict or "none",
                           "sender_domain": sender_domain},
                )
            return False

        # 4. PUBLISH to the mailbox's agent_view (the mailbox identifies the view — the publisher
        #    loop supplies agent_view_id + priority). DMARC pass cryptographically aligns the From
        #    domain -> trust=DOMAIN.
        digest = hashlib.sha256(sender.encode()).hexdigest()
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

    def _alert_security_breach(
        self, message_id: str, sender: str, dmarc: str, logger: logging.Logger | None,
    ) -> None:
        """Notify ops of a probable spoof via the framework ``security_breach_after`` event.

        Decoupled from any alert transport: app_monitor (when enabled) observes the event and emails
        ops. ``EventManager.dispatch`` swallows observer errors, so a failing alert never blocks the
        poll loop; the surrounding try/except only guards the dispatch call itself.
        """
        try:
            get_event_manager().dispatch(
                "security_breach_after",
                SecurityBreachEvent(
                    channel="outlook",
                    reason="dmarc_not_pass",
                    sender=sender,
                    reference_id=message_id,
                    detail=f"dmarc={dmarc}",
                ),
            )
        except Exception:
            if logger:
                logger.warning("Failed to dispatch security_breach event", exc_info=True)

    # Publisher protocol shims (the framework Publisher protocol expects these names).
    def publish_todo(self, config: object, reference_id: str | None = None, **kwargs) -> bool:
        if not reference_id:
            raise ValueError("outlook publish_todo requires a reference_id (message_id)")
        return self.publish_mail(
            config, reference_id,
            agent_view_id=kwargs["agent_view_id"],
            priority=kwargs.get("priority", 50),
            sender_email=kwargs.get("sender_email"),
            dmarc=kwargs.get("dmarc"),
            allowed_senders=kwargs.get("allowed_senders"),
            logger=kwargs.get("logger"),
        )

    def publish_cron(self, config: object, reference_id: str, **kwargs) -> bool:
        raise NotImplementedError("outlook channel does not support cron publishing")


class OutlookChannel(OutlookPromptChannel, OutlookPublisher):
    """Facade combining the prompt + publisher concerns for the outlook channel."""

    pass
