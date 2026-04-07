from copy import deepcopy
from datetime import datetime, timedelta, timezone

from services.handoff_inbox_models import HandoffInboxMessageSender, HandoffInboxOutboxStatus
from services.handoff_inbox_service import HandoffInboxService


class MutableClock:
    def __init__(self, current: datetime):
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> datetime:
        self.current = self.current + timedelta(**kwargs)
        return self.current


def _empty_doc_record():
    return {"__data__": None, "__subcollections__": {}}


class FakeSnapshot:
    def __init__(self, collection_storage, doc_id):
        self.id = doc_id
        self._collection_storage = collection_storage
        self._doc_id = doc_id
        doc_record = collection_storage.get(doc_id)
        self.exists = bool(doc_record and doc_record.get("__data__") is not None)
        self.reference = FakeDocumentReference(collection_storage, doc_id)

    def to_dict(self):
        doc_record = self._collection_storage.get(self._doc_id) or _empty_doc_record()
        payload = doc_record.get("__data__")
        return deepcopy(payload) if payload is not None else None


class FakeDocumentReference:
    def __init__(self, collection_storage, doc_id):
        self._collection_storage = collection_storage
        self._doc_id = doc_id

    def _doc_record(self):
        return self._collection_storage.setdefault(self._doc_id, _empty_doc_record())

    def set(self, payload):
        self._doc_record()["__data__"] = deepcopy(payload)

    def create(self, payload):
        existing = self._collection_storage.get(self._doc_id)
        if existing and existing.get("__data__") is not None:
            raise RuntimeError("exists")
        self.set(payload)

    def get(self):
        return FakeSnapshot(self._collection_storage, self._doc_id)

    def delete(self):
        self._collection_storage.pop(self._doc_id, None)

    def collection(self, name):
        subcollections = self._doc_record()["__subcollections__"]
        return FakeCollectionReference(subcollections, name)


class FakeCollectionReference:
    def __init__(self, root_storage, name):
        self._root_storage = root_storage
        self._name = name

    def _collection_storage(self):
        return self._root_storage.setdefault(self._name, {})

    def document(self, doc_id):
        return FakeDocumentReference(self._collection_storage(), doc_id)

    def stream(self):
        collection = self._collection_storage()
        snapshots = [
            FakeSnapshot(collection, doc_id)
            for doc_id, payload in collection.items()
            if payload.get("__data__") is not None
        ]
        snapshots.sort(key=lambda item: item.id)
        return snapshots


class FakeFirestoreClient:
    def __init__(self, database="(default)"):
        self.database = database
        self._collections = {}

    def collection(self, name):
        return FakeCollectionReference(self._collections, name)


def _build_service(clock: MutableClock) -> HandoffInboxService:
    return HandoffInboxService(
        firestore_client=FakeFirestoreClient("(default)"),
        now_fn=clock,
    )


def test_create_or_get_case_orders_active_and_queued():
    clock = MutableClock(datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc))
    service = _build_service(clock)

    first = service.create_or_get_case(
        client_phone="+5491111111111",
        client_name="Ana",
        tipo_consulta="presupuesto",
        handoff_context="Necesito ayuda con matafuegos",
    )
    clock.advance(seconds=1)
    second = service.create_or_get_case(
        client_phone="+5491222222222",
        client_name="Beto",
        tipo_consulta="urgencia",
        handoff_context="Tengo una consulta urgente",
    )
    same_first = service.create_or_get_case(
        client_phone="+5491111111111",
        client_name="Ana",
        tipo_consulta="presupuesto",
        handoff_context="Necesito ayuda con matafuegos",
    )

    assert first.is_active is True
    assert first.queue_position == 1
    assert second.is_active is False
    assert second.queue_position == 2
    assert same_first.case_id == first.case_id

    cases = service.list_cases()
    assert [item.client_phone for item in cases] == ["+5491111111111", "+5491222222222"]


def test_append_message_persists_history_and_case_projection():
    clock = MutableClock(datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc))
    service = _build_service(clock)
    case = service.create_or_get_case(
        client_phone="+5491333333333",
        client_name="Carla",
        tipo_consulta="otras",
        handoff_context="Quiero hablar con un humano",
    )

    clock.advance(minutes=1)
    service.append_message(
        case.case_id,
        sender=HandoffInboxMessageSender.CLIENT,
        text="Necesito hablar con una persona",
        source_message_id="wamid-client-1",
    )
    clock.advance(minutes=1)
    service.append_message(
        case.case_id,
        sender=HandoffInboxMessageSender.AGENT,
        text="Claro, te ayudo por este medio",
    )

    detail = service.get_case_detail(case.case_id)
    projection = service.get_open_case_for_client("+5491333333333")

    assert [item.text for item in detail.messages] == [
        "Necesito hablar con una persona",
        "Claro, te ayudo por este medio",
    ]
    assert detail.messages[0].source_message_id == "wamid-client-1"
    assert projection is not None
    assert projection.last_client_message_at is not None
    assert projection.last_agent_message_at is not None
    assert projection.has_unread is True


def test_close_case_promotes_next_and_advance_next_rotates_queue():
    clock = MutableClock(datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc))
    service = _build_service(clock)

    case_1 = service.create_or_get_case(
        client_phone="+5491444444444",
        client_name="Dani",
        tipo_consulta="presupuesto",
        handoff_context="caso 1",
    )
    clock.advance(seconds=1)
    case_2 = service.create_or_get_case(
        client_phone="+5491555555555",
        client_name="Ema",
        tipo_consulta="presupuesto",
        handoff_context="caso 2",
    )
    clock.advance(seconds=1)
    case_3 = service.create_or_get_case(
        client_phone="+5491666666666",
        client_name="Feli",
        tipo_consulta="urgencia",
        handoff_context="caso 3",
    )

    service.close_case(case_1.case_id)
    after_close = service.list_cases()
    assert [item.client_phone for item in after_close] == ["+5491555555555", "+5491666666666"]
    assert after_close[0].is_active is True

    promoted = service.advance_next()
    assert promoted is not None
    assert promoted.client_phone == "+5491666666666"
    assert promoted.is_active is True

    after_advance = service.list_cases()
    assert [item.client_phone for item in after_advance] == ["+5491666666666", "+5491555555555"]
    assert case_2.case_id != case_3.case_id


def test_autoclose_and_purge_closed_case_history():
    clock = MutableClock(datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc))
    fake_client = FakeFirestoreClient("(default)")
    service = HandoffInboxService(
        firestore_client=fake_client,
        now_fn=clock,
    )
    case = service.create_or_get_case(
        client_phone="+5491777777777",
        client_name="Gabi",
        tipo_consulta="urgencia",
        handoff_context="caso viejo",
    )
    service.take_case(case.case_id, owner_email="agente@example.com")
    service.create_outbox_record(
        case.case_id,
        owner_email="agente@example.com",
        text="Hola, ya te atiendo",
    )
    service.append_message(
        case.case_id,
        sender=HandoffInboxMessageSender.CLIENT,
        text="Necesito ayuda urgente",
    )
    service.append_message(
        case.case_id,
        sender=HandoffInboxMessageSender.AGENT,
        text="Estoy revisando tu caso",
        delivery_status=HandoffInboxOutboxStatus.SENT,
    )

    clock.advance(hours=2)
    dry_run = service.auto_close_inactive_cases(dry_run=True, inactivity_minutes=60, batch_limit=10)
    assert dry_run.cases_eligible == 1
    assert dry_run.cases_closed == 0

    closed = service.auto_close_inactive_cases(dry_run=False, inactivity_minutes=60, batch_limit=10)
    assert closed.cases_closed == 1
    assert service.get_open_case_for_client("+5491777777777") is None

    clock.advance(days=10)
    purge = service.purge_closed_case_history(
        dry_run=False,
        batch_limit=10,
        messages_days=3,
        outbox_days=3,
        cases_days=7,
    )

    assert purge.cases_deleted == 1
    assert purge.messages_deleted == 2
    assert purge.outbox_deleted == 1
    assert list(fake_client.collection(service.collection_name).stream()) == []
