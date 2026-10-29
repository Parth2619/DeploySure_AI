from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_quote_applies_the_discount():
    data = client.post("/api/quote", json={"price": 200, "discount_percent": 10}).json()
    assert data["final_price"] == 180.0 and data["savings"] == 20.0


def test_bad_discount_is_a_400():
    assert client.post("/api/quote", json={"price": 100, "discount_percent": 150}).status_code == 400
