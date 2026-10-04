from __future__ import annotations

import argparse
import json
import os
import urllib.parse

from aniwhere.ingest.catalog import ROOT
from aniwhere.ingest.external_collector import TMDB_URL, request_json
from aniwhere.settings import load_env


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect real TMDB episode data without exposing the API token."
    )
    parser.add_argument("--tv-id", type=int, required=True, help="TMDB TV series ID")
    parser.add_argument("--season", type=int, required=True, help="season number")
    parser.add_argument("--language", default="ko-KR", help="TMDB language, default: ko-KR")
    parser.add_argument("--json", action="store_true", help="print the raw API JSON")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    token = os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit(".env에 TMDB_READ_ACCESS_TOKEN을 설정해주세요.")

    query = urllib.parse.urlencode({"language": args.language})
    url = f"{TMDB_URL}/tv/{args.tv_id}/season/{args.season}?{query}"
    data = request_json(url, headers={"Authorization": f"Bearer {token}"})

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    episodes = data.get("episodes", [])
    filled = sum(bool(item.get("overview", "").strip()) for item in episodes)
    print(f"작품: {data.get('name') or '(제목 없음)'}")
    print(f"시즌: {data.get('season_number', args.season)}")
    print(f"회차: {len(episodes)}개 / 줄거리 있음: {filled}개 / 없음: {len(episodes) - filled}개")
    print("=" * 78)
    for episode in episodes:
        number = episode.get("episode_number")
        title = episode.get("name") or "(제목 없음)"
        air_date = episode.get("air_date") or "날짜 없음"
        overview = episode.get("overview", "").strip() or "[줄거리 없음]"
        still = episode.get("still_path")
        print(f"\nS{args.season:02}E{number:02} · {title} · {air_date}")
        print(overview)
        if still:
            print(f"스틸: https://image.tmdb.org/t/p/w500{still}")


if __name__ == "__main__":
    main()
