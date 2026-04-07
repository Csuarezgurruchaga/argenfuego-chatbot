from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.handoff_inbox_models import HandoffInboxMessageSender, HandoffInboxOutboxStatus
from services.handoff_inbox_service import (
    HandoffInboxClosedCaseError,
    HandoffInboxConflictError,
    HandoffInboxNotFoundError,
    handoff_inbox_service,
)
from services.meta_whatsapp_service import meta_whatsapp_service


@dataclass(frozen=True)
class HandoffInboxReplyResult:
    case_id: str
    client_phone: str
    owner_email: str
    sent: bool
    outbox_id: str
    error_message: Optional[str] = None


class HandoffInboxReplyService:
    def __init__(self, *, inbox_service=None, sender=None) -> None:
        self._inbox_service = inbox_service or handoff_inbox_service
        self._sender = sender or meta_whatsapp_service.send_text_message

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            raise ValueError("Reply text cannot be empty")
        return normalized

    def send_reply(
        self,
        *,
        case_id: str,
        owner_email: str,
        text: str,
        client_local_id: Optional[str] = None,
    ) -> HandoffInboxReplyResult:
        normalized_text = self._normalize_text(text)
        case = self._inbox_service.take_case(case_id, owner_email=owner_email)
        outbox = self._inbox_service.create_outbox_record(
            case_id,
            owner_email=case.owner_email or owner_email,
            text=normalized_text,
        )

        try:
            sent = bool(self._sender(case.client_phone, normalized_text))
        except Exception as exc:
            sent = False
            error_message = str(exc)
        else:
            error_message = None if sent else "send failed"

        if sent:
            self._inbox_service.update_outbox_status(
                case_id,
                outbox.outbox_id,
                status=HandoffInboxOutboxStatus.SENT,
            )
            self._inbox_service.append_message(
                case_id,
                sender=HandoffInboxMessageSender.AGENT,
                text=normalized_text,
                delivery_status=HandoffInboxOutboxStatus.SENT,
                client_local_id=client_local_id,
            )
            return HandoffInboxReplyResult(
                case_id=case_id,
                client_phone=case.client_phone,
                owner_email=case.owner_email or owner_email,
                sent=True,
                outbox_id=outbox.outbox_id,
            )

        self._inbox_service.update_outbox_status(
            case_id,
            outbox.outbox_id,
            status=HandoffInboxOutboxStatus.FAILED,
            error_message=error_message,
        )
        self._inbox_service.append_message(
            case_id,
            sender=HandoffInboxMessageSender.AGENT,
            text=normalized_text,
            delivery_status=HandoffInboxOutboxStatus.FAILED,
            client_local_id=client_local_id,
        )
        return HandoffInboxReplyResult(
            case_id=case_id,
            client_phone=case.client_phone,
            owner_email=case.owner_email or owner_email,
            sent=False,
            outbox_id=outbox.outbox_id,
            error_message=error_message,
        )


handoff_inbox_reply_service = HandoffInboxReplyService()
