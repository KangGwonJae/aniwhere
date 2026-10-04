from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aniwhere.agent.agent import AniWhereAgent
from aniwhere.chunking.service import document_chunks, semantic_chunks
from aniwhere.ingest.catalog import ROOT, anime_catalog, load_anime
from aniwhere.retrieval.embeddings import get_embedding_model
from aniwhere.retrieval.vector_store import SQLiteVectorStore

WEB_DIR = ROOT / "frontend"
DB_PATH = ROOT / "data" / "index" / "aniwhere.sqlite3"


def build_agent() -> AniWhereAgent:
    anime = load_anime()
    embeddings = get_embedding_model()
    store = SQLiteVectorStore(DB_PATH)
    semantic = semantic_chunks(anime)
    whole = document_chunks(anime)
    store.replace_collection("semantic", semantic, embeddings.encode(item["text"] for item in semantic))
    store.replace_collection("whole", whole, embeddings.encode(item["text"] for item in whole))
    return AniWhereAgent(store, embeddings, anime)


AGENT = build_agent()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print(f"[AniWhere] {format % args}")

    def json_response(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.json_response({"status": "ok", "semantic_chunks": AGENT.store.count("semantic"), "vector_db": str(DB_PATH.name), "embedding": AGENT.embeddings.name})
        elif parsed.path == "/api/catalog":
            self.json_response(anime_catalog())
        elif parsed.path == "/api/search":
            query = params.get("q", [""])[0].strip()
            self.json_response(AGENT.analyze(query) if query else {"error": "질문을 입력해주세요."}, 200 if query else 400)
        elif parsed.path == "/api/recap":
            try:
                self.json_response(AGENT.recap(params["anime_id"][0], int(params["until"][0])))
            except (KeyError, ValueError):
                self.json_response({"error": "anime_id와 until 값이 필요합니다."}, 400)
        elif parsed.path == "/api/streaming":
            try:
                self.json_response(AGENT.streaming(params["anime_id"][0]))
            except KeyError:
                self.json_response({"error": "지원하지 않는 작품입니다."}, 404)
        elif parsed.path == "/api/compare":
            query = params.get("q", [""])[0].strip()
            self.json_response(AGENT.compare(query) if query else {"error": "질문을 입력해주세요."}, 200 if query else 400)
        else:
            super().do_GET()


def main() -> None:
    port = int(os.getenv("ANIWHERE_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"AniWhere is running at http://127.0.0.1:{port}")
    print(f"Vector DB: {DB_PATH} ({AGENT.store.count('semantic')} semantic chunks)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
