"""API 서버(aniwhere/api/) 테스트. DB·LLM·임베딩 모델 없이, 가짜 서비스(aniwhere/api/fake.py)를 끼워 돕니다.

확인하는 것: 각 엔드포인트가 약속한 형식을 돌려주는지, 인자를 바꾸지 않고 서비스에 그대로 넘기는지,
service.py ↔ main.py ↔ fake.py가 서로 어긋나지 않는지.
"""
import pytest
from fastapi.testclient import TestClient

from aniwhere.api import fake
from aniwhere.api.main import create_app, get_service


@pytest.fixture
def client():
    app = create_app(frontend_dir=None)
    app.dependency_overrides[get_service] = lambda: fake
    fake.reset()
    return TestClient(app)


def test_health_reports_mode(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mode": "fake"}
