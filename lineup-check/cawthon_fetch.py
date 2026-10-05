#!/usr/bin/env python3
"""Download Graham Cawthon's 2001 to 2013 results pages into cache/.

26 show year pages (Raw and SmackDown) and 13 results year pages (the PPVs).
One request at a time with a pause, resumable: a page already in cache/ is not
fetched again.

    uv run --with requests lineup-check/cawthon_fetch.py
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
BASE = "https://thehistoryofwwe.com"
USER_AGENT = ("wrestling-dashboard-lineup-check/1.0 "
              "(+https://github.com/warner-wvez/wrestling-dashboard)")
YEARS = range(2001, 2014)
PAUSE_S = 3.0


def slugs():
    """Every page slug, in fetch order. WWF until the May 2002 rename."""
    out = []
    for y in YEARS:
        org = "wwf" if y == 2001 else "wwe"
        out += [f"{org}-raw-{y}", f"{org}-smackdown-{y}", f"{org}-results-{y}"]
    return out


def main():
    import requests
    CACHE.mkdir(exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    todo = [x for x in slugs() if not (CACHE / f"{x}.html").exists()]
    for i, slug in enumerate(todo, 1):
        for attempt, wait in enumerate((0, 10, 30, 90)):
            time.sleep(wait or PAUSE_S)
            try:
                r = s.get(f"{BASE}/{slug}/", timeout=60)
            except Exception as exc:
                print(f"  retry {slug}: {exc!r}", flush=True)
                continue
            if r.status_code == 200:
                (CACHE / f"{slug}.html").write_text(r.text, encoding="utf-8")
                break
            if r.status_code == 404:
                break
        print(f"[{i}/{len(todo)}] {slug} {r.status_code}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
