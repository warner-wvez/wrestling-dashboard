#!/usr/bin/env python3
"""Fetch the Cagematch event page for every event that joined to a Cagematch nr
but was not sourced from Cagematch, so backfill_event_pages.py can read them.

    uv run --with requests python cagematch-pipeline/fetch_event_pages.py [--limit N]

## Why a fetch step of its own

The 858 targets are the SmackDownHotel, Fandom and Wikipedia events that
fill_locations.py stamped with a `cagematch_nr`. Their Cagematch event pages were
never scraped, so match durations, attendance, TV data and commentary all sit at
zero (see backfill_event_pages.py for the table). fill_locations proved the join;
this pulls the pages that join points at.

Cagematch answers a plain `requests.get` for HTML with a 307 redirect loop, so
the fetch goes through Firecrawl, exactly as the bulk `.firecrawl/cagematch-raw`
scrape did. One event page per request. Firecrawl serves the English rendering
even without the `/en/` prefix, so `TV station/network` comes back `UPN`, not the
German `PPV Sender` the untargeted bulk scrape left on the PPV rows.

## Resumability

Each page is saved to `.firecrawl/cm-events/{nr}.html` (gitignored) the moment it
arrives, and a second run skips every nr already on disk. A page is only written
if it actually looks like a Cagematch event page (`InformationBoxTable` present),
so a soft error page cannot poison the cache and get skipped forever.

The API key is read from `$FIRECRAWL_API_KEY` or the firecrawl-cli credentials
file; nothing is hardcoded.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".firecrawl" / "cm-events"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
API = "https://api.firecrawl.dev/v1/scrape"
EVENT_URL = "https://www.cagematch.net/?id=1&nr={}"
CREDS = Path.home() / "Library" / "Application Support" / "firecrawl-cli" / "credentials.json"

MAX_WORKERS = 6
RETRIES = 4
BACKOFFS = [2, 5, 10, 20]
# Every real Cagematch event page carries this container; a soft error / redirect
# landing page does not. Refusing to cache anything without it keeps the resumable
# skip honest.
CONTENT_MARKER = "InformationBoxTable"


def api_key() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY")
    if key:
        return key.strip()
    if CREDS.exists():
        try:
            k = json.loads(CREDS.read_text()).get("apiKey")
            if k:
                return k.strip()
        except (json.JSONDecodeError, OSError):
            pass
    sys.exit("no Firecrawl API key: set $FIRECRAWL_API_KEY or install firecrawl-cli")


def targets() -> list[int]:
    """Every event with a cagematch_nr that was not itself sourced from Cagematch."""
    bundle = json.loads(re.search(TAG, (ROOT / "index.html").read_text("utf-8"), re.S).group(1))
    nrs = {int(e["cagematch_nr"]) for e in bundle["events"].values()
           if e.get("primary_source") != "cagematch" and e.get("cagematch_nr")}
    return sorted(nrs)


def fetch_one(nr: int, key: str) -> tuple[int, str]:
    """Return (nr, status). status is 'saved', 'skip', or 'fail: ...'."""
    path = CACHE / f"{nr}.html"
    if path.exists():
        return nr, "skip"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"url": EVENT_URL.format(nr), "formats": ["rawHtml"]}
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.post(API, headers=headers, json=body, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"http {r.status_code}"
                time.sleep(BACKOFFS[attempt])
                continue
            r.raise_for_status()
            data = r.json()
            html = (data.get("data") or {}).get("rawHtml") or ""
            if not data.get("success") or CONTENT_MARKER not in html:
                last = "no event content"
                time.sleep(BACKOFFS[attempt])
                continue
            tmp = path.with_suffix(".html.tmp")
            tmp.write_text(html, encoding="utf-8")
            os.replace(tmp, path)
            return nr, "saved"
        except requests.RequestException as exc:
            last = repr(exc)
            time.sleep(BACKOFFS[attempt])
    return nr, f"fail: {last}"


def main() -> None:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    CACHE.mkdir(parents=True, exist_ok=True)
    key = api_key()
    all_nrs = targets()
    todo = [nr for nr in all_nrs if not (CACHE / f"{nr}.html").exists()]
    if limit is not None:
        todo = todo[:limit]

    print(f"targets {len(all_nrs)}  already cached {len(all_nrs) - len(todo) if limit is None else '?'}  "
          f"to fetch {len(todo)}", flush=True)
    if not todo:
        print("nothing to fetch")
        return

    saved = failed = 0
    fails = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(fetch_one, nr, key): nr for nr in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            nr, status = fut.result()
            if status == "saved":
                saved += 1
            elif status.startswith("fail"):
                failed += 1
                fails.append((nr, status))
            if i % 25 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] saved={saved} failed={failed}", flush=True)

    print(f"\ndone: saved {saved}, failed {failed}")
    if fails:
        print("failures (re-run to retry, they were not cached):")
        for nr, status in fails[:20]:
            print(f"  nr={nr}  {status}")
        if len(fails) > 20:
            print(f"  ... and {len(fails) - 20} more")


if __name__ == "__main__":
    main()
