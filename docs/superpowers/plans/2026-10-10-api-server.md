# API 서버 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `aniwhere/service.py`의 함수들을 FastAPI 엔드포인트로 열고, DB·LLM 없이 뜨는 가짜 서비스 모드와 `frontend/` 화면 서빙을 함께 제공한다.

**Architecture:** `aniwhere/api/main.py`의 `create_app()`이 FastAPI 앱을 만든다. 라우트는 `Depends(get_service)`로 서비스 모듈(`aniwhere.service` 또는 `aniwhere.api.fake`)을 받아 함수를 그대로 호출하고 반환값을 그대로 돌려준다. 판단 로직은 없다. 요청 본문만 pydantic으로 검사하고, `ValueError`는 400, 조회 결과 없음은 404로 바꾼다.

**Tech Stack:** Python 3.11, FastAPI ≥0.115, uvicorn, pydantic v2, pytest + `fastapi.testclient`(httpx). 저장소 venv는 `.venv/bin/python`.

**Spec:** `docs/superpowers/specs/2026-10-10-api-server-design.md`

## Global Constraints

- `api/`에는 판단 로직을 두지 않는다. 서비스 반환값을 가공하지 않고 그대로 보낸다 (AGENTS.md, `docs/ARCHITECTURE.md`의 `api/` 규칙).
- 의존 방향: `api/`는 `aniwhere.service`, `aniwhere.api.fake`, `aniwhere.config`만 import한다. `retrieval`·`agent`·`records`·`db`를 직접 import하지 않는다.
- 응답용 pydantic 모델을 만들지 않는다. 응답 형식의 원본은 `service.py` 독스트링 하나다.
- `seen_ep`가 없어도 서버는 오류를 내지 않는다. 서비스가 `follow_up`으로 되묻는 200 응답을 그대로 보낸다.
- 비밀 값 없음. `.env.example`은 바꾸지 않는다. `ANIWHERE_FAKE`는 Makefile에서만 다룬다.
- CORS 설정 없음. `frontend/`는 이 PR에서 만들지 않는다.
- 모든 명령은 저장소 루트(`aniwhere/`)에서 `.venv/bin/python -m pytest ...` 형태로 실행한다.
- 커밋 메시지는 한국어, 첫 줄 한 문장. 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

스펙이 직접 말하지 않지만 사용자가 실제로 보낼 입력들. 각 항목의 테스트는 해당 Task에 들어 있다.

1. `PUT /api/records/{id}`에 `seen_ep`가 음수이거나 전체 회차보다 클 때 → 서비스가 `ValueError` → 400이어야 한다 (500 금지). → Task 5
2. `GET /api/series?limit=0` 또는 `limit=100000` → 422로 거절해야 한다 (DB에 무제한 질의 금지). → Task 3
3. `POST /api/find`에 `question: ""` → 422여야 한다 (빈 질문으로 LLM 호출 금지). → Task 4
4. `POST /api/review`에 `mode: "ask"`인데 `question` 없음 → 서비스 `ValueError` → 400. → Task 4
5. `series_id`를 `tmdb%3A65930`처럼 URL 인코딩해서 보내도 `tmdb:65930`과 같은 결과여야 한다. → Task 3

---

## 파일 구조

| 파일 | 역할 |
|---|---|
| `aniwhere/api/__init__.py` | 빈 파일 (패키지 표시) |
| `aniwhere/api/main.py` | `create_app(frontend_dir)`, `get_service()`, 요청 모델 4개, 라우트, `ValueError` 처리기, 모듈 수준 `app` |
| `aniwhere/api/fake.py` | `service.py`와 같은 이름·시그니처의 가짜 함수. 고정 데이터 + 메모리 기록장. `MODE = "fake"` |
| `tests/test_api.py` | TestClient 기반 테스트 전부 |
| `requirements.txt` | fastapi, uvicorn, httpx 추가 |
| `Makefile` | `api` 타깃 |
| `README.md` | 실행 명령에 `make api` 추가 |

---

### Task 1: 패키지 설치, 앱 뼈대, `/api/health`

**Files:**
- Modify: `requirements.txt`
- Create: `aniwhere/api/__init__.py`
- Create: `aniwhere/api/main.py`
- Create: `aniwhere/api/fake.py` (이 Task에서는 `MODE`만)
- Create: `tests/test_api.py`

**Interfaces:**
- Produces: `aniwhere.api.main.create_app(frontend_dir: Path | None = None) -> FastAPI`, `aniwhere.api.main.get_service()`, `aniwhere.api.main.app`, `aniwhere.api.fake.MODE = "fake"`
- 이후 모든 Task는 테스트에서 `client` 픽스처(가짜 서비스가 주입된 TestClient)를 쓴다.

- [ ] **Step 1: 패키지 추가·설치**

`requirements.txt`의 `# 앱 (aniwhere/)` 묶음에 두 줄, `# 테스트` 묶음에 한 줄 추가:

```
# 앱 (aniwhere/): LLM, 확인용 화면, API 서버
openai>=1.60
streamlit>=1.38
fastapi>=0.115
uvicorn[standard]>=0.30
# 테스트
pytest>=8.0
httpx>=0.27
```

Run: `.venv/bin/pip install -r requirements.txt -q && .venv/bin/python -c "import fastapi, httpx; print(fastapi.__version__)"`
Expected: 버전 문자열 출력.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_api.py`:

```python
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
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: `ModuleNotFoundError: No module named 'aniwhere.api'`

- [ ] **Step 4: 뼈대 구현**

`aniwhere/api/__init__.py`: 빈 파일.

`aniwhere/api/fake.py` (이 Task 분량):

```python
"""DB·LLM 없이 API 서버를 띄우기 위한 가짜 서비스. service.py와 같은 함수 이름·인자·응답 형식을 지킵니다.

쓰는 곳: (1) 프론트엔드 개발 — `make api FAKE=1`, (2) tests/test_api.py, (3) 응답 형식의 실행 가능한 예시.
데이터는 frontend/app.js의 mock과 맞춘 나의 히어로 아카데미아 하나와, 기록이 없는 진격의 거인 하나입니다.
기록장은 메모리에 두므로 서버를 다시 켜면 처음 상태로 돌아갑니다.
"""
MODE = "fake"


def reset():
    """기록장을 처음 상태로 되돌림 (테스트가 매번 부름)."""
```

`aniwhere/api/main.py`:

```python
"""HTTP 입구. 화면(frontend/)이 부르는 /api/* 와 화면 파일을 함께 제공합니다.

판단 로직을 두지 않습니다: 서비스(aniwhere/service.py, 또는 ANIWHERE_FAKE=1이면 aniwhere/api/fake.py)의 함수를
그대로 부르고 반환값을 그대로 돌려줍니다. 응답 형식의 원본은 service.py의 독스트링입니다.
실행: make api  /  make api FAKE=1  /  문서: http://localhost:8000/docs
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from aniwhere.config import REPO


def fake_mode() -> bool:
    return os.environ.get("ANIWHERE_FAKE", "") not in ("", "0")


def get_service():
    """라우트가 부를 서비스 모듈. 테스트는 app.dependency_overrides로 바꿔 끼웁니다."""
    if fake_mode():
        from aniwhere.api import fake
        return fake
    from aniwhere import service
    return service


def _mode(svc) -> str:
    return getattr(svc, "MODE", "real")


def create_app(frontend_dir: Path | None = REPO / "frontend") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = app.dependency_overrides.get(get_service, get_service)()
        if _mode(svc) == "real":
            svc.warm_up()
        yield

    app = FastAPI(title="AniWhere API", lifespan=lifespan)

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health")
    def health(svc=Depends(get_service)):
        mode = _mode(svc)
        if mode == "real":
            try:
                svc.db().execute("SELECT 1")
            except Exception as e:  # DB가 꺼져 있으면 503
                return JSONResponse(status_code=503, content={"status": "db_unavailable", "detail": str(e)})
        return {"status": "ok", "mode": mode}

    return app


app = create_app()
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: `test_health_reports_mode PASSED`

- [ ] **Step 6: 기존 테스트도 깨지지 않았는지**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 모두 통과 (DB 없으면 `test_app.py`는 skip).

- [ ] **Step 7: 커밋**

```bash
git add requirements.txt aniwhere/api tests/test_api.py
git commit -m "API 서버 뼈대: FastAPI 앱 팩토리, 서비스 주입, /api/health

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 가짜 서비스 `fake.py`와 service↔fake 어긋남 방지 테스트

**Files:**
- Modify: `aniwhere/api/fake.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `aniwhere.service`의 공개 함수 이름과 독스트링 (`service.py` 참고)
- Produces: `fake.py`에 `service.py`의 공개 함수와 같은 이름의 함수 전부(`db`·`warm_up` 제외) + `reset()`, 상수 `HERO = "tmdb:65930"`, `TITAN = "tmdb:1429"`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py`에 추가:

```python
import inspect
import re

from aniwhere import service

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


def test_fake_rejects_bad_input_like_service():
    with pytest.raises(ValueError):
        fake.where_to_watch("tmdb:0")
    with pytest.raises(ValueError):
        fake.save_record(fake.HERO, -1)
    with pytest.raises(ValueError):
        fake.save_record(fake.HERO, 999)
    with pytest.raises(ValueError):
        fake.review(fake.HERO, 49, "ask", None)
    with pytest.raises(ValueError):
        fake.review(fake.HERO, 49, "오타")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k fake`
Expected: `test_fake_has_every_service_function` FAIL (fake.py에 함수 없음), 나머지 AttributeError.

- [ ] **Step 3: fake.py 구현**

`aniwhere/api/fake.py`의 `MODE`·독스트링 아래에 추가:

```python
import datetime as dt

HERO, TITAN = "tmdb:65930", "tmdb:1429"
USER = "local"

SERIES = {
    HERO: {"series_id": HERO, "name": "나의 히어로 아카데미아", "title": "My Hero Academia", "total_episodes": 138,
           "poster_url": None, "genres": ["Action", "Comedy", "School"]},
    TITAN: {"series_id": TITAN, "name": "진격의 거인", "title": "Attack on Titan", "total_episodes": 89,
            "poster_url": None, "genres": ["Action", "Drama", "Mystery"]},
}
SOURCE = {"text": "미도리야는 올마이트에게서 원 포 올을 물려받는다.", "abs_ep": 2,
          "url": "https://bokunoheroacademia.fandom.com/wiki/Episode_2", "license": "CC BY-SA 3.0"}
ASK_SEEN = "어디까지 봤어요? 마지막으로 본 회차를 알려 주세요."
MODES = ("summary", "characters", "last", "ask")

_records: dict[str, dict] = {}


def reset():
    """기록장을 처음 상태로 되돌림 (테스트가 매번 부름)."""
    _records.clear()
    _records[HERO] = {"seen_ep": 49, "rating": None, "updated_at": "2026-10-05T21:00:00+09:00"}


reset()


def _series(series_id):
    info = SERIES.get(series_id)
    if not info:
        raise ValueError(f"모르는 작품입니다: {series_id}")
    return info


def _seen(series_id, seen_ep):
    if seen_ep is None and series_id in _records:
        return _records[series_id]["seen_ep"]
    return seen_ep


def find(question: str, history: list[dict] | None = None, *, user_id=USER) -> dict:
    return {"status": "found", "answer": "진격의 거인 1기 1화 〈2000년 후의 너에게〉 같아요.",
            "candidates": [{"series_id": TITAN, "title": "진격의 거인", "abs_ep": 1, "label": "1기 1화", "score": 0.91}],
            "follow_up": None,
            "sources": [{"text": "리바이가 입체기동으로 거인을 벤다.", "abs_ep": 1,
                         "url": "https://attackontitan.fandom.com/wiki/Episode_1", "license": "CC BY-SA 3.0"}]}


def where_to_watch(series_id: str) -> dict:
    info = _series(series_id)
    return {"series_id": series_id, "title": info["name"],
            "seasons": [{"name": "시즌 3", "providers": ["Laftel", "Netflix"], "checked_at": "2026-10-05",
                         "link": "https://www.justwatch.com/kr"}],
            "attribution": "시청처 정보: JustWatch (TMDB 제공). 구독형 제공처만 표시합니다."}


def review(series_id: str, seen_ep: int | None = None, mode: str = "summary", question: str | None = None, *,
           user_id=USER) -> dict:
    _series(series_id)
    if mode not in MODES:
        raise ValueError(f"mode는 {list(MODES)} 중 하나여야 합니다: {mode!r}")
    if mode == "ask" and not (question or "").strip():
        raise ValueError("직접 질문 모드에는 질문이 필요합니다")
    seen_ep = _seen(series_id, seen_ep)
    if seen_ep is None:
        return {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
    return {"answer": f"{seen_ep}화까지의 요약입니다. 미도리야는 올마이트의 힘을 물려받았어요 [1].",
            "seen_ep": seen_ep, "sources": [SOURCE], "follow_up": None}


def dictionary(series_id: str, seen_ep: int | None = None, *, user_id=USER) -> dict:
    _series(series_id)
    seen_ep = _seen(series_id, seen_ep)
    if seen_ep is None:
        return {"seen_ep": None, "entries": [], "follow_up": ASK_SEEN}
    return {"seen_ep": seen_ep, "follow_up": None, "entries": [
        {"kind": "character", "name": "미도리야 이즈쿠", "text": "올마이트에게 힘을 물려받은 학생.", "first_ep": 1, "url": None},
        {"kind": "character", "name": "올마이트", "text": "평화의 상징이라 불리는 히어로.", "first_ep": 1, "url": None},
        {"kind": "term", "name": "원 포 올", "text": "힘을 축적해 다음 계승자에게 전달하는 개성.", "first_ep": 2, "url": None},
    ]}


def recommend(likes: str, *, user_id=USER) -> dict:
    return {"mood": "반전과 긴장감", "follow_up": None,
            "picks": [{"series_id": TITAN, "title": "진격의 거인", "reason": "매 화 뒤집히는 전개가 비슷해요.",
                       "poster_url": None, "genres": SERIES[TITAN]["genres"]}]}


def save_record(series_id: str, seen_ep: int, rating: float | None = None, *, user_id=USER) -> dict:
    info = _series(series_id)
    if not isinstance(seen_ep, int) or seen_ep < 0 or seen_ep > info["total_episodes"]:
        raise ValueError(f"본 회차는 0부터 {info['total_episodes']}까지의 정수여야 합니다: {seen_ep!r}")
    if rating is not None and not 0.5 <= rating <= 5:
        raise ValueError(f"평점은 0.5부터 5까지입니다: {rating!r}")
    old = _records.get(series_id, {})
    _records[series_id] = {"seen_ep": seen_ep, "rating": rating if rating is not None else old.get("rating"),
                           "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    return get_record(series_id)


def get_record(series_id: str, *, user_id=USER) -> dict | None:
    r = _records.get(series_id)
    if not r:
        return None
    info = SERIES[series_id]
    return {"series_id": series_id, "name": info["name"], "total_episodes": info["total_episodes"], **r}


def list_records(*, user_id=USER) -> list[dict]:
    return [get_record(sid) for sid in _records]


def delete_record(series_id: str, *, user_id=USER) -> bool:
    return _records.pop(series_id, None) is not None


def search_series(query: str | None = None, limit: int = 50) -> list[dict]:
    rows = [{k: v for k, v in s.items() if k in ("series_id", "name", "title", "total_episodes")} for s in SERIES.values()]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r["name"].lower() or q in r["title"].lower()]
    return rows[:limit]


def series(series_id: str) -> dict | None:
    return SERIES.get(series_id)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: 모두 PASS. `test_fake_response_keys_match_service_docstring`은 `find`·`where_to_watch`·`review`·`dictionary`·`recommend`·`save_record` 6개 PASS, 나머지 SKIP.

실패하면 서비스 독스트링의 키와 가짜 응답 키를 비교해서 **가짜 쪽을** 고친다 (독스트링이 원본). 단, `save_record` 독스트링은 `→ 저장된 기록 {…}`이므로 `→\s*\{`에 안 걸려 SKIP될 수 있다 — 그 경우 `service.py`의 해당 독스트링을 `→ {series_id, name, seen_ep, total_episodes, rating, updated_at} (저장된 기록)`으로 고쳐 비교 대상에 넣는다.

- [ ] **Step 5: 커밋**

```bash
git add aniwhere/api/fake.py aniwhere/service.py tests/test_api.py
git commit -m "가짜 서비스: DB·LLM 없이 service.py와 같은 형식으로 응답, 독스트링과 어긋나면 테스트 실패

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 조회 라우트 — 작품 목록·정보·시청처·사전

**Files:**
- Modify: `aniwhere/api/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `svc.search_series(query, limit)`, `svc.series(id)`, `svc.where_to_watch(id)`, `svc.dictionary(id, seen_ep)`
- Produces: `GET /api/series`, `GET /api/series/{series_id}`, `GET /api/series/{series_id}/where-to-watch`, `GET /api/series/{series_id}/dictionary`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py`에 추가:

```python
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


def test_where_to_watch_unknown_series_is_400(client):
    r = client.get("/api/series/tmdb:0/where-to-watch")
    assert r.status_code == 400
    assert "모르는 작품" in r.json()["detail"]


def test_dictionary_uses_record_when_seen_ep_missing(client):
    body = client.get(f"/api/series/{fake.HERO}/dictionary").json()
    assert body["seen_ep"] == 49 and body["entries"] and body["follow_up"] is None


def test_dictionary_asks_when_no_record_and_no_seen_ep(client):
    body = client.get(f"/api/series/{fake.TITAN}/dictionary").json()
    assert body == {"seen_ep": None, "entries": [], "follow_up": fake.ASK_SEEN}


def test_dictionary_explicit_seen_ep(client):
    body = client.get(f"/api/series/{fake.TITAN}/dictionary", params={"seen_ep": 7}).json()
    assert body["seen_ep"] == 7
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k "series or where or dictionary"`
Expected: 모두 404 Not Found로 FAIL.

- [ ] **Step 3: 라우트 구현**

`aniwhere/api/main.py` import에 추가:

```python
from fastapi import Depends, FastAPI, HTTPException, Query
```

모듈 수준(함수 밖)에 도우미 추가:

```python
def _or_404(value, what: str):
    if value is None:
        raise HTTPException(status_code=404, detail=f"없습니다: {what}")
    return value
```

`create_app` 안, `health` 라우트 아래에 추가:

```python
    @app.get("/api/series")
    def series_list(q: str | None = None, limit: int = Query(50, ge=1, le=200), svc=Depends(get_service)):
        return svc.search_series(q, limit)

    @app.get("/api/series/{series_id}")
    def series_info(series_id: str, svc=Depends(get_service)):
        return _or_404(svc.series(series_id), series_id)

    @app.get("/api/series/{series_id}/where-to-watch")
    def where_to_watch(series_id: str, svc=Depends(get_service)):
        return svc.where_to_watch(series_id)

    @app.get("/api/series/{series_id}/dictionary")
    def dictionary(series_id: str, seen_ep: int | None = None, svc=Depends(get_service)):
        return svc.dictionary(series_id, seen_ep)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add aniwhere/api/main.py tests/test_api.py
git commit -m "API 조회 라우트: 작품 목록·정보, 시청처(07), 회차 기준 사전(08)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: LLM 라우트 — 찾기·복습·추천, 인자 그대로 전달 테스트

**Files:**
- Modify: `aniwhere/api/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `svc.find(question, history)`, `svc.review(series_id, seen_ep, mode, question)`, `svc.recommend(likes)`
- Produces: `POST /api/find`, `POST /api/review`, `POST /api/recommend`; 요청 모델 `Turn`, `FindRequest`, `ReviewRequest`, `RecommendRequest`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py`에 추가. `Recorder`는 서비스가 받은 인자를 그대로 기록하는 가짜 — "판단 로직 없음"을 확인하는 데 쓴다.

```python
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


def test_recommend(client, recorder):
    r = client.post("/api/recommend", json={"likes": "기생충, 오징어 게임"})
    assert set(r.json()) >= {"mood", "picks"}
    rec, c = recorder
    c.post("/api/recommend", json={"likes": "기생충"})
    assert rec.calls == [("recommend", ("기생충",), {})]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k "find or review or recommend"`
Expected: 404/405로 FAIL.

- [ ] **Step 3: 요청 모델과 라우트 구현**

`aniwhere/api/main.py` import에 추가:

```python
from typing import Literal

from pydantic import BaseModel, Field
```

모듈 수준에 요청 모델 추가 (응답 모델은 만들지 않는다):

```python
class Turn(BaseModel):
    role: str
    content: str


class FindRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[Turn] = []


class ReviewRequest(BaseModel):
    series_id: str
    seen_ep: int | None = None
    mode: Literal["summary", "characters", "last", "ask"] = "summary"
    question: str | None = None


class RecommendRequest(BaseModel):
    likes: str = Field(min_length=1)
```

`create_app` 안, `dictionary` 라우트 아래에 추가:

```python
    @app.post("/api/find")
    def find(body: FindRequest, svc=Depends(get_service)):
        return svc.find(body.question, [t.model_dump() for t in body.history])

    @app.post("/api/review")
    def review(body: ReviewRequest, svc=Depends(get_service)):
        return svc.review(body.series_id, body.seen_ep, body.mode, body.question)

    @app.post("/api/recommend")
    def recommend(body: RecommendRequest, svc=Depends(get_service)):
        return svc.recommend(body.likes)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add aniwhere/api/main.py tests/test_api.py
git commit -m "API LLM 라우트: 기억으로 찾기(05·06), 맞춤 복습(09), 취향 추천(01) — 인자는 그대로 전달

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 기록장 라우트

**Files:**
- Modify: `aniwhere/api/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `svc.list_records()`, `svc.get_record(id)`, `svc.save_record(id, seen_ep, rating)`, `svc.delete_record(id) -> bool`
- Produces: `GET /api/records`, `GET/PUT/DELETE /api/records/{series_id}`; 요청 모델 `RecordRequest`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
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
    assert client.put("/api/records/tmdb:0", json={"seen_ep": 1}).status_code == 400


def test_record_requires_integer_seen_ep(client):
    assert client.put(f"/api/records/{fake.HERO}", json={}).status_code == 422
    assert client.put(f"/api/records/{fake.HERO}", json={"seen_ep": "열둘"}).status_code == 422
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k record`
Expected: `test_records_crud`·`test_record_*` FAIL (404/405). (`test_fake_record_roundtrip`은 이미 PASS.)

- [ ] **Step 3: 구현**

`aniwhere/api/main.py` import에 `Response` 추가:

```python
from fastapi import Depends, FastAPI, HTTPException, Query, Response
```

요청 모델 추가:

```python
class RecordRequest(BaseModel):
    seen_ep: int
    rating: float | None = None
```

`create_app` 안, `recommend` 라우트 아래에 추가:

```python
    @app.get("/api/records")
    def records(svc=Depends(get_service)):
        return svc.list_records()

    @app.get("/api/records/{series_id}")
    def record(series_id: str, svc=Depends(get_service)):
        return _or_404(svc.get_record(series_id), f"{series_id}의 기록")

    @app.put("/api/records/{series_id}")
    def save_record(series_id: str, body: RecordRequest, svc=Depends(get_service)):
        return svc.save_record(series_id, body.seen_ep, body.rating)

    @app.delete("/api/records/{series_id}", status_code=204)
    def delete_record(series_id: str, svc=Depends(get_service)):
        if not svc.delete_record(series_id):
            raise HTTPException(status_code=404, detail=f"없습니다: {series_id}의 기록")
        return Response(status_code=204)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add aniwhere/api/main.py tests/test_api.py
git commit -m "API 기록장 라우트(13): 목록·조회·저장·삭제

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: service↔라우트 빠짐 방지 테스트, 화면(frontend/) 서빙

**Files:**
- Modify: `aniwhere/api/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `create_app(frontend_dir)`, `SERVICE_FUNCS` (Task 2)
- Produces: `frontend_dir`가 있으면 `/`에서 정적 파일 제공

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from aniwhere.api import main as api_main


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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k "route or frontend"`
Expected: `test_every_service_function_has_a_route` PASS (Task 3~5에서 전부 연결됨 — 아니면 빠진 라우트가 있다는 뜻이니 추가), `test_frontend_is_served_when_folder_exists` FAIL (`/` 404).

- [ ] **Step 3: mount 구현**

`aniwhere/api/main.py` import에 추가:

```python
from fastapi.staticfiles import StaticFiles
```

`create_app` 안, 마지막 라우트 뒤·`return app` 앞에 추가 (라우트 등록 뒤에 mount해야 `/api/*`가 먼저 매칭됨):

```python
    # 화면 파일. 폴더가 없으면(아직 main에 frontend/가 없을 때) API만 뜬다.
    if frontend_dir and Path(frontend_dir).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests -q`
Expected: `test_api.py` 모두 PASS, 기존 테스트 변화 없음.

- [ ] **Step 5: 커밋**

```bash
git add aniwhere/api/main.py tests/test_api.py
git commit -m "API 서버가 frontend/ 화면을 함께 제공, 서비스 함수가 라우트에서 빠지면 테스트로 잡음

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 실행 명령(Makefile·README)과 실제 실행 확인

**Files:**
- Modify: `Makefile`
- Modify: `README.md:50-56` (실행 명령 코드 블록)
- Modify: `tests/README.md` (한 줄)

**Interfaces:**
- Consumes: `aniwhere.api.main:app`, `ANIWHERE_FAKE`

- [ ] **Step 1: Makefile에 `api` 타깃**

`.PHONY` 줄에 `api` 추가하고, `run:` 타깃 아래에:

```make
# API 서버 + 화면 (http://localhost:8000, 문서 /docs). DB·LLM 없이 가짜 응답으로 띄우기: make api FAKE=1
FAKE ?=
api:
	ANIWHERE_FAKE=$(FAKE) .venv/bin/uvicorn aniwhere.api.main:app --reload --port 8000
```

- [ ] **Step 2: README 실행 명령에 추가**

`README.md`의 실행 명령 블록에서 `make run` 줄 아래에:

```
make api                  # API 서버 + 화면 (http://localhost:8000, 문서 /docs)
make api FAKE=1           # DB·LLM 없이 가짜 응답으로 띄우기 (프론트엔드 개발용)
```

`tests/README.md`에 한 줄 추가: `- test_api.py: API 서버. DB·LLM 없이 가짜 서비스로 돕니다. service.py에 함수를 추가하면 라우트도 추가해야 통과합니다.`

- [ ] **Step 3: 가짜 모드 실제 실행**

Run (백그라운드로 띄우고 호출 뒤 종료):

```bash
make api FAKE=1 > /tmp/aniwhere-api-fake.log 2>&1 &
sleep 3
curl -s localhost:8000/api/health
curl -s localhost:8000/api/records/tmdb:65930
curl -s -X POST localhost:8000/api/review -H 'content-type: application/json' -d '{"series_id":"tmdb:65930","mode":"last"}'
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/
kill %1
```

Expected: `{"status":"ok","mode":"fake"}`, 49화 기록, 복습 응답, `/`는 `404`(main에 `frontend/` 없음).

- [ ] **Step 4: 실제 모드 실행 (실제 DB가 있는 맥에서만)**

```bash
make api > /tmp/aniwhere-api.log 2>&1 &
sleep 15     # 임베딩 모델 로딩
curl -s localhost:8000/api/health
curl -s 'localhost:8000/api/series?q=히어로'
curl -s -X POST localhost:8000/api/find -H 'content-type: application/json' -d '{"question":"키 작은 아저씨가 칼 들고 날아다녀"}'
kill %1
```

Expected: `{"status":"ok","mode":"real"}`, 작품 목록, `candidates`에 진격의 거인. 출력을 그대로 PR 본문에 적는다. DB가 없으면 `/api/health`가 503 — 그 경우 이 단계는 PR 본문에 "미실행"으로 적는다.

- [ ] **Step 5: 전체 테스트와 커밋**

Run: `make test`
Expected: 모두 통과.

```bash
git add Makefile README.md tests/README.md
git commit -m "실행 명령 추가: make api, make api FAKE=1

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 끝난 뒤

- PR 생성: `feat/gwonjae-api-server` → `main`, 본문은 `.github/pull_request_template.md`. 시청 여정 단계는 "모든 기능의 입구(service.py의 표를 따름)". Task 7의 실행 출력 포함.
- Slack `#빅데이터_공훈의_팀방`에 의진 앞으로: PR 링크, `make api FAKE=1`로 뜨는 것, `app.js`의 `mock` → `fetch('/api/...')` 교체 지점, `/docs` 주소.
