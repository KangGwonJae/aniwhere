"""질문 임베딩. 청크를 임베딩한 모델(config의 embedding.model)과 같은 모델을 써야 검색이 됩니다."""
from aniwhere.config import section

_model = None
_override = None


def set_embedder(fn):
    """테스트용: 모델을 내려받지 않고 fn(질문) -> 벡터로 바꿔 끼움. None이면 원래대로."""
    global _override
    _override = fn


def embed_query(text: str) -> list[float]:
    if _override is not None:
        return list(_override(text))
    global _model
    cfg = section("embedding")
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(cfg["model"], device=section("retrieval").get("query_device"))
        if cfg.get("max_seq_length"):
            _model.max_seq_length = cfg["max_seq_length"]
    vec = _model.encode([(cfg.get("query_prefix") or "") + text], normalize_embeddings=True, show_progress_bar=False)[0]
    return [float(x) for x in vec]
