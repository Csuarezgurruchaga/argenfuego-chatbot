from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Optional
from uuid import uuid4

from services.handoff_inbox_models import (
    HandoffInboxAutocloseCaseRecord,
    HandoffInboxAutocloseResult,
    HandoffInboxCaseDetail,
    HandoffInboxCaseProjection,
    HandoffInboxCaseRecord,
    HandoffInboxCaseStatus,
    HandoffInboxChannel,
    HandoffInboxLastMessageFrom,
    HandoffInboxMessageRecord,
    HandoffInboxMessageSender,
    HandoffInboxOutboxRecord,
    HandoffInboxOutboxStatus,
    HandoffInboxRetentionCutoffs,
    HandoffInboxRetentionResult,
    HandoffInboxSummary,
)

try:
    from google.cloud import firestore
except Exception:
    firestore = None


logger = logging.getLogger(__name__)


class HandoffInboxConflictError(ValueError):
    pass


class HandoffInboxNotFoundError(KeyError):
    pass


class HandoffInboxClosedCaseError(ValueError):
    pass


class HandoffInboxService:
    def __init__(
        self,
        *,
        collection_name: Optional[str] = None,
        messages_subcollection_name: str = "messages",
        outbox_subcollection_name: str = "outbox",
        database: Optional[str] = None,
        firestore_client=None,
        now_fn=None,
        case_id_factory=None,
        message_id_factory=None,
        outbox_id_factory=None,
    ) -> None:
        self.collection_name = (
            collection_name or os.getenv("HANDOFF_INBOX_CASES_COLLECTION", "handoff_inbox_cases")
        ).strip() or "handoff_inbox_cases"
        self.messages_subcollection_name = messages_subcollection_name.strip() or "messages"
        self.outbox_subcollection_name = outbox_subcollection_name.strip() or "outbox"
        self.database = (
            database or os.getenv("CHATBOT_FIRESTORE_DATABASE", "(default)")
        ).strip() or "(default)"
        if self.database == "default":
            self.database = "(default)"
        self._firestore_client = firestore_client
        self._now_fn = now_fn or self._utc_now
        self._case_id_factory = case_id_factory or self._build_case_id
        self._message_id_factory = message_id_factory or self._build_message_id
        self._outbox_id_factory = outbox_id_factory or self._build_outbox_id

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _build_case_id() -> str:
        return f"case-{uuid4().hex}"

    @staticmethod
    def _build_message_id() -> str:
        return f"msg-{uuid4().hex}"

    @staticmethod
    def _build_outbox_id() -> str:
        return f"outbox-{uuid4().hex}"

    def _get_firestore_client(self):
        if self._firestore_client is not None:
            return self._firestore_client
        if firestore is None:
            raise RuntimeError("google-cloud-firestore not installed")
        self._firestore_client = firestore.Client(database=self.database)
        return self._firestore_client

    def _cases_collection(self):
        return self._get_firestore_client().collection(self.collection_name)

    def _messages_collection(self, case_id: str):
        return self._cases_collection().document(case_id).collection(self.messages_subcollection_name)

    def _outbox_collection(self, case_id: str):
        return self._cases_collection().document(case_id).collection(self.outbox_subcollection_name)

    @staticmethod
    def _snapshot_payload(snapshot) -> Optional[dict]:
        if snapshot is None:
            return None
        if hasattr(snapshot, "exists") and not snapshot.exists:
            return None
        payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else None
        if not payload:
            return None
        return payload

    @staticmethod
    def _normalize_owner_email(owner_email: Optional[str]) -> Optional[str]:
        if owner_email is None:
            return None
        text = owner_email.strip().lower()
        return text or None

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        return (text or "").strip()

    def _build_message_record(
        self,
        *,
        sender: HandoffInboxMessageSender,
        text: str,
        delivery_status: Optional[HandoffInboxOutboxStatus] = None,
        created_at: Optional[datetime] = None,
        message_id: Optional[str] = None,
        client_local_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> HandoffInboxMessageRecord:
        if not isinstance(sender, HandoffInboxMessageSender):
            sender = HandoffInboxMessageSender(str(sender))
        now = created_at or self._now_fn()
        return HandoffInboxMessageRecord.model_validate(
            {
                "message_id": message_id or self._message_id_factory(),
                "client_local_id": self._normalize_text(client_local_id) or None,
                "source_message_id": self._normalize_text(source_message_id) or None,
                "sender": sender,
                "channel": HandoffInboxChannel.WHATSAPP,
                "text": self._normalize_text(text),
                "created_at": now,
                "updated_at": now,
                "delivery_status": delivery_status,
            }
        )

    @staticmethod
    def _create_document_if_absent(document_ref, payload: dict) -> bool:
        create_method = getattr(document_ref, "create", None)
        if callable(create_method):
            try:
                create_method(payload)
            except Exception as exc:
                if exc.__class__.__name__ in {"AlreadyExists", "Conflict"}:
                    return False
                raise
            return True
        snapshot = document_ref.get()
        if HandoffInboxService._snapshot_payload(snapshot) is not None:
            return False
        document_ref.set(payload)
        return True

    def _update_case_after_message(self, case_id: str, message: HandoffInboxMessageRecord) -> None:
        record = self._load_case_record(case_id)
        sender_value = getattr(message.sender, "value", message.sender)
        now = message.created_at
        update_payload = {
            "updated_at": now,
            "last_interaction_at": now,
            "last_message_from": HandoffInboxLastMessageFrom(str(sender_value)),
        }
        if sender_value == HandoffInboxMessageSender.CLIENT.value:
            update_payload["has_unread"] = True
            update_payload["last_client_message_at"] = now
        elif sender_value == HandoffInboxMessageSender.AGENT.value:
            update_payload["last_agent_message_at"] = now
        updated_case = record.model_copy(update=update_payload)
        self._persist_case(updated_case)

    def _write_message_record(
        self,
        case_id: str,
        message: HandoffInboxMessageRecord,
        *,
        update_case: bool = True,
    ) -> HandoffInboxMessageRecord:
        self._messages_collection(case_id).document(message.message_id).set(message.model_dump(mode="json"))
        if update_case:
            self._update_case_after_message(case_id, message)
        return message

    def _persist_case(self, record: HandoffInboxCaseRecord) -> HandoffInboxCaseRecord:
        record = record.model_copy(update={"last_interaction_at": self._derive_case_last_interaction_at(record)})
        self._cases_collection().document(record.case_id).set(record.model_dump(mode="json"))
        return record

    @staticmethod
    def _delete_document(document_ref) -> None:
        document_ref.delete()

    def _load_case_record(self, case_id: str, *, raise_if_missing: bool = True) -> Optional[HandoffInboxCaseRecord]:
        snapshot = self._cases_collection().document(case_id).get()
        payload = self._snapshot_payload(snapshot)
        if payload is None:
            if raise_if_missing:
                raise HandoffInboxNotFoundError(f"Handoff inbox case not found: {case_id}")
            return None
        return HandoffInboxCaseRecord.model_validate(payload)

    def _list_case_records(self) -> list[HandoffInboxCaseRecord]:
        records = []
        for snapshot in self._cases_collection().stream():
            payload = self._snapshot_payload(snapshot)
            if payload is None:
                continue
            records.append(HandoffInboxCaseRecord.model_validate(payload))
        return records

    def _list_open_case_records(self) -> list[HandoffInboxCaseRecord]:
        records = [record for record in self._list_case_records() if record.status != HandoffInboxCaseStatus.CLOSED]
        active = [record for record in records if record.status == HandoffInboxCaseStatus.ACTIVE]
        queued = [record for record in records if record.status == HandoffInboxCaseStatus.QUEUED]
        active.sort(key=lambda item: (item.created_at, item.case_id))
        queued.sort(key=lambda item: (item.created_at, item.case_id))
        return active + queued

    @staticmethod
    def _derive_case_last_interaction_at(record: HandoffInboxCaseRecord) -> datetime:
        candidates = [record.created_at]
        if record.last_client_message_at is not None:
            candidates.append(record.last_client_message_at)
        if record.last_agent_message_at is not None:
            candidates.append(record.last_agent_message_at)
        return max(candidates)

    @classmethod
    def _case_last_interaction_at(cls, record: HandoffInboxCaseRecord) -> datetime:
        if getattr(record, "last_interaction_at", None) is not None:
            return record.last_interaction_at
        return cls._derive_case_last_interaction_at(record)

    def _project_case(
        self,
        record: HandoffInboxCaseRecord,
        *,
        ordered_open_case_ids: Optional[list[str]] = None,
    ) -> HandoffInboxCaseProjection:
        queue_position = None
        if record.status != HandoffInboxCaseStatus.CLOSED and ordered_open_case_ids is not None:
            try:
                queue_position = ordered_open_case_ids.index(record.case_id) + 1
            except ValueError:
                queue_position = None
        return HandoffInboxCaseProjection.model_validate(
            {
                **record.model_dump(mode="python"),
                "is_active": record.status == HandoffInboxCaseStatus.ACTIVE,
                "queue_position": queue_position,
            }
        )

    def _iter_case_messages(self, case_id: str) -> list[HandoffInboxMessageRecord]:
        messages = []
        for snapshot in self._messages_collection(case_id).stream():
            payload = self._snapshot_payload(snapshot)
            if payload is None:
                continue
            messages.append(HandoffInboxMessageRecord.model_validate(payload))
        return messages

    def _iter_case_outbox(self, case_id: str) -> list[HandoffInboxOutboxRecord]:
        outbox_records = []
        for snapshot in self._outbox_collection(case_id).stream():
            payload = self._snapshot_payload(snapshot)
            if payload is None:
                continue
            outbox_records.append(HandoffInboxOutboxRecord.model_validate(payload))
        return outbox_records

    def _promote_oldest_queued_case(self) -> Optional[HandoffInboxCaseRecord]:
        queued_cases = [
            record
            for record in self._list_case_records()
            if record.status == HandoffInboxCaseStatus.QUEUED
        ]
        queued_cases.sort(key=lambda item: (item.created_at, item.case_id))
        if not queued_cases:
            return None
        now = self._now_fn()
        next_case = queued_cases[0].model_copy(
            update={
                "status": HandoffInboxCaseStatus.ACTIVE,
                "updated_at": now,
            }
        )
        return self._persist_case(next_case)

    def get_open_case_for_client(self, client_phone: str) -> Optional[HandoffInboxCaseProjection]:
        normalized_phone = self._normalize_text(client_phone)
        ordered = self._list_open_case_records()
        ordered_ids = [record.case_id for record in ordered]
        for record in ordered:
            if record.client_phone == normalized_phone:
                return self._project_case(record, ordered_open_case_ids=ordered_ids)
        return None

    def create_or_get_case(
        self,
        *,
        client_phone: str,
        client_name: Optional[str],
        tipo_consulta: Optional[str],
        handoff_context: Optional[str],
    ) -> HandoffInboxCaseProjection:
        existing = self.get_open_case_for_client(client_phone)
        if existing is not None:
            return existing

        now = self._now_fn()
        has_active_case = any(
            record.status == HandoffInboxCaseStatus.ACTIVE for record in self._list_case_records()
        )
        status = HandoffInboxCaseStatus.QUEUED if has_active_case else HandoffInboxCaseStatus.ACTIVE
        record = HandoffInboxCaseRecord.model_validate(
            {
                "case_id": self._case_id_factory(),
                "client_phone": self._normalize_text(client_phone),
                "client_name": self._normalize_text(client_name) or None,
                "tipo_consulta": self._normalize_text(tipo_consulta) or None,
                "status": status,
                "handoff_context": self._normalize_text(handoff_context) or None,
                "created_at": now,
                "last_interaction_at": now,
                "updated_at": now,
            }
        )
        self._persist_case(record)
        ordered = self._list_open_case_records()
        return self._project_case(record, ordered_open_case_ids=[item.case_id for item in ordered])

    def list_cases(self, *, limit: int = 50) -> list[HandoffInboxCaseProjection]:
        ordered = self._list_open_case_records()
        ordered_ids = [record.case_id for record in ordered]
        return [
            self._project_case(record, ordered_open_case_ids=ordered_ids)
            for record in ordered[:limit]
        ]

    def get_summary(self) -> HandoffInboxSummary:
        records = self._list_case_records()
        open_records = [record for record in records if record.status != HandoffInboxCaseStatus.CLOSED]
        updated_candidates = [record.updated_at for record in open_records]
        return HandoffInboxSummary(
            total_open_cases=len(open_records),
            active_count=sum(1 for record in open_records if record.status == HandoffInboxCaseStatus.ACTIVE),
            queued_count=sum(1 for record in open_records if record.status == HandoffInboxCaseStatus.QUEUED),
            unread_count=sum(1 for record in open_records if record.has_unread),
            updated_at=max(updated_candidates) if updated_candidates else None,
        )

    def append_message(
        self,
        case_id: str,
        *,
        sender: HandoffInboxMessageSender,
        text: str,
        delivery_status: Optional[HandoffInboxOutboxStatus] = None,
        created_at: Optional[datetime] = None,
        message_id: Optional[str] = None,
        client_local_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> HandoffInboxMessageRecord:
        record = self._load_case_record(case_id)
        if record.status == HandoffInboxCaseStatus.CLOSED:
            raise HandoffInboxClosedCaseError(f"Cannot append message to closed case: {case_id}")
        message = self._build_message_record(
            sender=sender,
            text=text,
            delivery_status=delivery_status,
            created_at=created_at,
            message_id=message_id,
            client_local_id=client_local_id,
            source_message_id=source_message_id,
        )
        return self._write_message_record(case_id, message, update_case=True)

    @staticmethod
    def _message_cursor_value(message: HandoffInboxMessageRecord) -> datetime:
        return getattr(message, "updated_at", None) or message.created_at

    @classmethod
    def _message_cursor_sort_key(cls, message: HandoffInboxMessageRecord) -> tuple[datetime, datetime, str]:
        return (
            cls._message_cursor_value(message),
            message.created_at,
            message.message_id,
        )

    def get_case_detail(
        self,
        case_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> HandoffInboxCaseDetail:
        record = self._load_case_record(case_id)
        ordered = self._list_open_case_records()
        projection = self._project_case(record, ordered_open_case_ids=[item.case_id for item in ordered])
        messages = []
        for snapshot in self._messages_collection(case_id).stream():
            payload = self._snapshot_payload(snapshot)
            if payload is None:
                continue
            message = HandoffInboxMessageRecord.model_validate(payload)
            if since is not None and self._message_cursor_value(message) <= since:
                continue
            messages.append(message)
        if since is not None:
            messages.sort(key=self._message_cursor_sort_key)
            trimmed_messages = messages[:limit]
            next_cursor = self._message_cursor_value(trimmed_messages[-1]) if trimmed_messages else since
            trimmed_messages.sort(key=lambda item: (item.created_at, item.message_id))
        else:
            messages.sort(key=lambda item: (item.created_at, item.message_id))
            trimmed_messages = messages[:limit]
            next_cursor = (
                max(self._message_cursor_value(message) for message in trimmed_messages)
                if trimmed_messages
                else since
            )
        return HandoffInboxCaseDetail(case=projection, messages=trimmed_messages, next_cursor=next_cursor)

    def purge_closed_case_history(
        self,
        *,
        dry_run: bool = True,
        batch_limit: Optional[int] = None,
        messages_days: Optional[int] = None,
        outbox_days: Optional[int] = None,
        cases_days: Optional[int] = None,
    ) -> HandoffInboxRetentionResult:
        now = self._now_fn()
        messages_days = int(messages_days or os.getenv("HANDOFF_RETENTION_MESSAGES_DAYS", "3"))
        outbox_days = int(outbox_days or os.getenv("HANDOFF_RETENTION_OUTBOX_DAYS", "3"))
        cases_days = int(cases_days or os.getenv("HANDOFF_RETENTION_CASES_DAYS", "7"))
        resolved_batch_limit = int(batch_limit or os.getenv("HANDOFF_RETENTION_BATCH_LIMIT", "100"))
        resolved_batch_limit = max(1, resolved_batch_limit)
        cutoffs = HandoffInboxRetentionCutoffs(
            messages_before=now - timedelta(days=messages_days),
            outbox_before=now - timedelta(days=outbox_days),
            cases_before=now - timedelta(days=cases_days),
        )
        result = HandoffInboxRetentionResult(
            dry_run=dry_run,
            batch_limit=resolved_batch_limit,
            cutoffs=cutoffs,
        )

        closed_records = [
            record for record in self._list_case_records()
            if record.status == HandoffInboxCaseStatus.CLOSED
        ]
        closed_records.sort(
            key=lambda item: (
                item.closed_at or datetime.max.replace(tzinfo=timezone.utc),
                item.case_id,
            )
        )

        for record in closed_records:
            if result.cases_scanned >= resolved_batch_limit:
                break
            result.cases_scanned += 1
            if record.closed_at is None:
                result.cases_skipped_missing_closed_at += 1
                continue

            delete_case = record.closed_at <= cutoffs.cases_before
            self._purge_case_messages(
                record.case_id,
                cutoffs.messages_before,
                result,
                dry_run=dry_run,
                delete_all=delete_case,
            )
            self._purge_case_outbox(
                record.case_id,
                cutoffs.outbox_before,
                result,
                dry_run=dry_run,
                delete_all=delete_case,
            )

            if delete_case:
                if not dry_run:
                    self._delete_document(self._cases_collection().document(record.case_id))
                result.cases_deleted += 1

        return result

    def auto_close_inactive_cases(
        self,
        *,
        dry_run: bool = True,
        batch_limit: Optional[int] = None,
        inactivity_minutes: Optional[int] = None,
    ) -> HandoffInboxAutocloseResult:
        now = self._now_fn()
        inactivity_minutes = int(inactivity_minutes or os.getenv("HANDOFF_INACTIVITY_MINUTES", "60"))
        resolved_batch_limit = int(batch_limit or os.getenv("HANDOFF_AUTOCLOSE_BATCH_LIMIT", "100"))
        resolved_batch_limit = max(1, resolved_batch_limit)
        cutoff_before = now - timedelta(minutes=inactivity_minutes)
        result = HandoffInboxAutocloseResult(
            dry_run=dry_run,
            batch_limit=resolved_batch_limit,
            cutoff_before=cutoff_before,
        )

        open_records = [
            record
            for record in self._list_case_records()
            if record.status != HandoffInboxCaseStatus.CLOSED
        ]
        open_records.sort(key=lambda item: (self._case_last_interaction_at(item), item.created_at, item.case_id))

        for current in open_records:
            if result.cases_scanned >= resolved_batch_limit:
                break
            result.cases_scanned += 1

            last_interaction_at = self._case_last_interaction_at(current)
            if last_interaction_at > cutoff_before:
                continue

            eligible_case = HandoffInboxAutocloseCaseRecord.model_validate(
                {
                    "case_id": current.case_id,
                    "client_phone": current.client_phone,
                    "prior_status": current.status,
                    "last_client_message_at": current.last_client_message_at,
                    "last_agent_message_at": current.last_agent_message_at,
                    "created_at": current.created_at,
                    "last_interaction_at": last_interaction_at,
                }
            )
            result.cases_eligible += 1
            result.eligible_cases.append(eligible_case)

            if dry_run:
                continue

            try:
                self.close_case(current.case_id)
            except (HandoffInboxClosedCaseError, HandoffInboxNotFoundError):
                continue

            result.cases_closed += 1
            result.closed_cases.append(eligible_case)

        return result

    def _purge_case_messages(
        self,
        case_id: str,
        cutoff: datetime,
        result: HandoffInboxRetentionResult,
        *,
        dry_run: bool,
        delete_all: bool = False,
    ) -> None:
        for message in self._iter_case_messages(case_id):
            if not delete_all and message.created_at > cutoff:
                continue
            if not dry_run:
                self._delete_document(self._messages_collection(case_id).document(message.message_id))
            result.messages_deleted += 1

    def _purge_case_outbox(
        self,
        case_id: str,
        cutoff: datetime,
        result: HandoffInboxRetentionResult,
        *,
        dry_run: bool,
        delete_all: bool = False,
    ) -> None:
        for outbox_record in self._iter_case_outbox(case_id):
            if not delete_all and outbox_record.created_at > cutoff:
                continue
            if not dry_run:
                self._delete_document(self._outbox_collection(case_id).document(outbox_record.outbox_id))
            result.outbox_deleted += 1

    def take_case(self, case_id: str, *, owner_email: str) -> HandoffInboxCaseProjection:
        record = self._load_case_record(case_id)
        if record.status == HandoffInboxCaseStatus.CLOSED:
            raise HandoffInboxClosedCaseError(f"Cannot take closed case: {case_id}")
        normalized_owner = self._normalize_owner_email(owner_email)
        if record.owner_email and record.owner_email != normalized_owner:
            raise HandoffInboxConflictError(f"Case already owned by {record.owner_email}")
        now = self._now_fn()
        updated = record.model_copy(update={"owner_email": normalized_owner, "updated_at": now})
        self._persist_case(updated)
        ordered = self._list_open_case_records()
        return self._project_case(updated, ordered_open_case_ids=[item.case_id for item in ordered])

    def create_outbox_record(self, case_id: str, *, owner_email: str, text: str) -> HandoffInboxOutboxRecord:
        record = self._load_case_record(case_id)
        if record.status == HandoffInboxCaseStatus.CLOSED:
            raise HandoffInboxClosedCaseError(f"Cannot reply on closed case: {case_id}")
        now = self._now_fn()
        outbox = HandoffInboxOutboxRecord.model_validate(
            {
                "outbox_id": self._outbox_id_factory(),
                "case_id": case_id,
                "client_phone": record.client_phone,
                "owner_email": self._normalize_owner_email(owner_email) or "agent",
                "text": self._normalize_text(text),
                "status": HandoffInboxOutboxStatus.PENDING,
                "created_at": now,
                "updated_at": now,
            }
        )
        self._outbox_collection(case_id).document(outbox.outbox_id).set(outbox.model_dump(mode="json"))
        return outbox

    def update_outbox_status(
        self,
        case_id: str,
        outbox_id: str,
        *,
        status: HandoffInboxOutboxStatus,
        error_message: Optional[str] = None,
    ) -> HandoffInboxOutboxRecord:
        snapshot = self._outbox_collection(case_id).document(outbox_id).get()
        payload = self._snapshot_payload(snapshot)
        if payload is None:
            raise HandoffInboxNotFoundError(f"Handoff outbox record not found: {outbox_id}")
        current = HandoffInboxOutboxRecord.model_validate(payload)
        updated = current.model_copy(
            update={
                "status": status,
                "updated_at": self._now_fn(),
                "error_message": self._normalize_text(error_message) or None,
            }
        )
        self._outbox_collection(case_id).document(outbox_id).set(updated.model_dump(mode="json"))
        return updated

    def close_case(self, case_id: str, *, actor_email: Optional[str] = None) -> HandoffInboxCaseProjection:
        record = self._load_case_record(case_id)
        if record.status == HandoffInboxCaseStatus.CLOSED:
            ordered = self._list_open_case_records()
            return self._project_case(record, ordered_open_case_ids=[item.case_id for item in ordered])

        now = self._now_fn()
        updated = record.model_copy(
            update={
                "status": HandoffInboxCaseStatus.CLOSED,
                "closed_at": now,
                "updated_at": now,
                "has_unread": False,
                "owner_email": self._normalize_owner_email(actor_email) or record.owner_email,
            }
        )
        self._persist_case(updated)
        if record.status == HandoffInboxCaseStatus.ACTIVE:
            self._promote_oldest_queued_case()
        return self._project_case(updated, ordered_open_case_ids=None)

    def advance_next(self) -> Optional[HandoffInboxCaseProjection]:
        ordered = self._list_open_case_records()
        active = next((record for record in ordered if record.status == HandoffInboxCaseStatus.ACTIVE), None)
        queued = [record for record in ordered if record.status == HandoffInboxCaseStatus.QUEUED]
        if active is None:
            if queued:
                promoted = self._promote_oldest_queued_case()
                if promoted is None:
                    return None
                refreshed = self._list_open_case_records()
                return self._project_case(promoted, ordered_open_case_ids=[item.case_id for item in refreshed])
            return None
        if not queued:
            return self._project_case(active, ordered_open_case_ids=[item.case_id for item in ordered])

        now = self._now_fn()
        demoted = active.model_copy(update={"status": HandoffInboxCaseStatus.QUEUED, "updated_at": now})
        self._persist_case(demoted)
        next_queued = queued[0]
        promoted = next_queued.model_copy(update={"status": HandoffInboxCaseStatus.ACTIVE, "updated_at": self._now_fn()})
        self._persist_case(promoted)
        refreshed = self._list_open_case_records()
        return self._project_case(promoted, ordered_open_case_ids=[item.case_id for item in refreshed])


handoff_inbox_service = HandoffInboxService()
