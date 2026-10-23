#!/usr/bin/env python3
"""Fandom's per-episode results as the third vote on Raw and SmackDown.

Fandom 403s plain requests (Cloudflare) and firecrawl's default scrape
passes at 1 credit a page, so every page goes through `firecrawl scrape
--format rawHtml`, one at a time, saved to backfill/cache/fandom/<slug>.html
the moment it arrives (a re-run skips cached slugs). Slugs are built from the
air dates Cawthon gives: "January_11,_1993_Monday_Night_RAW_results" and
"August_26,_1999_Smackdown_results". The run prints how many credits it will
spend and stops unless --yes is given. A missing page is a miss, not a
failure: that episode just has no Fandom vote.

    uv run --with requests --with beautifulsoup4 python backfill/fandom_votes.py [--yes] [--limit N]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.fandom_scraper import parse_episode_page  # noqa: E402
from backfill.common import CACHE, OUT, read_json, record_status, write_json  # noqa: E402

FANDOM_CACHE = CACHE / "fandom"
BASE = "https://prowrestling.fandom.com/wiki/"
SHOW_WORD = {"Raw": "Monday_Night_RAW", "SmackDown": "Smackdown"}
PAGE_SLUGS = {"Raw": [f"wwf-raw-{y}" if y != 1994 else "wwf-raw-1994-results" for y in range(1993, 2001)],
              "SmackDown": ["wwf-smackdown-1999", "wwf-smackdown-2000"]}


def fandom_slug(show_type: str, air_date: str) -> str:
    d = date.fromisoformat(air_date)
    return f"{d.strftime('%B')}_{d.day},_{d.year}_{SHOW_WORD[show_type]}_results"


def fandom_url(slug: str) -> str:
    return BASE + slug


_TITLE_RE = re.compile(r"\b(?:to retain|to win|for) the ((?:WWF|WWE|World) [^()]*?Championship)\b")
_DARK_RE = re.compile(r"^\s*Dark Match\s*:\s*", re.I)


def parse_page(html: str) -> dict:
    """The 2001 to 2003 Fandom parser, plus two things its SmackDown pages
    never carried: the title named in prose ("to retain the WWF
    Intercontinental Championship") and the "Dark Match :" prefix."""
    page = parse_episode_page(html)
    for m in page["matches"]:
        raw = m.get("raw_description") or ""
        if not m.get("title_at_stake"):
            t = _TITLE_RE.search(raw)
            if t:
                m["title_at_stake"] = t.group(1).strip()
        if not m.get("match_type") and _DARK_RE.match(raw):
            m["match_type"] = "Dark"
    return {"air_date": page.get("air_date"), "tape_date": page.get("tape_date"),
            "matches": page["matches"]}


def _scrape(slug: str) -> Path | None:
    out = FANDOM_CACHE / f"{slug}.html"
    if out.exists():
        return out
    tmp = FANDOM_CACHE / f"{slug}.tmp"
    r = subprocess.run(["firecrawl", "scrape", fandom_url(slug), "--format", "rawHtml", "-o", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode or not tmp.exists():
        return None
    text = tmp.read_text(encoding="utf-8")
    try:
        html = json.loads(text).get("rawHtml") or ""
    except json.JSONDecodeError:
        html = text
    tmp.unlink()
    if "mw-parser-output" not in html or "noarticletext" in html:
        return None
    out.write_text(html, encoding="utf-8")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    yes, limit = "--yes" in argv, None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    FANDOM_CACHE.mkdir(parents=True, exist_ok=True)
    cawthon = read_json(OUT / "cawthon_cards.json")
    wanted = []
    for show_type, slugs in PAGE_SLUGS.items():
        for slug in slugs:
            for ep in cawthon.get(slug, []):
                wanted.append((show_type, ep["air_date"]))
    wanted = sorted(set(wanted))
    todo = [(st, d) for st, d in wanted if not (FANDOM_CACHE / f"{fandom_slug(st, d)}.html").exists()]
    print(f"{len(wanted)} episodes, {len(todo)} to scrape = up to {len(todo)} firecrawl credits")
    if todo and not yes:
        print("pass --yes to spend them")
        return 2
    cards, misses = {}, []
    for i, (st, d) in enumerate(wanted, 1):
        if limit is not None and i > limit:
            break
        slug = fandom_slug(st, d)
        p = _scrape(slug)
        if p is None:
            misses.append(f"{st}\t{d}\t{slug}")
            continue
        try:
            cards[f"{st}|{d}"] = parse_page(p.read_text(encoding="utf-8"))
        except Exception as ex:
            misses.append(f"{st}\t{d}\t{slug}\tparse: {ex}")
        if i % 25 == 0:
            print(f"  {i}/{len(wanted)}", flush=True)
    write_json(OUT / "fandom_cards.json", cards)
    (OUT / "fandom_misses.tsv").write_text("".join(m + "\n" for m in misses), encoding="utf-8")
    print(f"{len(cards)} pages parsed, {len(misses)} misses -> {OUT / 'fandom_misses.tsv'}")
    record_status("fandom", True, f"{len(cards)} votes, {len(misses)} misses")
    return 0


if __name__ == "__main__":
    sys.exit(main())
