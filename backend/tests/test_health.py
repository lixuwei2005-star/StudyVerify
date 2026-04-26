from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "studyverify-backend",
        "version": "0.1.0",
    }


def test_root_returns_welcome() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "StudyVerify API. See /docs for OpenAPI spec."}
