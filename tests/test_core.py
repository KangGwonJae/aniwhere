import tempfile
import unittest
from pathlib import Path

import numpy as np

from aniwhere.api.server import AGENT
from aniwhere.chunking.service import semantic_chunks
from aniwhere.ingest.catalog import load_anime
from aniwhere.retrieval.embeddings import LocalKoreanEmbedding
from aniwhere.retrieval.vector_store import SQLiteVectorStore


class CoreTests(unittest.TestCase):
    def test_chunk_types_and_metadata(self):
        chunks = semantic_chunks(load_anime())
        types = {chunk["metadata"]["chunk_type"] for chunk in chunks}
        self.assertEqual(types, {"anime_summary", "character", "event", "terminology", "streaming"})
        self.assertTrue(all("spoiler_until" in chunk["metadata"] for chunk in chunks))

    def test_vector_store_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteVectorStore(Path(directory) / "test.sqlite3")
            records = [
                {"id": "a", "text": "a", "metadata": {"episode": 3}},
                {"id": "b", "text": "b", "metadata": {"episode": 9}},
            ]
            vectors = np.array([[1, 0], [1, 0]], dtype=np.float32)
            store.replace_collection("test", records, vectors)
            result = store.query("test", np.array([1, 0], dtype=np.float32), filters={"episode": {"lte": 5}})
            self.assertEqual([item["id"] for item in result], ["a"])

    def test_local_embedding_is_deterministic(self):
        model = LocalKoreanEmbedding()
        first, second = model.encode(["노란 머리 번개", "노란 머리 번개"])
        np.testing.assert_array_equal(first, second)

    def test_levi_colloquial_memory_query(self):
        result = AGENT.analyze("키 작은 아저씨가 커터칼같이 생긴 칼 들고 날아다녀")
        self.assertEqual(result["top_candidate"]["anime_id"], "attack-on-titan")
        self.assertEqual(result["top_candidate"]["character_name"], "리바이")

    def test_explicit_title_scopes_search(self):
        result = AGENT.analyze("주술회전에서 손가락을 먹는 장면")
        self.assertEqual(result["top_candidate"]["anime_id"], "anilist-113415")

    def test_jujutsu_finger_memory_without_title(self):
        for query in ("어떤 학생이 손가락 먹는 애니야", "핑크머리 학생이 손가락을 먹었어"):
            with self.subTest(query=query):
                result = AGENT.analyze(query)
                self.assertEqual(result["top_candidate"]["title"], "주술회전")

    def test_quirkless_student_inherits_power(self):
        queries = (
            "원래 능력 없는데 힘을 물려받은 학생이 나온 애니야",
            "초능력이 없던 소년이 최고의 영웅에게 능력을 계승받았어",
        )
        for query in queries:
            with self.subTest(query=query):
                result = AGENT.analyze(query)
                self.assertEqual(result["top_candidate"]["anime_id"], "my-hero-academia")

    def test_curated_titles_receive_imported_posters(self):
        anime = {item["id"]: item for item in load_anime()}
        for anime_id in ("demon-slayer", "my-hero-academia", "attack-on-titan"):
            self.assertTrue(anime[anime_id].get("poster_url"))

    def test_episode_mode_returns_watch_point(self):
        result = AGENT.analyze("어디까지 봤는지 찾아줘: 올마이트가 올포원과 싸우고 손가락을 가리켰어")
        self.assertEqual(result["intent"], "episode")
        self.assertEqual(result["episode"]["season"], 3)
        self.assertEqual(result["episode"]["episode"], 11)
        self.assertIn("마지막으로 본 지점", result["answer"])


if __name__ == "__main__":
    unittest.main()
