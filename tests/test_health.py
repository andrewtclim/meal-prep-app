from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_health_returns_ok():
    """GET /health answers 200 with {"status": "ok"}.

    Guards the endpoint that Docker, Cloud Run, and CI use to check the API is up.
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
