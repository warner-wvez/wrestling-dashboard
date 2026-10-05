#!/usr/bin/env python3
"""WWE's own same-night results for a Raw or SmackDown, from the Wayback Machine.

The tiebreaker for review rows where our card, Cawthon and SmackDown Hotel
split. It is read by a person, never applied automatically: the pages are
prose, and a sample showed the other two sources agreeing against WWE on a DQ
finish (Triple H beat Randy Orton by DQ on Raw 2008-03-03; both called it a
no contest).

Two page shapes, by era:
  2004 to 2009  wwe.com/shows/<show>/archive/MMDDYYYY/ carries a "Matches"
                list ("Shawn Michaels def. John Cena (disqualification)").
  2011 on       wwe.com/shows/<show>/YYYY-MM-DD/results (by 2013
                wwe-raw-results-<id>, split over page-2, page-3 ...) is a
                prose recap of the night.

Pages are cached in wwe-cache/ (gitignored); the first capture after the air
date is used, so the text is what WWE published that week.

    uv run --with requests --with beautifulsoup4 lineup-check/wwe_recap.py Raw 2008-03-10 [name ...]
"""
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CACHE = HERE / "wwe-cache"
UA = {"User-Agent": "wrestling-dashboard lineup check (personal research)"}
CDX = "http://web.archive.org/cdx/search/cdx"


def _get(url, tries=3):
    for n in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 * (n + 1))
    return None


def _cached(key, fetch):
    f = CACHE / (re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    value = fetch()
    if value is not None:
        CACHE.mkdir(exist_ok=True)
        f.write_text(json.dumps(value), encoding="utf-8")
    return value


def captures(prefix, day, days_after=400):
    """[(timestamp, original url)] of 200 captures under a URL prefix, first
    capture per URL, taken from the air date to days_after later."""
    first = date.fromisoformat(day)
    start, end = first.strftime("%Y%m%d"), (first + timedelta(days=days_after)).strftime("%Y%m%d")

    def fetch():
        text = _get(f"{CDX}?url={prefix}&matchType=prefix&from={start}&to={end}"
                    "&output=json&filter=statuscode:200&collapse=urlkey&limit=400")
        if text is None:
            return None
        rows = json.loads(text) if text.strip() else []
        return [(r[1], r[2]) for r in rows[1:]]
    return _cached(f"cdx_{prefix}_{start}_{end}", fetch) or []


def page_text(timestamp, url):
    from bs4 import BeautifulSoup

    def fetch():
        html = _get(f"http://web.archive.org/web/{timestamp}id_/{url}")
        if html is None:
            return None
        return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()
    return _cached(f"page_{timestamp}_{url}", fetch)


def _show(show_type):
    return "raw" if show_type == "Raw" else "smackdown"


def archive_results(show_type, day):
    """2004 to 2009: the archive page's "Matches" list as one string, or None."""
    y, m, d = day.split("-")
    caps = captures(f"wwe.com/shows/{_show(show_type)}/archive/{m}{d}{y}", day)
    for ts, url in sorted(caps):
        text = page_text(ts, url)
        if text and " Matches " in text:
            block = text.split(" Matches ", 1)[1]
            return block[:900], f"http://web.archive.org/web/{ts}/{url}"
    return None


def results_pages(show_type, day):
    """2011 on: [(url, text)] for the day's results recap, every page of it
    ("/results" in 2011, "/wwe-raw-results-<id>/page-N" by 2013)."""
    caps = captures(f"wwe.com/shows/{_show(show_type)}/{day}/", day, days_after=3000)
    out = []
    for ts, url in sorted(caps, key=lambda c: c[1]):
        if re.search(r"/(?:wwe-\w+-)?results(?:-\d+)?(?:/page-\d+)?/?$", url):
            text = page_text(ts, url)
            if text:
                out.append((f"http://web.archive.org/web/{ts}/{url}", text))
    return out


def main():
    show_type, day, *names = sys.argv[1:]
    if day < "2010":
        got = archive_results(show_type, day)
        print(got[1] if got else "no archive page captured")
        print(got[0] if got else "")
        return
    keys = [n.split()[-1] for n in names]
    for url, text in results_pages(show_type, day):
        hits = [m.start() for k in keys for m in re.finditer(re.escape(k), text)]
        if hits:
            print("==", url)
            for h in sorted(hits)[:: max(1, len(hits) // 4)][:4]:
                print("  ..", text[max(0, h - 300):h + 500])


if __name__ == "__main__":
    main()
