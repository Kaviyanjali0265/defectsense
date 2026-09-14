from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reports_empty():
    response = client.get("/reports")
    assert response.status_code == 200
    assert "reports" in response.json()


def test_stats_empty():
    response = client.get("/reports/stats")
    assert response.status_code == 200
    assert "total_reports" in response.json()
