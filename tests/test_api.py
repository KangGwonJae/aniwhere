"""API 서버(aniwhere/api/) 테스트. DB·LLM·임베딩 모델 없이, 가짜 서비스(aniwhere/api/fake.py)를 끼워 돕니다.

확인하는 것: 각 엔드포인트가 약속한 형식을 돌려주는지, 인자를 바꾸지 않고 서비스에 그대로 넘기는지,
service.py ↔ main.py ↔ fake.py가 서로 어긋나지 않는지.
"""
import inspect
import re

import pytest
from fastapi.testclient import TestClient

from aniwhere import service
from aniwhere.api import fake, main as api_main
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


class Recorder:
    """서비스 함수 호출을 (이름, 인자, 키워드)로 기록하고 빈 dict를 돌려줌."""
    MODE = "fake"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {}
        return call


@pytest.fixture
def recorder():
    rec = Recorder()
    app = create_app(frontend_dir=None)
    app.dependency_overrides[get_service] = lambda: rec
    return rec, TestClient(app)


def test_find_returns_contract_keys(client):
    r = client.post("/api/find", json={"question": "키 작은 아저씨가 칼 들고 날아다녀"})
    assert r.status_code == 200
    assert set(r.json()) >= {"status", "answer", "candidates", "sources"}
    assert set(r.json()["candidates"][0]) >= {"series_id", "title"}


def test_find_passes_question_and_history_unchanged(recorder):
    rec, c = recorder
    history = [{"role": "user", "content": "거인 나오는 거"}, {"role": "assistant", "content": "어떤 장면이었나요?"}]
    c.post("/api/find", json={"question": "벽을 부숴", "history": history})
    assert rec.calls == [("find", ("벽을 부숴", history), {})]


def test_find_rejects_empty_or_missing_question(client):
    assert client.post("/api/find", json={"question": ""}).status_code == 422
    assert client.post("/api/find", json={}).status_code == 422


def test_review_passes_arguments_unchanged(recorder):
    rec, c = recorder
    c.post("/api/review", json={"series_id": fake.HERO, "seen_ep": 49, "mode": "last"})
    assert rec.calls == [("review", (fake.HERO, 49, "last", None), {})]


def test_review_defaults(recorder):
    rec, c = recorder
    c.post("/api/review", json={"series_id": fake.HERO})
    assert rec.calls == [("review", (fake.HERO, None, "summary", None), {})]


def test_review_without_seen_ep_and_record_asks_back(client):
    body = client.post("/api/review", json={"series_id": fake.TITAN}).json()
    assert body["answer"] is None and body["follow_up"] == fake.ASK_SEEN


def test_review_bad_mode_is_422(client):
    assert client.post("/api/review", json={"series_id": fake.HERO, "mode": "요약"}).status_code == 422


def test_review_ask_without_question_is_400(client):
    r = client.post("/api/review", json={"series_id": fake.HERO, "seen_ep": 49, "mode": "ask"})
    assert r.status_code == 400


def test_review_unknown_series_is_404(client):
    assert client.post("/api/review", json={"series_id": "tmdb:0", "seen_ep": 1}).status_code == 404


def test_long_text_is_rejected(client):
    assert client.post("/api/find", json={"question": "가" * 1001}).status_code == 422
    assert client.post("/api/recommend", json={"likes": "가" * 1001}).status_code == 422
    assert client.post("/api/find", json={"question": "가" * 1000}).status_code == 200


def test_recommend(client, recorder):
    r = client.post("/api/recommend", json={"likes": "기생충, 오징어 게임"})
    assert set(r.json()) >= {"mood", "picks"}
    rec, c = recorder
    c.post("/api/recommend", json={"likes": "기생충"})
    assert rec.calls == [("recommend", ("기생충",), {})]


def test_records_crud(client):
    assert [r["series_id"] for r in client.get("/api/records").json()] == [fake.HERO]
    assert client.get(f"/api/records/{fake.TITAN}").status_code == 404

    r = client.put(f"/api/records/{fake.TITAN}", json={"seen_ep": 12, "rating": 4.5})
    assert r.status_code == 200
    assert set(r.json()) >= {"series_id", "name", "seen_ep", "total_episodes", "rating", "updated_at"}
    assert r.json()["seen_ep"] == 12

    assert client.get(f"/api/records/{fake.TITAN}").json()["rating"] == 4.5
    assert len(client.get("/api/records").json()) == 2

    assert client.delete(f"/api/records/{fake.TITAN}").status_code == 204
    assert client.delete(f"/api/records/{fake.TITAN}").status_code == 404
    assert client.get(f"/api/records/{fake.TITAN}").status_code == 404


def test_record_save_passes_arguments_unchanged(recorder):
    rec, c = recorder
    c.put(f"/api/records/{fake.HERO}", json={"seen_ep": 50})
    assert rec.calls == [("save_record", (fake.HERO, 50, None), {})]


def test_record_out_of_range_is_400_not_500(client):
    assert client.put(f"/api/records/{fake.HERO}", json={"seen_ep": -1}).status_code == 400
    assert client.put(f"/api/records/{fake.HERO}", json={"seen_ep": 999}).status_code == 400
    assert client.put(f"/api/records/{fake.HERO}", json={"seen_ep": 3, "rating": 9}).status_code == 400
    assert client.put("/api/records/tmdb:0", json={"seen_ep": 1}).status_code == 404     # 모르는 작품은 404


def test_record_requires_integer_seen_ep(client):
    assert client.put(f"/api/records/{fake.HERO}", json={}).status_code == 422
    assert client.put(f"/api/records/{fake.HERO}", json={"seen_ep": "열둘"}).status_code == 422


def test_every_service_function_has_a_route():
    """service.py에 함수를 추가하고 API를 빠뜨리면 여기서 걸림."""
    src = inspect.getsource(api_main)
    missing = [n for n in SERVICE_FUNCS if f"svc.{n}(" not in src]
    assert missing == [], f"라우트에서 부르지 않는 서비스 함수: {missing}"


def test_frontend_is_served_when_folder_exists(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>AniWhere</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('hi')", encoding="utf-8")
    app = create_app(frontend_dir=tmp_path)
    app.dependency_overrides[get_service] = lambda: fake
    c = TestClient(app)
    assert c.get("/").status_code == 200 and "AniWhere" in c.get("/").text
    assert c.get("/app.js").status_code == 200
    assert c.get("/api/health").json()["mode"] == "fake"      # /api가 화면보다 먼저 매칭


def test_no_frontend_folder_means_api_only(tmp_path):
    app = create_app(frontend_dir=tmp_path / "없는폴더")
    app.dependency_overrides[get_service] = lambda: fake
    c = TestClient(app)
    assert c.get("/").status_code == 404
    assert c.get("/api/health").status_code == 200
