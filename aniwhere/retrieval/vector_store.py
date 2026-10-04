from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np


class SQLiteVectorStore:
    """Small persistent vector DB used by the demo.

    Vectors and metadata live in SQLite; similarity is calculated in memory because
    the demo corpus is intentionally small. The storage/search boundary is identical
    to hosted vector stores, so Qdrant/Chroma can replace this module later.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                collection_name TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                vector BLOB NOT NULL,
                dimensions INTEGER NOT NULL
            )"""
        )
        self.connection.commit()

    def replace_collection(self, collection: str, records: list[dict[str, Any]], vectors: np.ndarray) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM vectors WHERE collection_name = ?", (collection,))
            self.connection.executemany(
                "INSERT INTO vectors VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        record["id"], collection, record["text"],
                        json.dumps(record["metadata"], ensure_ascii=False),
                        vector.astype(np.float32).tobytes(), len(vector),
                    )
                    for record, vector in zip(records, vectors, strict=True)
                ],
            )

    def count(self, collection: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM vectors WHERE collection_name = ?", (collection,)
        ).fetchone()
        return int(row["count"])

    def query(self, collection: str, query_vector: np.ndarray, limit: int = 8,
              filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM vectors WHERE collection_name = ?", (collection,)
        ).fetchall()
        results = []
        query_norm = float(np.linalg.norm(query_vector)) or 1.0
        for row in rows:
            metadata = json.loads(row["metadata"])
            if filters and any(not self._matches(metadata, key, value) for key, value in filters.items()):
                continue
            vector = np.frombuffer(row["vector"], dtype=np.float32)
            score = float(np.dot(query_vector, vector) / (query_norm * (np.linalg.norm(vector) or 1.0)))
            results.append({"id": row["id"], "text": row["text"], "metadata": metadata, "score": round(score, 4)})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]

    @staticmethod
    def _matches(metadata: dict[str, Any], key: str, expected: Any) -> bool:
        actual = metadata.get(key)
        if isinstance(expected, dict) and "lte" in expected:
            return actual is not None and actual <= expected["lte"]
        return actual == expected
