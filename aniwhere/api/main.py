"""HTTP 입구. 화면(frontend/)이 부르는 /api/* 와 화면 파일을 함께 제공합니다.

판단 로직을 두지 않습니다: 서비스(aniwhere/service.py, 또는 ANIWHERE_FAKE=1이면 aniwhere/api/fake.py)의 함수를
그대로 부르고 반환값을 그대로 돌려줍니다. 응답 형식의 원본은 service.py의 독스트링입니다.
실행: make api  /  make api FAKE=1  /  문서: http://localhost:8000/docs
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aniwhere.config import REPO
from aniwhere.retrieval.catalog import UnknownSeries


class Turn(BaseModel):
    role: str
    content: str


TEXT = Field(min_length=1, max_length=1000)     # 사용자가 쓰는 글. 너무 길면 LLM 비용·지연이 그대로 늘어남


class FindRequest(BaseModel):
    question: str = TEXT
    history: list[Turn] = []


class ReviewRequest(BaseModel):
    series_id: str
    seen_ep: int | None = None
    mode: Literal["summary", "characters", "last", "ask"] = "summary"
    question: str | None = Field(None, max_length=1000)


class RecommendRequest(BaseModel):
    likes: str = TEXT


class RecordRequest(BaseModel):
    seen_ep: int
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
            svc.warm_up()
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
            except Exception as e:  # DB가 꺼져 있으면 503
                return JSONResponse(status_code=503, content={"status": "db_unavailable", "detail": str(e)})
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
    def dictionary(series_id: str, seen_ep: int | None = None, svc=Depends(get_service)):
        return svc.dictionary(series_id, seen_ep)

    @app.post("/api/find")
    def find(body: FindRequest, svc=Depends(get_service)):
        return svc.find(body.question, [t.model_dump() for t in body.history])

    @app.post("/api/review")
    def review(body: ReviewRequest, svc=Depends(get_service)):
        return svc.review(body.series_id, body.seen_ep, body.mode, body.question)

    @app.post("/api/recommend")
    def recommend(body: RecommendRequest, svc=Depends(get_service)):
        return svc.recommend(body.likes)

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

    return app


app = create_app()
