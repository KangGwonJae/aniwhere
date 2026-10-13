"""HTTP 입구. 화면(frontend/)이 부르는 /api/* 와 화면 파일을 함께 제공합니다.

판단 로직을 두지 않습니다: 서비스(aniwhere/service.py, 또는 ANIWHERE_FAKE=1이면 aniwhere/api/fake.py)의 함수를
그대로 부르고 반환값을 그대로 돌려줍니다. 응답 형식의 원본은 service.py의 독스트링입니다.
실행: make api  /  make api FAKE=1  /  문서: http://localhost:8000/docs
"""
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt

from aniwhere.config import REPO
from aniwhere.retrieval.catalog import UnknownSeries

log = logging.getLogger(__name__)

TEXT = Field(min_length=1, max_length=1000)     # 사용자가 쓰는 글. 너무 길면 LLM 비용·지연이 그대로 늘어남
USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def browser_user(x_aniwhere_user: str | None = Header(None)) -> str:
    """로그인 전에는 브라우저가 만든 익명 ID로 기록을 나눕니다.

    헤더가 없는 기존 로컬 실행·API 사용자는 이전처럼 ``local``을 사용합니다.
    """
    if x_aniwhere_user is None:
        return "local"
    if not USER_ID_RE.fullmatch(x_aniwhere_user):
        raise HTTPException(status_code=400, detail="올바르지 않은 브라우저 사용자 ID입니다")
    return x_aniwhere_user


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=1000)


class ChatTurn(BaseModel):
    """에이전트 대화의 한 턴. role을 Literal로 막는 이유: system이면 프롬프트를 덮어쓸 수 있고 tool이면 OpenAI가 400을 냄.
    context는 서버가 전 응답에서 준 것을 화면이 그대로 되돌려 보내는 값(화면은 해석하지 않음)."""
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)
    context: dict | None = None


class ChatRequest(BaseModel):
    message: str = TEXT
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)     # 왕복 10번. 화면은 history.slice(-20)


class FindRequest(BaseModel):
    question: str = TEXT
    history: list[Turn] = Field(default_factory=list, max_length=20)     # 대화 전체가 LLM에 들어가므로 길이 제한


class ReviewRequest(BaseModel):
    series_id: str
    seen_ep: int | None = None
    mode: Literal["summary", "characters", "last", "ask"] = "summary"
    question: str | None = Field(None, max_length=1000)


class RecommendRequest(BaseModel):
    likes: str = TEXT


class RecordRequest(BaseModel):
    seen_ep: StrictInt          # JSON true·"12"가 정수로 바뀌어 저장되지 않게
    rating: float | None = None


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


def _or_404(value, what: str):
    if value is None:
        raise HTTPException(status_code=404, detail=f"없습니다: {what}")
    return value


def create_app(frontend_dir: Path | None = REPO / "frontend") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = app.dependency_overrides.get(get_service, get_service)()
        if _mode(svc) == "real":
            try:
                svc.warm_up()
            except Exception as e:  # DB가 꺼져 있어도 서버는 뜨고, /api/health가 503으로 알려 줌
                log.warning("warm_up 실패 — DB나 모델을 준비하지 못함: %s", e)
        yield

    app = FastAPI(title="AniWhere API", lifespan=lifespan)

    @app.exception_handler(UnknownSeries)
    async def unknown_series(_, exc: UnknownSeries):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health")
    def health(svc=Depends(get_service)):
        mode = _mode(svc)
        if mode == "real":
            try:
                svc.db().execute("SELECT 1")
            except Exception as e:  # DB가 꺼져 있으면 503. 접속 정보가 담길 수 있는 원문은 서버 로그에만
                log.warning("DB 연결 확인 실패: %s", e)
                return JSONResponse(status_code=503, content={"status": "db_unavailable",
                                                              "detail": "DB에 연결할 수 없습니다"})
        return {"status": "ok", "mode": mode}

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
    def dictionary(series_id: str, seen_ep: int | None = None, svc=Depends(get_service),
                   user_id: str = Depends(browser_user)):
        return svc.dictionary(series_id, seen_ep, user_id=user_id)

    @app.post("/api/find")
    def find(body: FindRequest, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return svc.find(body.question, [t.model_dump() for t in body.history], user_id=user_id)

    @app.post("/api/review")
    def review(body: ReviewRequest, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return svc.review(body.series_id, body.seen_ep, body.mode, body.question, user_id=user_id)

    @app.post("/api/recommend")
    def recommend(body: RecommendRequest, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return svc.recommend(body.likes, user_id=user_id)

    @app.post("/api/chat")
    def chat(body: ChatRequest, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return svc.chat(body.message, [t.model_dump() for t in body.history], user_id=user_id)

    @app.get("/api/records")
    def records(svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return svc.list_records(user_id=user_id)

    @app.get("/api/records/{series_id}")
    def record(series_id: str, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        return _or_404(svc.get_record(series_id, user_id=user_id), f"{series_id}의 기록")

    @app.put("/api/records/{series_id}")
    def save_record(series_id: str, body: RecordRequest, svc=Depends(get_service),
                    user_id: str = Depends(browser_user)):
        return svc.save_record(series_id, body.seen_ep, body.rating, user_id=user_id)

    @app.delete("/api/records/{series_id}", status_code=204)
    def delete_record(series_id: str, svc=Depends(get_service), user_id: str = Depends(browser_user)):
        if not svc.delete_record(series_id, user_id=user_id):
            raise HTTPException(status_code=404, detail=f"없습니다: {series_id}의 기록")
        return Response(status_code=204)

    # 화면 파일. 폴더가 없으면(아직 main에 frontend/가 없을 때) API만 뜬다.
    if frontend_dir and Path(frontend_dir).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


app = create_app()
