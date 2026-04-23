"""
Step 1a: Cagematch event discovery via the WWE promotion events index.

Binary-searches to the first page in the target year range, then walks
forward until it leaves the range. Filters to Raw, SmackDown, and known
PPV/PLE title stems. Ignores house shows, dev brands (NXT), and B-shows.

Output schema matches v1 so src/cagematch_scraper.py needs no changes.

Run:
  .venv/bin/python src/discover.py --year 2004
  .venv/bin/python src/discover.py --year 2004 --dry-run
  .venv/bin/python src/discover.py --year-from 2004 --year-to 2005
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

INDEX_URL = "https://www.cagematch.net/?id=8&nr=1&page=4&s={offset}"
EVENT_URL = "https://www.cagematch.net/?id=1&nr={nr}"
PAGE_SIZE = 100
TOTAL_ROWS_CEILING = 28000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_DELAY_SEC = 2.0
RETRY_BACKOFFS_SEC = [1, 2, 4]

_EVENT_NR_RE = re.compile(r"[?&]id=1&nr=(\d+)")

# PPV / PLE title stems. Anything not starting with one of these (and not
# Raw or SmackDown) is silently skipped. If a PPV gets missed, add it here.
PPV_STEMS = (
    "WWF Royal Rumble", "WWE Royal Rumble",
    "WWF No Way Out", "WWE No Way Out",
    "WWF WrestleMania", "WWE WrestleMania",
    "WWF Backlash", "WWE Backlash",
    "WWF Judgment Day", "WWE Judgment Day",
    "WWF Insurrextion", "WWE Insurrextion",
    "WWF King Of The Ring", "WWE King Of The Ring",
    "WWF Bad Blood", "WWE Bad Blood",
    "WWF Vengeance", "WWE Vengeance",
    "WWF Fully Loaded", "WWE Fully Loaded",
    "WWE Great American Bash", "WWE The Great American Bash",
    "WWF SummerSlam", "WWE SummerSlam",
    "WWF Unforgiven", "WWE Unforgiven",
    "WWF No Mercy", "WWE No Mercy",
    "WWE Taboo Tuesday",
    "WWF Rebellion", "WWE Rebellion",
    "WWF Survivor Series", "WWE Survivor Series",
    "WWE Cyber Sunday",
    "WWE Armageddon", "WWF Armageddon",
    "WWE New Year's Revolution",
    "WWE The Bash",
    "WWE Breaking Point",
    "WWE Hell In A Cell",
    "WWE Bragging Rights",
    "WWE TLC",
    "WWE Elimination Chamber",
    "WWE Extreme Rules",
    "WWE Over The Limit",
    "WWE Capitol Punishment",
    "WWE Money In The Bank",
    "WWE Night Of Champions",
    "WWE Fastlane",
    "WWE Payback",
    "WWE Battleground",
    "WWE Clash Of Champions",
    "WWE Roadblock",
    "WWE Crown Jewel",
    "WWE Super Show-Down",
    "WWE Super ShowDown",
    "WWE Stomping Grounds",
    "WWE Day 1",
    "WWF In Your House",
    "WWE ECW One Night Stand",
    "WWE December To Dismember",
    "ECW One Night Stand",
    "ECW December To Dismember",
    "WWE NXT Arrival",
    "WWE NXT ArRIVAL",
    "WWE NXT TakeOver",
    "WWE NXT Takeover",
    "WWE Tribute To The Troops",
)


def fetch(url):
    """GET with retries, 2s backoff ladder, iso-8859-15 decode."""
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            resp.encoding = "iso-8859-15"
            return resp.text
        except requests.RequestException as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(RETRY_BACKOFFS_SEC[attempt])
    raise RuntimeError(f"fetch failed for {url}: {last_err}")


def parse_cagematch_date(value):
    """DD.MM.YYYY to date. None if unparseable."""
    if not value:
        return None
    parts = value.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        d, m, y = (int(p) for p in parts)
        return date(y, m, d)
    except ValueError:
        return None


def parse_index_page(html):
    """Extract event rows from one index page. Returns list of dicts."""
    soup = BeautifulSoup(html, "html.parser")
    rows_out = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        date_raw = tds[1].get_text(strip=True)
        parsed_date = parse_cagematch_date(date_raw)
        if parsed_date is None:
            continue
        title_cell = tds[3]
        link = title_cell.find("a")
        if not link or not link.get("href"):
            continue
        m = _EVENT_NR_RE.search(link["href"])
        if not m:
            continue
        rows_out.append({
            "nr": int(m.group(1)),
            "date": parsed_date,
            "date_raw": date_raw,
            "title": link.get_text(strip=True),
            "location": tds[4].get_text(strip=True) if len(tds) > 4 else "",
        })
    return rows_out


def first_row_date(offset):
    """Fetch one page and return the date of its first data row, or None."""
    html = fetch(INDEX_URL.format(offset=offset))
    rows = parse_index_page(html)
    return rows[0]["date"] if rows else None


def binary_search_offset_for_year(target_year):
    """
    Find the lowest page offset whose first row year is <= target_year.
    The list is reverse-chronological: higher offset = older events.
    """
    lo, hi = 0, TOTAL_ROWS_CEILING
    best = 0
    fetches = 0
    print(f"Binary search for first page at year <= {target_year} ...", flush=True)
    while lo <= hi:
        mid = ((lo + hi) // 2 // PAGE_SIZE) * PAGE_SIZE
        d = first_row_date(mid)
        fetches += 1
        label = d.isoformat() if d else "empty"
        print(f"  probe s={mid:>5}: first row date = {label}", flush=True)
        time.sleep(REQUEST_DELAY_SEC)
        if d is None:
            hi = mid - PAGE_SIZE
            continue
        if d.year > target_year:
            lo = mid + PAGE_SIZE
        else:
            best = mid
            hi = mid - PAGE_SIZE
    print(f"  -> starting offset s={best} ({fetches} probe fetches)", flush=True)
    return best


def classify(row, year_from, year_to):
    """keep / too_new / too_old / skip_silent."""
    title = row["title"]
    d = row["date"]

    if d.year > year_to:
        return "too_new", None
    if d.year < year_from:
        return "too_old", None

    # Drop house shows and other non-broadcast variants explicitly. Weekly
    # TV episodes have "#NNN" in the title; house shows and live events
    # don't, which is the real signal we want.
    title_lower = title.lower()
    if any(marker in title_lower for marker in ("house show", "live event", "live show")):
        return "skip_silent", None
    # Weekly TV titles always carry a # number. Dark matches / taped
    # variants without a number aren't what we want.
    has_episode_number = "#" in title

    is_raw = (
        title.startswith("WWE RAW") or title.startswith("WWF RAW")
        or title.startswith("WWE Monday Night RAW") or title.startswith("WWF Monday Night RAW")
    ) and has_episode_number
    is_smackdown = (
        title.startswith("WWE SmackDown") or title.startswith("WWF SmackDown")
        or title.startswith("WWE Friday Night SmackDown") or title.startswith("WWE Thursday Night SmackDown")
        or title.startswith("WWF Friday Night SmackDown") or title.startswith("WWF Thursday Night SmackDown")
    ) and has_episode_number
    is_ppv = any(title.startswith(stem) for stem in PPV_STEMS)

    if not (is_raw or is_smackdown or is_ppv):
        return "skip_silent", None

    show_type = "Raw" if is_raw else "SmackDown" if is_smackdown else "PPV-Candidate"
    kept = {
        "nr": row["nr"],
        "url": EVENT_URL.format(nr=row["nr"]),
        "title": title,
        "date": d.isoformat(),
        "type": show_type,
        "promotion": "World Wrestling Entertainment",
        "location": row["location"],
    }
    return "keep", kept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Shorthand for --year-from N --year-to N")
    parser.add_argument("--year-from", type=int, default=2001)
    parser.add_argument("--year-to", type=int, default=2003)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pages", type=int, default=80)
    args = parser.parse_args()

    if args.year is not None:
        year_from = year_to = args.year
    else:
        year_from, year_to = args.year_from, args.year_to

    if year_from > year_to:
        print(f"ERROR: year-from ({year_from}) > year-to ({year_to})", file=sys.stderr)
        sys.exit(2)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Target range: {year_from} to {year_to} inclusive.", flush=True)

    start_offset = binary_search_offset_for_year(year_to)
    # Back off a few pages before starting the walk. The binary search lands
    # on the first page whose first row falls at or before year_to, but
    # slightly earlier offsets (newer events) often still contain rows in
    # the target range that we'd otherwise skip. Three pages = 300 rows of
    # headroom, which comfortably covers any single-year target.
    start_offset = max(0, start_offset - 300)

    kept = []
    rejected = []
    pages_fetched = 0
    rows_seen = 0
    offset = start_offset

    print(f"Walking forward from s={start_offset} ...", flush=True)
    while pages_fetched < args.max_pages:
        url = INDEX_URL.format(offset=offset)
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"ERROR fetching {url}: {exc}", file=sys.stderr)
            sys.exit(1)

        rows = parse_index_page(html)
        pages_fetched += 1
        if not rows:
            print(f"  page s={offset}: no rows, stopping.", flush=True)
            break
        rows_seen += len(rows)

        page_kept = 0
        page_skipped = 0
        page_too_new = 0
        page_too_old = 0
        for row in rows:
            status, rec = classify(row, year_from, year_to)
            if status == "keep":
                kept.append(rec)
                page_kept += 1
            elif status == "too_new":
                page_too_new += 1
            elif status == "too_old":
                page_too_old += 1
            else:
                page_skipped += 1
                rejected.append({"nr": row.get("nr"), "title": row.get("title"), "date": row.get("date").isoformat() if row.get("date") else None})

        print(
            f"  page s={offset:>5}: rows={len(rows):>3}, "
            f"kept={page_kept:>2}, skipped={page_skipped:>3}, "
            f"too_new={page_too_new:>2}, too_old={page_too_old:>2}",
            flush=True,
        )

        if page_too_old == len(rows):
            break

        offset += PAGE_SIZE
        time.sleep(REQUEST_DELAY_SEC)

    kept.sort(key=lambda r: (r["date"], r["nr"]))

    print(flush=True)
    print(f"Pages fetched: {pages_fetched}", flush=True)
    print(f"Rows inspected: {rows_seen}", flush=True)
    print(f"Kept: {len(kept)}", flush=True)

    if args.dry_run:
        print("--dry-run: not writing. First 10 kept:", flush=True)
        for r in kept[:10]:
            print(f"  {r['date']}  nr={r['nr']:>6}  {r['type']:<14} {r['title']}", flush=True)
        return

    (DATA_DIR / "events_to_scrape.json").write_text(
        json.dumps(kept, indent=2, ensure_ascii=False)
    )
    (DATA_DIR / "events_rejected.json").write_text(
        json.dumps(rejected, indent=2, ensure_ascii=False)
    )
    print(f"Wrote {DATA_DIR / 'events_to_scrape.json'}", flush=True)
    print(f"Wrote {DATA_DIR / 'events_rejected.json'}", flush=True)

    years_span = year_to - year_from + 1
    expected_min = 90 * years_span
    expected_max = 180 * years_span
    if len(kept) < expected_min or len(kept) > expected_max:
        print(
            f"WARNING: kept={len(kept)} is outside the expected "
            f"{expected_min}-{expected_max} band for {years_span} year(s).",
            file=sys.stderr, flush=True,
        )


if __name__ == "__main__":
    main()
