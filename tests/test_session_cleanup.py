import importlib
import os
import sys

from fastapi.testclient import TestClient


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _load_main_module():
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_cleanup_endpoint_requires_valid_token(monkeypatch):
    monkeypatch.setenv("SESSION_CHECKPOINT_CLEANUP_TOKEN", "cleanup-token")
    main_module = _load_main_module()
    client = TestClient(main_module.app)

    response = client.post("/session-checkpoints/cleanup", data={"token": "wrong-token"})

    assert response.status_code == 401


def test_cleanup_endpoint_runs_bounded_batch(monkeypatch):
    monkeypatch.setenv("SESSION_CHECKPOINT_CLEANUP_TOKEN", "cleanup-token")
    monkeypatch.setenv("SESSION_CHECKPOINT_CLEANUP_BATCH_SIZE", "2")
    main_module = _load_main_module()
    captured = {}

    def fake_cleanup_expired_checkpoints(*, limit):
        captured["limit"] = limit
        return ["whatsapp:+5491111111111", "whatsapp:+5491222222222"]

    monkeypatch.setattr(
        main_module.conversation_session_service,
        "cleanup_expired_checkpoints",
        fake_cleanup_expired_checkpoints,
    )

    client = TestClient(main_module.app)
    response = client.post("/session-checkpoints/cleanup", data={"token": "cleanup-token"})

    assert response.status_code == 200
    assert captured["limit"] == 2
    assert response.json() == {
        "deleted": 2,
        "deleted_doc_ids": [
            "whatsapp:+5491111111111",
            "whatsapp:+5491222222222",
        ],
        "batch_limit": 2,
    }
