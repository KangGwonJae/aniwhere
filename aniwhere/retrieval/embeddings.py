from __future__ import annotations

import os
import re
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer


class LocalKoreanEmbedding:
    """Deterministic offline embedding for the zero-key demo.

    Character n-grams work reasonably well for Korean inflections and misspellings.
    The interface can later be replaced with a sentence-transformer or API embedding.
    """

    name = "local-korean-char-ngram-v1"

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions
        self.vectorizer = HashingVectorizer(
            n_features=dimensions,
            analyzer="char_wb",
            ngram_range=(2, 5),
            alternate_sign=False,
            norm="l2",
        )

    @staticmethod
    def expand(text: str) -> str:
        aliases = {
            "노랑 머리": "노란 머리 금발",
            "노란머리": "노란 머리 금발",
            "번개 기술": "번개 전기 능력",
            "전기 기술": "전기 번개 능력",
            "바보": "멍해짐 사고력 저하 바보 같은 표정",
            "무서워": "겁이 많음 공포",
            "겁쟁이": "겁이 많음 공포",
            "올포원": "올 포 원",
            "나히아": "나의 히어로 아카데미아",
            "히로아카": "나의 히어로 아카데미아",
            "진격거": "진격의 거인",
            "귀칼": "귀멸의 칼날",
            "커터칼": "교체식 칼날 초경질 칼 쌍검",
            "날아다": "공중 이동 와이어 입체기동장치",
            "키 작은": "작은 체구 단신",
            "아저씨": "성인 남자 병장",
            "손가락 먹": "양면 스쿠나 손가락 특급 주물 집어삼킨 이타도리 유지 주술회전",
            "손가락을 먹": "양면 스쿠나 손가락 특급 주물 집어삼킨 이타도리 유지 주술회전",
            "핑크머리": "분홍 머리 이타도리 유지 학생",
            "원래 능력 없": "무개성 초능력이 없던 미도리야 이즈쿠 데쿠",
            "능력이 없": "무개성 초능력이 없음",
            "힘을 물려받": "원 포 올 계승 힘을 계승받은 미도리야 올마이트 나의 히어로 아카데미아",
            "능력을 물려받": "원 포 올 계승 힘을 계승받은 미도리야 올마이트 나의 히어로 아카데미아",
            "계승받": "힘을 물려받은 원 포 올 미도리야 올마이트 나의 히어로 아카데미아",
            "최고의 영웅": "최고의 히어로 평화의 상징 올마이트",
        }
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        additions = [value for key, value in aliases.items() if key in normalized]
        return " ".join([normalized, *additions])

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        expanded = [self.expand(text) for text in texts]
        return self.vectorizer.transform(expanded).toarray().astype(np.float32)


def get_embedding_model() -> LocalKoreanEmbedding:
    # A stable factory boundary for a future multilingual sentence-transformer.
    os.environ.setdefault("ANIWHERE_EMBEDDING_MODE", "local")
    return LocalKoreanEmbedding()
