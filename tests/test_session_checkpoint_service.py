from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from chatbot.models import ConversacionData, DatosContacto, EstadoConversacion, TipoConsulta
from chatbot.states import ConversationManager
from services import conversation_session_service as session_module


class FakeSnapshot:
    def __init__(self, doc_id, data, collection):
        self.id = doc_id
        self._data = deepcopy(data)
        self.exists = data is not None
        self.reference = FakeDocumentReference(collection, doc_id)

    def to_dict(self):
        return deepcopy(self._data)


class FakeDocumentReference:
    def __init__(self, storage, doc_id):
        self._storage = storage
        self._doc_id = doc_id

    def set(self, payload):
        self._storage[self._doc_id] = deepcopy(payload)

    def create(self, payload):
        if self._doc_id in self._storage:
            raise session_module.AlreadyExists("exists") if session_module.AlreadyExists else RuntimeError("exists")
        self._storage[self._doc_id] = deepcopy(payload)

    def get(self):
        return FakeSnapshot(self._doc_id, self._storage.get(self._doc_id), self._storage)

    def delete(self):
        self._storage.pop(self._doc_id, None)


class FakeQuery:
    def __init__(self, storage, field_path, op_string, value):
        self._storage = storage
        self._field_path = field_path
        self._op_string = op_string
        self._value = value
        self._limit = None

    def limit(self, amount):
        self._limit = amount
        return self

    def stream(self):
        matches = []
        for doc_id, payload in self._storage.items():
            current = payload.get(self._field_path)
            if self._op_string == "<=" and current is not None and current <= self._value:
                matches.append(FakeSnapshot(doc_id, payload, self._storage))
        matches.sort(key=lambda snapshot: snapshot.id)
        if self._limit is not None:
            matches = matches[: self._limit]
        return matches


class FakeCollectionReference:
    def __init__(self, storage, name):
        self._storage = storage
        self._name = name

    def document(self, doc_id):
        collection = self._storage.setdefault(self._name, {})
        return FakeDocumentReference(collection, doc_id)

    def where(self, field_path, op_string, value):
        collection = self._storage.setdefault(self._name, {})
        return FakeQuery(collection, field_path, op_string, value)


class FakeFirestoreClient:
    instances = []

    def __init__(self, database):
        self.database = database
        self.collections = {}
        FakeFirestoreClient.instances.append(self)

    def collection(self, name):
        return FakeCollectionReference(self.collections, name)


def _build_conversation():
    return ConversacionData(
        numero_telefono="+5491122334455",
        estado=EstadoConversacion.CONFIRMANDO,
        estado_anterior=EstadoConversacion.RECOLECTANDO_SECUENCIAL,
        tipo_consulta=TipoConsulta.PRESUPUESTO,
        nombre_usuario="Ana",
        datos_contacto=DatosContacto(
            email="ana@example.com",
            direccion="Av Siempre Viva 742",
            horario_visita="9 a 18",
            descripcion="Necesito cotizar matafuegos y mantenimiento.",
        ),
        datos_temporales={
            "descripcion": "Necesito cotizar matafuegos y mantenimiento.",
            "_ifci_flow": False,
        },
        atendido_por_humano=True,
        message_history=[{"sender": "client", "message": "hola"}],
    )


def test_checkpoint_service_round_trip(monkeypatch):
    FakeFirestoreClient.instances.clear()
    monkeypatch.setenv(session_module.FIRESTORE_DATABASE_ENV, "(default)")
    monkeypatch.setattr(
        session_module,
        "firestore",
        SimpleNamespace(Client=FakeFirestoreClient),
    )

    service = session_module.ConversationSessionService()
    conversation = _build_conversation()
    updated_at = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
    last_user_message_at = datetime(2026, 4, 7, 11, 55, tzinfo=timezone.utc)

    payload = service.save(
        "whatsapp",
        conversation.numero_telefono,
        conversation,
        updated_at=updated_at,
        last_user_message_at=last_user_message_at,
    )

    assert payload["estado"] == EstadoConversacion.CONFIRMANDO.value
    assert payload["schema_version"] == session_module.CHECKPOINT_SCHEMA_VERSION
    assert payload["expires_at"] == last_user_message_at + timedelta(hours=24)

    client = FakeFirestoreClient.instances[-1]
    raw_doc = client.collections[session_module.CHECKPOINT_COLLECTION]["whatsapp:+5491122334455"]
    assert set(raw_doc.keys()) == session_module.CHECKPOINT_FIELDS
    assert raw_doc["datos_contacto"]["email"] == "ana@example.com"
    assert "message_history" not in raw_doc
    assert "atendido_por_humano" not in raw_doc

    checkpoint = service.load("whatsapp", "+5491122334455")

    assert checkpoint is not None
    assert checkpoint.doc_id == "whatsapp:+5491122334455"
    assert checkpoint.updated_at == updated_at
    assert checkpoint.last_user_message_at == last_user_message_at
    assert checkpoint.conversation.estado == EstadoConversacion.CONFIRMANDO
    assert checkpoint.conversation.estado_anterior == EstadoConversacion.RECOLECTANDO_SECUENCIAL
    assert checkpoint.conversation.tipo_consulta == TipoConsulta.PRESUPUESTO
    assert checkpoint.conversation.datos_contacto.email == "ana@example.com"
    assert checkpoint.conversation.atendido_por_humano is False
    assert checkpoint.conversation.message_history == []


def test_checkpoint_service_marks_duplicate_message_ids(monkeypatch):
    FakeFirestoreClient.instances.clear()
    monkeypatch.setenv(session_module.FIRESTORE_DATABASE_ENV, "(default)")
    monkeypatch.setattr(
        session_module,
        "firestore",
        SimpleNamespace(Client=FakeFirestoreClient),
    )

    service = session_module.ConversationSessionService()

    assert service.mark_message_processed("wamid-1") is False
    assert service.mark_message_processed("wamid-1") is True


def test_conversation_manager_hydrates_resumable_state(monkeypatch):
    FakeFirestoreClient.instances.clear()
    monkeypatch.setenv(session_module.FIRESTORE_DATABASE_ENV, "(default)")
    monkeypatch.setattr(
        session_module,
        "firestore",
        SimpleNamespace(Client=FakeFirestoreClient),
    )

    service = session_module.ConversationSessionService()
    conversation = _build_conversation()
    service.save_for_key(conversation.numero_telefono, conversation)

    manager = ConversationManager(session_service=service)
    hydrated = manager.get_conversacion(conversation.numero_telefono)

    assert hydrated.estado == EstadoConversacion.CONFIRMANDO
    assert hydrated.nombre_usuario == "Ana"
    assert hydrated.datos_contacto.email == "ana@example.com"


def test_cleanup_service_deletes_only_expired_checkpoints(monkeypatch):
    FakeFirestoreClient.instances.clear()
    monkeypatch.setenv(session_module.FIRESTORE_DATABASE_ENV, "(default)")
    monkeypatch.setattr(
        session_module,
        "firestore",
        SimpleNamespace(Client=FakeFirestoreClient),
    )
    service = session_module.ConversationSessionService()
    now = datetime(2026, 4, 7, 15, 0, tzinfo=timezone.utc)

    expired = ConversacionData(numero_telefono="+5491111111111", estado=EstadoConversacion.CONFIRMANDO)
    fresh = ConversacionData(numero_telefono="+5491222222222", estado=EstadoConversacion.CONFIRMANDO)

    service.save(
        "whatsapp",
        expired.numero_telefono,
        expired,
        updated_at=now - timedelta(hours=26),
        last_user_message_at=now - timedelta(hours=26),
    )
    service.save(
        "whatsapp",
        fresh.numero_telefono,
        fresh,
        updated_at=now - timedelta(hours=1),
        last_user_message_at=now - timedelta(hours=1),
    )

    deleted_doc_ids = service.cleanup_expired_checkpoints(now=now, limit=10)

    assert deleted_doc_ids == ["whatsapp:+5491111111111"]
    assert service.load("whatsapp", "+5491111111111") is None
    assert service.load("whatsapp", "+5491222222222") is not None


def test_new_presupuesto_multi_states_are_resumable():
    resumable_states = [
        EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO,
        EstadoConversacion.PRESUPUESTO_CORRIGIENDO_SECCION,
        EstadoConversacion.PRESUPUESTO_CORRIGIENDO_CONTACTO,
        EstadoConversacion.PRESUPUESTO_PRODUCTOS_CORRIGIENDO,
        EstadoConversacion.PRESUPUESTO_PRODUCTOS_BORRAR,
    ]

    for state in resumable_states:
        assert session_module.conversation_session_service.is_resumable_state(state) is True
