from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_returns_ok() -> None:
    app = create_app(Settings(app_env="test"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}
