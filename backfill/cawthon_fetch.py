#!/usr/bin/env python3
"""Download Graham Cawthon's 1985 to 2000 pages into backfill/cache/cawthon/.

One request at a time, 3 s apart, resumable (a page already cached is not
fetched again), the lineup-check User-Agent. The slug list is every show
family in the spec plus the arena results year pages (PPVs and house shows).

    uv run --with requests python backfill/cawthon_fetch.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))
from cawthon_fetch import BASE, PAUSE_S, USER_AGENT  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache" / "cawthon"

SLUGS = (
    [f"wwf-raw-{y}" if y != 1994 else "wwf-raw-1994-results" for y in range(1993, 2001)]
    + ["wwf-smackdown-1999", "wwf-smackdown-2000"]
    + [f"wwf-superstars-{y}" for y in range(1986, 1998)]
    + [f"wwf-wrestling-challenge-{y}" for y in range(1986, 1996)]
    + [f"wwf-prime-time-wrestling-{y}" for y in range(1985, 1993)]
    + [f"wwf-all-american-wrestling-{y}" for y in range(1985, 1995)]
    + ["wwf-sunday-night-heat-1998", "wwf-sunday-night-heat-1999"]
    + [f"wwf-shotgun-{y}" for y in range(1997, 2000)]
    + ["wwf-mania", "wwf-sunday-night-slam", "wwf-saturday-nights-main-event", "wwf-the-main-event"]
    + [f"wwf-results-{y}" for y in range(1985, 2001)]
)


def main():
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    todo = [x for x in SLUGS if not (CACHE / f"{x}.html").exists()]
    missing = []
    for i, slug in enumerate(todo, 1):
        code = None
        for wait in (0, 10, 30, 90):
            time.sleep(wait or PAUSE_S)
            try:
                r = s.get(f"{BASE}/{slug}/", timeout=60)
            except Exception as exc:
                print(f"  retry {slug}: {exc!r}", flush=True)
                continue
            code = r.status_code
            if code == 200:
                (CACHE / f"{slug}.html").write_text(r.text, encoding="utf-8")
                break
            if code == 404:
                missing.append(slug)
                break
        print(f"[{i}/{len(todo)}] {slug} {code}", flush=True)
    if missing:
        print("404 (left out, name them in the run report): " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
