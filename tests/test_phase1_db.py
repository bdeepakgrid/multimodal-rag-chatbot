import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch

from api.main import app
from api.auth import Role
from api.auth_db import init_auth_db


@pytest.fixture(autouse=True)
def setup_db():
    init_auth_db()


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

        with patch("api.deps._state", mock_state):
            with TestClient(app) as test_client:
                yield test_client


def test_auth_signup_and_login(client):
    import uuid
    uid = uuid.uuid4().hex[:8]
    username = f"user_{uid}"
    email = f"user_{uid}@example.com"

    # Signup a new reviewer
    signup_resp = client.post(
        "/api/v1/auth/signup",
        json={
            "username": username,
            "email": email,
            "password": "secretpassword",
            "role": "reviewer"
        }
    )
    assert signup_resp.status_code == 200
    data = signup_resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "reviewer"

    token = data["access_token"]

    # Access protected route with Bearer token
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["identity"] == username
    assert me_resp.json()["role"] == "reviewer"


def test_auth_login_existing_seeded_users(client):
    # Test logging in as seeded admin user
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "admin"


def test_auth_invalid_credentials(client):
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrongpassword"}
    )
    assert login_resp.status_code == 401
