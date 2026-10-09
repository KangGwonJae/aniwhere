"""03 시청 — 회차 기준 인물·용어 사전(08). "지금 몇 화 보는 중" 기준으로 그 회차까지 나온 항목만 보여 줍니다."""
from aniwhere.retrieval import catalog
from aniwhere.retrieval.search import chunks_upto


def dictionary(db, series_id, *, seen_ep: int) -> list[dict]:
    """[{kind, name, text, first_ep, url, image_url?, role?}] — kind: character(인물) / appearance(인물 외형) / term(용어).

    first_ep는 그 항목이 처음 보이는 회차(None이면 처음부터). 인물은 주연 먼저, 그다음은 먼저 나온 순.
    """
    chunks = chunks_upto(db, series_id, seen_ep=seen_ep, types=["character", "terminology"],
                         include_episode_free=True)
    cards = catalog.character_cards(db, series_id, [int(c["chunk_id"].rsplit(":", 1)[1]) for c in chunks
                                                    if c["chunk_id"].startswith(f"{series_id}:char:")])
    entries = {}
    for c in chunks:
        head, _, body = c["text"].partition("\n")
        url = (c["sources"] or [{}])[0].get("url")
        rest = c["chunk_id"][len(series_id) + 1:]
        if rest.startswith("char:"):
            card = cards.get(int(rest[5:]), {})
            entries[rest] = {"kind": "character", "name": card.get("name") or head, "text": body,
                             "first_ep": c["abs_ep"], "url": url, "image_url": card.get("image_url"),
                             "role": card.get("role"), "name_native": card.get("name_native")}
        elif rest.startswith("wiki:"):
            title = rest[5:].rsplit(":", 1)[0]
            e = entries.setdefault("wiki:" + title, {
                "kind": "appearance" if c["type"] == "character" else "term", "name": title, "text": "",
                "first_ep": c["abs_ep"], "url": url})
            e["text"] = (e["text"] + "\n" + body).strip()        # 한 문서가 여러 조각으로 나뉜 것을 다시 이음
    order = {"character": 0, "term": 1, "appearance": 2}
    return sorted(entries.values(), key=lambda e: (order[e["kind"]], e.get("role") != "MAIN", e["first_ep"] or 0,
                                                   e["name"]))
