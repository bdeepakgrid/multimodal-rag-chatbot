import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch

from api.main import app
from api.auth import Role, API_KEY_STORE


@pytest.fixture
def client():
    with patch("api.main.init_app_state") as mock_init, \
         patch("api.main.warm_reranker") as mock_warm, \
         patch("api.main.shutdown_app_state") as mock_shutdown:
        mock_state = MagicMock()
        mock_state.ollama.health_check = AsyncMock(return_value=True)
        mock_state.ollama.llm_health_check = AsyncMock(return_value=(True, "OK"))
        mock_state.qdrant_store.get_stats = MagicMock(return_value={"total_chunks": 0, "by_type": {}})
        mock_init.return_value = mock_state
        
        # Ensure api.deps._state is set
        with patch("api.deps._state", mock_state):
            with TestClient(app) as test_client:
                yield test_client


def test_auth_missing_key(client):
    response = client.get("/api/v1/collections")
    assert response.status_code == 401
    assert "Invalid or missing API key" in response.json()["detail"]


def test_auth_invalid_key(client):
    response = client.get("/api/v1/collections", headers={"API-Key": "wrong-key"})
    assert response.status_code == 401
    assert "Invalid or missing API key" in response.json()["detail"]


def test_auth_valid_roles_resolve(client):
    for key, (tenant_id, expected_role, identity) in API_KEY_STORE.items():
        response = client.get("/api/v1/collections", headers={"API-Key": key})
        # Collections endpoint should be accessible in Phase 1 for all roles
        assert response.status_code == 200, f"Failed for role {expected_role}"


def test_phase1_unrestricted_chat_and_ingest(client):
    # Both technician, reviewer, admin can hit /chat and /ingest (plumbing only, no restrictions in Phase 1)
    roles_keys = [
        ("tech-key-123", Role.TECHNICIAN),
        ("reviewer-key-456", Role.REVIEWER),
        ("admin-key-789", Role.ADMIN),
    ]

    for key, role in roles_keys:
        # Chat test with greeting (returns 200 without LLM call)
        chat_resp = client.post(
            "/api/v1/chat",
            json={"query": "hello"},
            headers={"API-Key": key}
        )
        assert chat_resp.status_code == 200, f"Chat blocked for role {role}"

        # Ingest test (missing files returns 422 validation error in FastAPI, NOT 401/403)
        ingest_resp = client.post(
            "/api/v1/ingest",
            headers={"API-Key": key}
        )
        # In Phase 1, all roles pass auth and hit endpoint validation (422 for missing required files)
        assert ingest_resp.status_code == 422, f"Ingest auth failed/restricted unexpectedly for role {role}"
