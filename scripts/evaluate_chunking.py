from aniwhere.api.server import AGENT

queries = [
    ("노란 머리에 겁이 많고 번개 기술을 쓰는 검사", "demon-slayer"),
    ("전기를 너무 많이 쓰면 바보처럼 멍해지는 학생", "my-hero-academia"),
    ("올마이트가 악당과 싸우고 손가락으로 카메라를 가리킨 장면", "my-hero-academia"),
    ("붉은 목도리를 한 강한 여자 병사", "attack-on-titan"),
    ("키 작은 아저씨가 커터칼같이 생긴 칼 들고 날아다녀", "attack-on-titan"),
]

semantic_hits = 0
whole_hits = 0
for query, expected in queries:
    result = AGENT.compare(query)
    semantic_id = result["semantic"][0]["metadata"]["anime_id"]
    whole_id = result["whole"][0]["metadata"]["anime_id"]
    semantic_hits += semantic_id == expected
    whole_hits += whole_id == expected
    print(f"{query}\n  semantic={semantic_id} / whole={whole_id} / expected={expected}")

print(f"\nTop-1 semantic: {semantic_hits}/{len(queries)}")
print(f"Top-1 whole:    {whole_hits}/{len(queries)}")
