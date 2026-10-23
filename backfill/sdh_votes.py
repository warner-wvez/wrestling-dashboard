#!/usr/bin/env python3
"""SmackDown Hotel year pages as a vote on Raw 1993 on, SmackDown and Heat.

The site has no pages for Superstars, Wrestling Challenge, Prime Time or
SNME in these years (checked 2026-10-23: 404), so this lane is three slugs.
Pages cache in backfill/cache/sdh/, 2 s apart, browser User-Agent (the
existing fetch_year). Output: {"raw-1993": [episodes], ...}

    uv run --with requests --with beautifulsoup4 python backfill/sdh_votes.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.smackdownhotel import fetch_year, parse_year_html  # noqa: E402
from backfill.common import CACHE, OUT, record_status, write_json  # noqa: E402

SDH_CACHE = CACHE / "sdh"
PAGES = ([("raw", y) for y in range(1993, 2001)] + [("smackdown", 1999), ("smackdown", 2000)]
         + [("heat", y) for y in range(1998, 2001)])


def show_type_of(slug: str) -> str:
    return {"raw": "Raw", "smackdown": "SmackDown", "heat": "Heat"}[slug]


def main():
    SDH_CACHE.mkdir(parents=True, exist_ok=True)
    cards, failures = {}, []
    for show, year in PAGES:
        p = SDH_CACHE / f"{show}-{year}.html"
        try:
            if not p.exists():
                p.write_text(fetch_year(show, year), encoding="utf-8")
                time.sleep(2)
            eps = parse_year_html(p.read_text(encoding="utf-8"))
        except Exception as ex:
            failures.append(f"{show}-{year}: {ex}")
            continue
        cards[f"{show}-{year}"] = eps
        print(f"  {show}-{year}: {len(eps)} episodes")
    write_json(OUT / "sdh_cards.json", cards)
    record_status("sdh", not failures, f"{len(cards)} pages; failures: {', '.join(failures) or 'none'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
