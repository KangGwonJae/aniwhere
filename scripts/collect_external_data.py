import argparse

from aniwhere.ingest.external_collector import ExternalCollector, OUTPUT_PATH, REPORT_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect AniList + TMDB data for AniWhere")
    parser.add_argument("--count", type=int, default=20, help="number of titles to save")
    args = parser.parse_args()
    target = max(1, min(args.count, 40))
    items = ExternalCollector().collect(target=target, page_size=min(50, max(30, target + 30)))
    print(f"\nSaved {len(items)} titles to {OUTPUT_PATH}")
    print(f"Collection report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
