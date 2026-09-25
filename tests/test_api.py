from fastapi.testclient import TestClient

from api.main import app
from core.models import MechanismEnum

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reports_empty():
    response = client.get("/reports")
    assert response.status_code == 200
    assert "reports" in response.json()


def test_stats_shape():
    response = client.get("/reports/stats")
    assert response.status_code == 200
    body = response.json()
    for key in ("total", "by_status", "by_mechanism", "by_step", "verified", "model_accuracy"):
        assert key in body


def test_mechanisms_lists_full_taxonomy():
    response = client.get("/mechanisms")
    assert response.status_code == 200
    body = response.json()
    ids = {m["id"] for m in body["mechanisms"]}
    assert ids == {e.value for e in MechanismEnum}
    for m in body["mechanisms"]:
        assert "category" in m and "step" in m and "signature" in m


def test_verify_unknown_report_404():
    response = client.post(
        "/reports/does-not-exist/verify",
        json={"verified_mechanism": "head_bearing_wear"},
    )
    assert response.status_code == 404


def test_verify_rejects_unknown_mechanism():
    # Even for a report that doesn't exist, an invalid mechanism should fail
    # request validation (422) before the 404 lookup ever runs.
    response = client.post(
        "/reports/does-not-exist/verify",
        json={"verified_mechanism": "not_a_real_mechanism"},
    )
    assert response.status_code == 422
