import importlib
import os
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.handoff_inbox_models import (
    HandoffInboxAutocloseCaseRecord,
    HandoffInboxAutocloseResult,
    HandoffInboxCaseStatus,
    HandoffInboxRetentionCutoffs,
    HandoffInboxRetentionResult,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _load_main_module():
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_internal_handoff_autoclose_requires_valid_token(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "secret-token")
    main_module = _load_main_module()
    client = TestClient(main_module.app)

    response = client.post("/internal/handoff/autoclose", data={"token": "wrong-token"})

    assert response.status_code == 401


def test_internal_handoff_autoclose_notifies_and_finalizes_closed_cases(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "secret-token")
    monkeypatch.setenv("HANDOFF_INACTIVITY_MINUTES", "90")
    main_module = _load_main_module()

    result = HandoffInboxAutocloseResult(
        dry_run=False,
        batch_limit=5,
        cutoff_before=datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
        cases_scanned=2,
        cases_eligible=1,
        cases_closed=1,
        closed_cases=[
            HandoffInboxAutocloseCaseRecord(
                case_id="case-1",
                client_phone="+5491111111111",
                prior_status=HandoffInboxCaseStatus.ACTIVE,
                created_at=datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc),
                last_interaction_at=datetime(2026, 4, 7, 10, 30, tzinfo=timezone.utc),
            )
        ],
    )

    sent_messages = []
    finalized = []
    sync_calls = []

    monkeypatch.setattr(
        main_module.handoff_inbox_service,
        "auto_close_inactive_cases",
        lambda **kwargs: result,
    )
    monkeypatch.setattr(
        main_module,
        "send_message",
        lambda phone, text: sent_messages.append((phone, text)) or True,
    )
    monkeypatch.setattr(
        main_module,
        "_sync_runtime_handoff_state",
        lambda: sync_calls.append("sync") or [],
    )
    monkeypatch.setattr(
        main_module.conversation_manager,
        "finalizar_conversacion",
        lambda phone: finalized.append(phone),
    )

    client = TestClient(main_module.app)
    response = client.post(
        "/internal/handoff/autoclose",
        data={"token": "secret-token", "dry_run": "false", "batch_limit": "5"},
    )

    assert response.status_code == 200
    assert sent_messages == [
        (
            "+5491111111111",
            "Cerramos esta conversación por inactividad.\nSi necesitás ayuda, escribinos nuevamente.",
        )
    ]
    assert finalized == ["+5491111111111"]
    assert sync_calls == ["sync"]
    assert response.json()["cases_closed"] == 1
    assert response.json()["closed_cases"][0]["case_id"] == "case-1"


def test_internal_handoff_purge_returns_retention_counts(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "secret-token")
    main_module = _load_main_module()

    result = HandoffInboxRetentionResult(
        dry_run=True,
        batch_limit=7,
        cutoffs=HandoffInboxRetentionCutoffs(
            messages_before=datetime(2026, 4, 4, 0, 0, tzinfo=timezone.utc),
            outbox_before=datetime(2026, 4, 4, 0, 0, tzinfo=timezone.utc),
            cases_before=datetime(2026, 3, 31, 0, 0, tzinfo=timezone.utc),
        ),
        cases_scanned=3,
        cases_skipped_missing_closed_at=1,
        cases_deleted=2,
        messages_deleted=11,
        outbox_deleted=4,
    )

    monkeypatch.setattr(
        main_module.handoff_inbox_service,
        "purge_closed_case_history",
        lambda **kwargs: result,
    )

    client = TestClient(main_module.app)
    response = client.post(
        "/internal/handoff/purge",
        data={"token": "secret-token", "dry_run": "true", "batch_limit": "7"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "dry_run": True,
        "batch_limit": 7,
        "cases_scanned": 3,
        "cases_skipped_missing_closed_at": 1,
        "cases_deleted": 2,
        "messages_deleted": 11,
        "outbox_deleted": 4,
        "cutoffs": {
            "messages_before": "2026-04-04T00:00:00+00:00",
            "outbox_before": "2026-04-04T00:00:00+00:00",
            "cases_before": "2026-03-31T00:00:00+00:00",
        },
    }
