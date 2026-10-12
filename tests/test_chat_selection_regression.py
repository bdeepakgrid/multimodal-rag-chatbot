import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
import api.routers.chat as chat_router
from api.routers.chat import PENDING_FEEDBACK, REFINE_PENDING, SESSION_STATE
from models.schemas import AgentStep, Chunk, RetrievedChunk, SourceType


@pytest.fixture
def client():
    with patch("api.main.init_app_state") as mock_init, \
         patch("api.main.warm_reranker") as mock_warm, \
         patch("api.main.shutdown_app_state") as mock_shutdown:
        mock_state = MagicMock()
        mock_state.ollama.health_check = AsyncMock(return_value=True)
        mock_state.ollama.llm_health_check = AsyncMock(return_value=(True, "OK"))
        mock_state.qdrant_store.ensure_collection = MagicMock()
        mock_state.context_builder.build = MagicMock(return_value=("prompt", []))
        mock_state.context_builder.compute_confidence = MagicMock(return_value=0.9)
        mock_state.settings.confidence_threshold = 0.5
        mock_state.settings.default_tenant_id = "default"
        mock_state.agent.run = AsyncMock(return_value=([], [], []))
        mock_state.ollama.generate = AsyncMock(return_value="")
        mock_state.graph_store.load.return_value = MagicMock()
        mock_state.graph_store.load.return_value.graph.graph = {"feedback_weights": {}}
        mock_state.graph_store.save = MagicMock()
        mock_init.return_value = mock_state
        chat_router.get_app_state = MagicMock(return_value=mock_state)

        with patch("api.deps._state", mock_state):
            with TestClient(app) as test_client:
                yield test_client


def test_selection_number_bypasses_out_of_scope_check(client):
    chunk = Chunk.new(
        text="Incident MX-037 | Station 13 | Symptom: robot stopped welding and threw a current error | Root cause: worn contact tip | Solution: replace contact tip and verify current draw.",
        tenant_id="default",
        source_file="weld_log.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["weld", "robot"],
        raw_file_url="https://example.invalid/weld_log.csv",
        chunk_index=0,
    )
    second_chunk = Chunk.new(
        text="Incident MX-013 | Station 2 | Symptom: robot stalls on approach before arc strike | Root cause: intermittent I/O fault | Solution: inspect encoder and reset inputs.",
        tenant_id="default",
        source_file="station2_log.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["robot", "motion"],
        raw_file_url="https://example.invalid/station2_log.csv",
        chunk_index=1,
    )
    SESSION_STATE["sess-selection"] = SimpleNamespace(
        candidates=[
            RetrievedChunk(chunk=chunk, rerank_score=0.91),
            RetrievedChunk(chunk=second_chunk, rerank_score=0.82),
        ],
        original_query="Robot stopped while welding and threw a current error",
    )

    try:
        response = client.post(
            "/api/v1/chat",
            json={"query": "2", "session_id": "sess-selection"},
            headers={"API-Key": "technician-key-123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "Issue:" in body["answer"]
        assert "Likely cause:" in body["answer"]
        assert "Fix:" in body["answer"]
        assert "Verify:" in body["answer"]
        assert "Safety:" in body["answer"]
        assert "_Source:" in body["answer"]
        assert "Did that resolve it?" in body["answer"]
        assert "I can only answer questions based on the equipment maintenance documents" not in body["answer"]
    finally:
        SESSION_STATE.pop("sess-selection", None)


def test_number_without_active_selection_is_out_of_scope(client):
    response = client.post(
        "/api/v1/chat",
        json={"query": "2"},
        headers={"API-Key": "technician-key-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "I can only answer questions based on the equipment maintenance documents" in body["answer"]


def test_image_attachment_is_described_before_retrieval(client):
    state = chat_router.get_app_state.return_value
    state.settings.chat_image_max_bytes = 8 * 1024 * 1024
    state.ollama.describe_image = AsyncMock(
        return_value="HMI shows servo drive alarm A.042 and an illuminated fault indicator."
    )
    state.agent.run = AsyncMock(return_value=([], [AgentStep(thought="image query", query="servo alarm", results_found=0)], []))

    response = client.post(
        "/api/v1/chat",
        data={"query": "Axis has stopped", "session_id": "image-query"},
        files={"image": ("hmi.png", b"fake-png-content", "image/png")},
        headers={"API-Key": "technician-key-123"},
    )

    assert response.status_code == 200
    state.ollama.describe_image.assert_awaited_once()
    search_query = state.agent.run.await_args.args[0]
    assert "Axis has stopped" in search_query
    assert "servo drive alarm A.042" in search_query


def test_confirmed_fix_response_includes_feedback_suggestions(client):
    chunk = Chunk.new(
        text="Incident MX-011 | Station 9 | Symptom: robot stopped welding and threw a current error | Root cause: worn contact tip | Solution: replace contact tip and verify current draw.",
        tenant_id="default",
        source_file="weld_log.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["weld", "robot"],
        raw_file_url="https://example.invalid/weld_log.csv",
        chunk_index=0,
    )
    SESSION_STATE["sess-feedback-suggestions"] = SimpleNamespace(
        candidates=[RetrievedChunk(chunk=chunk, rerank_score=0.91)],
        original_query="Robot stopped while welding and threw a current error",
    )

    try:
        response = client.post(
            "/api/v1/chat",
            json={"query": "1", "session_id": "sess-feedback-suggestions"},
            headers={"API-Key": "technician-key-123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "Did that resolve it?" in body["answer"]
        labels = {item["label"] for item in body["suggestions"]}
        assert labels == {"Yes", "Partially", "No"}
        ids = {item["id"] for item in body["suggestions"]}
        assert ids == {"feedback-yes", "feedback-partially", "feedback-no"}
    finally:
        SESSION_STATE.pop("sess-feedback-suggestions", None)
        PENDING_FEEDBACK.pop("sess-feedback-suggestions", None)


def test_feedback_no_reruns_search_excluding_incident(client):
    incident_id = "MX-999"
    query = "Robot stopped while welding and threw a current error"
    PENDING_FEEDBACK["fb-no"] = {"incident_id": incident_id, "query": query, "source_file": "weld_log.csv"}

    kept = Chunk.new(
        text="Incident MX-111 | Station 9 | Symptom: robot stalls before arc strike | Root cause: poor alignment | Solution: align fixture.",
        tenant_id="default",
        source_file="station9.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["robot"],
        raw_file_url="https://example.invalid/station9.csv",
        chunk_index=0,
    )
    chat_router.get_app_state.return_value.agent.run = AsyncMock(return_value=([RetrievedChunk(chunk=kept, rerank_score=0.8)], [], []))

    response = client.post(
        "/api/v1/chat",
        json={"query": "no", "session_id": "fb-no"},
        headers={"API-Key": "technician-key-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "Ruling that one out" in body["answer"]
    assert incident_id not in body["answer"]
    assert SESSION_STATE["fb-no"].candidates[0].chunk.source_file == "station9.csv"
    PENDING_FEEDBACK.pop("fb-no", None)
    SESSION_STATE.pop("fb-no", None)


def test_selection_after_rejection_reruns_correctly(client):
    first = Chunk.new(
        text="Incident MX-200 | Station 5 | Symptom: current spike during weld start | Root cause: worn tip | Solution: replace tip.",
        tenant_id="default",
        source_file="first.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["robot"],
        raw_file_url="https://example.invalid/first.csv",
        chunk_index=0,
    )
    second = Chunk.new(
        text="Incident MX-201 | Station 6 | Symptom: robot stalls before arc strike | Root cause: poor alignment | Solution: align fixture.",
        tenant_id="default",
        source_file="second.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["robot"],
        raw_file_url="https://example.invalid/second.csv",
        chunk_index=1,
    )
    SESSION_STATE["selection-reject"] = SimpleNamespace(
        candidates=[RetrievedChunk(chunk=first, rerank_score=0.95), RetrievedChunk(chunk=second, rerank_score=0.88)],
        original_query="Robot stopped while welding and threw a current error",
    )
    response = client.post(
        "/api/v1/chat",
        json={"query": "1", "session_id": "selection-reject"},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    assert "Issue:" in response.json()["answer"]

    PENDING_FEEDBACK["selection-reject"] = {"incident_id": "MX-200", "query": "Robot stopped while welding and threw a current error", "source_file": "first.csv"}
    chat_router.get_app_state.return_value.agent.run = AsyncMock(return_value=([RetrievedChunk(chunk=second, rerank_score=0.88)], [], []))

    response = client.post(
        "/api/v1/chat",
        json={"query": "no", "session_id": "selection-reject"},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    assert "Ruling that one out" in response.json()["answer"]
    assert SESSION_STATE["selection-reject"].candidates[0].chunk.source_file == "second.csv"

    response = client.post(
        "/api/v1/chat",
        json={"query": "1", "session_id": "selection-reject"},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    assert "Issue:" in response.json()["answer"]
    assert "MX-201" in response.json()["answer"] or "Station 6" in response.json()["answer"]

    SESSION_STATE.pop("selection-reject", None)
    PENDING_FEEDBACK.pop("selection-reject", None)


def test_feedback_yes_persists_confirmed_outcome(client):
    incident_id = "MX-777"
    session_id = "fb-yes"
    PENDING_FEEDBACK[session_id] = {"incident_id": incident_id, "query": "robot current error", "source_file": "weld.csv"}

    response = client.post(
        "/api/v1/chat",
        json={"query": "yes", "session_id": session_id},
        headers={"API-Key": "technician-key-123"},
    )

    assert response.status_code == 200
    assert "marked as confirmed" in response.json()["answer"].lower()

    db_path = Path("./data/feedback.sqlite3")
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT incident_id, outcome FROM feedback_outcomes WHERE incident_id = ? ORDER BY id DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
    assert row is not None and row[1] == "confirmed"
    PENDING_FEEDBACK.pop(session_id, None)


def test_feedback_partially_stays_in_refine_mode(client):
    session_id = "fb-partial"
    PENDING_FEEDBACK[session_id] = {"incident_id": "MX-555", "query": "robot current error", "source_file": "weld.csv"}

    response = client.post(
        "/api/v1/chat",
        json={"query": "partially", "session_id": session_id},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    assert "What\'s still happening?" in response.json()["answer"]
    assert session_id in REFINE_PENDING

    chat_router.get_app_state.return_value.agent.run = AsyncMock(return_value=([RetrievedChunk(chunk=Chunk.new(
        text="Incident MX-404 | Station 12 | Symptom: current spike remains during weld start | Root cause: poor contact | Solution: clean contact.",
        tenant_id="default",
        source_file="weld.csv",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["robot"],
        raw_file_url="https://example.invalid/weld.csv",
        chunk_index=0,
    ), rerank_score=0.75)], [], []))

    response = client.post(
        "/api/v1/chat",
        json={"query": "still seeing current spike at startup", "session_id": session_id},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    assert "Was this diagnosis useful?" in response.json()["answer"]
    assert "A closer match was found" in response.json()["answer"]
    assert "Incident MX-404" not in response.json()["answer"]
    REFINE_PENDING.pop(session_id, None)
    PENDING_FEEDBACK.pop(session_id, None)


def test_bare_feedback_word_without_pending_state_hits_out_of_scope(client):
    response = client.post(
        "/api/v1/chat",
        json={"query": "no"},
        headers={"API-Key": "technician-key-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "I can only answer questions based on the equipment maintenance documents" in body["answer"]
