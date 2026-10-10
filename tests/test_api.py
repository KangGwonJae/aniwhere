"""API 서버(aniwhere/api/) 테스트. DB·LLM·임베딩 모델 없이, 가짜 서비스(aniwhere/api/fake.py)를 끼워 돕니다.

확인하는 것: 각 엔드포인트가 약속한 형식을 돌려주는지, 인자를 바꾸지 않고 서비스에 그대로 넘기는지,
service.py ↔ main.py ↔ fake.py가 서로 어긋나지 않는지.
"""
import inspect
import re

import pytest
from fastapi.testclient import TestClient

from aniwhere import service
from aniwhere.api import fake
from aniwhere.api.main import create_app, get_service
from aniwhere.retrieval.catalog import UnknownSeries


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

# service.py의 공개 함수 = API로 열어야 하는 함수. db()·warm_up()은 서버 내부용.
SERVICE_FUNCS = sorted(
    n for n, f in inspect.getmembers(service, inspect.isfunction)
    if f.__module__ == service.__name__ and not n.startswith("_") and n not in ("db", "warm_up")
)

# 독스트링 키 비교에 쓸 호출 인자. 기록이 있는 작품(HERO)로 부르면 follow_up 없이 정상 응답이 나옴.
SAMPLE_ARGS = {
    "find": ("키 작은 아저씨가 칼 들고 날아다녀",),
    "where_to_watch": (fake.HERO,),
    "review": (fake.HERO,),
    "dictionary": (fake.HERO,),
    "recommend": ("반전 많은 스릴러",),
    "save_record": (fake.HERO, 3),
}


def docstring_keys(func):
    """독스트링의 `→ {a, b[...], c?}`에서 최상위 키를 뽑음. 그 형식이 아니면 None. 반환: (필수 키, 선택 키)"""
    doc = inspect.getdoc(func) or ""
    m = re.search(r"→\s*\{", doc)
    if not m:
        return None
    depth, start, parts, buf = 0, m.end(), [], ""
    for ch in doc[start:]:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth == 0:
                break
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf); buf = ""
        else:
            buf += ch
    parts.append(buf)
    keys = [re.split(r"[\[{]", p.strip())[0].strip() for p in parts if p.strip()]
    return {k for k in keys if not k.endswith("?")}, {k.rstrip("?") for k in keys if k.endswith("?")}


def test_fake_has_every_service_function():
    missing = [n for n in SERVICE_FUNCS if not callable(getattr(fake, n, None))]
    assert missing == [], f"fake.py에 없는 서비스 함수: {missing}"


@pytest.mark.parametrize("name", SERVICE_FUNCS)
def test_fake_response_keys_match_service_docstring(name):
    keys = docstring_keys(getattr(service, name))
    if keys is None:
        pytest.skip("독스트링에 → {…} 형식이 없음")
    required, optional = keys
    fake.reset()
    result = getattr(fake, name)(*SAMPLE_ARGS[name])
    assert isinstance(result, dict), f"{name}은 dict를 돌려줘야 함"
    assert required <= set(result), f"{name}: 빠진 필수 키 {required - set(result)}"
    assert set(result) <= required | optional, f"{name}: 독스트링에 없는 키 {set(result) - required - optional}"


def test_fake_record_roundtrip():
    fake.reset()
    assert fake.get_record(fake.TITAN) is None
    saved = fake.save_record(fake.TITAN, 12, 4.5)
    assert saved["seen_ep"] == 12 and saved["rating"] == 4.5
    assert fake.get_record(fake.TITAN)["seen_ep"] == 12
    assert {r["series_id"] for r in fake.list_records()} == {fake.HERO, fake.TITAN}
    assert fake.delete_record(fake.TITAN) is True
    assert fake.delete_record(fake.TITAN) is False


def test_find_status_branches_are_reachable():
    """화면의 네 갈래(회차 찾음 / 작품만 찾음 / 헷갈림 / 못 찾음)를 가짜로도 모두 만들어 볼 수 있어야 함."""
    fake.reset()
    assert fake.find("키 작은 아저씨가 칼 들고 날아다녀")["status"] == "episode"
    assert fake.find("거인 나오는 작품")["status"] == "series"
    amb = fake.find("두 장면이 헷갈려")
    assert amb["status"] == "ambiguous" and amb["follow_up"] and len(amb["candidates"]) >= 2
    none = fake.find("없는 작품 이야기")
    assert none["status"] == "none" and none["candidates"] == []


def test_fake_rejects_bad_input_like_service():
    with pytest.raises(UnknownSeries):
        fake.where_to_watch("tmdb:0")
    with pytest.raises(UnknownSeries):
        fake.save_record("tmdb:0", 1)
    with pytest.raises(UnknownSeries):
        fake.review("tmdb:0")
    with pytest.raises(ValueError):
        fake.save_record(fake.HERO, -1)
    with pytest.raises(ValueError):
        fake.save_record(fake.HERO, 999)
    with pytest.raises(ValueError):
        fake.review(fake.HERO, 49, "ask", None)
    with pytest.raises(ValueError):
        fake.review(fake.HERO, 49, "오타")


def test_series_list_and_search(client):
    assert len(client.get("/api/series").json()) == 2
    rows = client.get("/api/series", params={"q": "거인"}).json()
    assert [r["series_id"] for r in rows] == [fake.TITAN]
    assert set(rows[0]) == {"series_id", "name", "title", "total_episodes"}


def test_series_limit_is_bounded(client):
    assert client.get("/api/series", params={"limit": 0}).status_code == 422
    assert client.get("/api/series", params={"limit": 100000}).status_code == 422


def test_series_info_and_404(client):
    assert client.get(f"/api/series/{fake.HERO}").json()["name"] == "나의 히어로 아카데미아"
    assert client.get("/api/series/tmdb:0").status_code == 404


def test_series_id_may_be_url_encoded(client):
    plain = client.get("/api/series/tmdb:65930").json()
    encoded = client.get("/api/series/tmdb%3A65930").json()
    assert plain == encoded


def test_where_to_watch(client):
    r = client.get(f"/api/series/{fake.HERO}/where-to-watch")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"series_id", "title", "seasons", "attribution"}
    assert set(body["seasons"][0]) >= {"name", "providers", "checked_at"}


def test_unknown_series_is_404_everywhere(client):
    assert client.get("/api/series/tmdb:0/where-to-watch").status_code == 404
    assert client.get("/api/series/tmdb:0/dictionary").status_code == 404
    assert "모르는 작품" in client.get("/api/series/tmdb:0/where-to-watch").json()["detail"]


def test_dictionary_uses_record_when_seen_ep_missing(client):
    body = client.get(f"/api/series/{fake.HERO}/dictionary").json()
    assert body["seen_ep"] == 49 and body["entries"] and body["follow_up"] is None


def test_dictionary_asks_when_no_record_and_no_seen_ep(client):
    body = client.get(f"/api/series/{fake.TITAN}/dictionary").json()
    assert body == {"seen_ep": None, "entries": [], "follow_up": fake.ASK_SEEN}


def test_dictionary_explicit_seen_ep(client):
    body = client.get(f"/api/series/{fake.TITAN}/dictionary", params={"seen_ep": 7}).json()
    assert body["seen_ep"] == 7
