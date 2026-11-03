from fastapi.testclient import TestClient

from khataiq.api.main import app


def test_healthz_is_ok_without_a_database():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
