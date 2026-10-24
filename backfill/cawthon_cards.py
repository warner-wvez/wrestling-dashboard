#!/usr/bin/env python3
"""Parse the cached Cawthon pages into backfill/out/cawthon_cards.json.

{slug: [{air_date, tape_date, city, venue, label?, matches: [...]}]} for every
show page, and {"wwf-results-YYYY": {date: {title, heat, ppv}}} for the arena
results pages. Each match is parse_match_line's dict plus finish_of's two keys.

    uv run --with requests --with beautifulsoup4 python backfill/cawthon_cards.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "lineup-check")):
    sys.path.insert(0, p)
from cawthon_parse import (finish_of, parse_compilation_page, parse_match_line,  # noqa: E402
                           parse_ppv_page, parse_show_page, parse_special_page)
from backfill.cawthon_fetch import CACHE, SLUGS  # noqa: E402
from backfill.common import OUT, record_status, write_json  # noqa: E402

# Three page shapes: the show page ("M/D/YY; City; Venue" headers, Raw,
# SmackDown, Superstars, Challenge, Heat, Shotgun, Sunday Night Slam), the
# special page (bold "WWF @ City - Venue - Month D, YYYY" headers, SNME and The
# Main Event), and the compilation page (an italic air date only, Prime Time,
# All-American, Mania).
SPECIAL = {"wwf-saturday-nights-main-event", "wwf-the-main-event"}
COMPILATION_PREFIXES = ("wwf-prime-time-wrestling-", "wwf-all-american-wrestling-", "wwf-mania")


def _matches(lines):
    out = []
    for ln in lines:
        m = parse_match_line(ln)
        if m:
            m.update(finish_of(ln))
            out.append(m)
    return out


def main():
    cards, missing, counts = {}, [], {}
    for slug in SLUGS:
        p = CACHE / f"{slug}.html"
        if not p.exists():
            missing.append(slug)
            continue
        html = p.read_text(encoding="utf-8")
        if slug.startswith("wwf-results-"):
            cards[slug] = parse_ppv_page(html)
            counts[slug] = len(cards[slug])
            continue
        if slug in SPECIAL:
            shows = parse_special_page(html)
        elif slug.startswith(COMPILATION_PREFIXES):
            shows = parse_compilation_page(html)
        else:
            shows = parse_show_page(html)
        for s in shows:
            s["matches"] = _matches(s.pop("lines"))
        cards[slug] = shows
        counts[slug] = len(shows)
    write_json(OUT / "cawthon_cards.json", cards)
    for slug in SLUGS:
        print(f"  {slug:40s} {counts.get(slug, 'MISSING')}")
    ok = not missing
    record_status("cawthon", ok, f"{len(cards)} pages; missing: {', '.join(missing) or 'none'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
