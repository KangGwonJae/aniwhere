"""터미널에서 기능을 바로 불러 보는 명령. 화면 없이 응답(JSON)을 확인할 때 씁니다.

    python -m aniwhere find "올마이트가 올포원과 싸우고 손가락을 가리켰어"
    python -m aniwhere series 진격                       # 작품 ID 찾기
    python -m aniwhere record tmdb:1429 25 --rating 4.5  # 기록장에 저장
    python -m aniwhere review tmdb:1429 --mode last      # 본 회차는 기록장에서 읽음 (--seen 25로 직접 줄 수도 있음)
    python -m aniwhere review tmdb:1429 --seen 25 --mode ask --question "애니는 왜 잡혔어?"
    python -m aniwhere watch tmdb:1429
    python -m aniwhere dict tmdb:1429 --seen 5
    python -m aniwhere recommend "기생충, 오징어 게임, 더 글로리"
"""
import argparse
import json

from aniwhere import service


def main():
    ap = argparse.ArgumentParser(prog="python -m aniwhere", description="AniWhere 기능 확인")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find", help="05·06 기억으로 작품·회차 찾기")
    p.add_argument("question")
    p = sub.add_parser("series", help="제목으로 작품 ID 찾기")
    p.add_argument("query", nargs="?")
    p = sub.add_parser("watch", help="07 시청처 안내")
    p.add_argument("series_id")
    p = sub.add_parser("review", help="09 맞춤 복습")
    p.add_argument("series_id")
    p.add_argument("--seen", type=int, help="본 회차(전체 회차 번호). 없으면 기록장에서 읽음")
    p.add_argument("--mode", default="summary", help="summary / characters / last / ask")
    p.add_argument("--question")
    p = sub.add_parser("dict", help="08 회차 기준 인물·용어 사전")
    p.add_argument("series_id")
    p.add_argument("--seen", type=int)
    p = sub.add_parser("record", help="13 시청 기록장 저장")
    p.add_argument("series_id")
    p.add_argument("seen_ep", type=int)
    p.add_argument("--rating", type=float)
    sub.add_parser("records", help="13 시청 기록장 보기")
    p = sub.add_parser("recommend", help="01 취향 인터뷰 추천")
    p.add_argument("likes")
    a = ap.parse_args()
    out = {
        "find": lambda: service.find(a.question),
        "series": lambda: service.search_series(a.query, limit=20),
        "watch": lambda: service.where_to_watch(a.series_id),
        "review": lambda: service.review(a.series_id, a.seen, a.mode, a.question),
        "dict": lambda: service.dictionary(a.series_id, a.seen),
        "record": lambda: service.save_record(a.series_id, a.seen_ep, a.rating),
        "records": lambda: service.list_records(),
        "recommend": lambda: service.recommend(a.likes),
    }[a.cmd]()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
