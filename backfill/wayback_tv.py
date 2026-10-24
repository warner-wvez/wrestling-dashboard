#!/usr/bin/env python3
"""WWF's own results write-ups, read back through the Wayback Machine.

From June 1999 to June 2000 wwf.com kept a TV results archive at
wwf.com/tv/archives/<year>/<month>/<day><letters>.html: one write-up per show
("Raw Results 6/21 part 3", "HEAT Results 6/20"), split over lettered parts,
posted a few days after the air date (the path date is the posting date, the
title carries the air date). The Wayback Machine holds 2,929 of those pages.
Nothing earlier survives: the first wwf.com capture is June 1997 and the
results section starts in June 1999.

This is the gold source for the review sheet in that window: WWF's own words
on who wrestled whom. Rows are settled by name presence, never by parsing the
prose as a result: a different_opponent row is ruled when exactly one of the
two names is on WWF's page for that show, a missing_match row when every
name on the other source's line is, an unpaired row when every name on ours
is, and a date_unconfirmed row when WWF posted a write-up for that show on
that date. Winner disputes get the sentences that name both people attached
as evidence and stay for a person.

    uv run --with requests python backfill/wayback_tv.py fetch      # polite, resumable, hours
    uv run --with requests --with beautifulsoup4 python backfill/wayback_tv.py check
"""
from __future__ import annotations

import csv
import html as htmllib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)
from backfill.common import CACHE, OUT, read_json, write_json  # noqa: E402

WB_CACHE = CACHE / "wayback"
TV_CACHE = WB_CACHE / "tv"
CDX_FILE = WB_CACHE / "cdx-tv-archives.txt"
CDX_URL = ("http://web.archive.org/cdx/search/cdx?url=wwf.com/tv/archives/*&from=1998&to=2002"
           "&fl=timestamp,original&filter=statuscode:200&collapse=urlkey&limit=6000")
USER_AGENT = "wrestling-dashboard-backfill/1.0 (+https://github.com/warner-wvez/wrestling-dashboard)"
PAUSE_S = 3.0

_TITLE_RE = re.compile(
    r"(RAW(?: IS WAR)?|Raw(?: is War)?|HEAT|Heat|Sunday Night Heat|SmackDown!?|Smackdown!?|Livewire|LiveWire|"
    r"Superstars|Shotgun|Jakked|Metal|SuperAstros|Super Astros)\s+Results?\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"
    r"(?:\s*[,:-]?\s*part\s*(\d+))?", re.I)
SHOW_TYPE = {"raw": "Raw", "raw is war": "Raw", "heat": "Heat", "sunday night heat": "Heat",
             "smackdown": "SmackDown", "smackdown!": "SmackDown", "superstars": "Superstars",
             "shotgun": "Shotgun", "jakked": "Jakked", "metal": "Jakked", "livewire": None,
             "superastros": None, "super astros": None}
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    t = htmllib.unescape(_TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def parse_page(page_html: str, path: str) -> dict | None:
    """{show_type, air_date, part, text} from one archived write-up, or None
    when the page is not a results write-up (an index, a listing)."""
    m = re.search(r"<title>(.*?)</title>", page_html, re.S | re.I)
    title = _text(m.group(1)) if m else ""
    t = _TITLE_RE.search(title)
    if not t:
        return None
    show = SHOW_TYPE.get(t.group(1).lower().replace("!", ""), None)
    if show is None:
        return None
    ym = re.search(r"/tv/archives/(\d{4})/", path)
    year = int(t.group(4)) if t.group(4) and len(t.group(4)) == 4 else int(ym.group(1)) if ym else None
    if year is None:
        return None
    mo, day = int(t.group(2)), int(t.group(3))
    if ym and mo == 12 and int(ym.group(1)) > year:
        year = int(ym.group(1))              # a December show written up in January
    body = page_html
    i = body.lower().find("archives")
    text = _text(body[i + 8:] if i >= 0 else body)
    text = re.split(r"\s(?:©|Copyright|All Rights Reserved)", text)[0]
    return {"show_type": show, "air_date": f"{year:04d}-{mo:02d}-{day:02d}",
            "part": int(t.group(5)) if t.group(5) else 1, "text": text, "title": title}


def cdx_rows() -> list[tuple[str, str]]:
    if not CDX_FILE.exists():
        import requests
        WB_CACHE.mkdir(parents=True, exist_ok=True)
        r = requests.get(CDX_URL, headers={"User-Agent": USER_AGENT}, timeout=180)
        r.raise_for_status()
        CDX_FILE.write_text(r.text, encoding="utf-8")
    rows = []
    for line in CDX_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lower().endswith(".html") and "<" not in line:
            rows.append((parts[0], parts[1]))
    return rows


def _cache_path(original: str) -> Path:
    rel = re.sub(r"^https?://(www\.)?wwf\.com(:80)?/tv/archives/", "", original)
    return TV_CACHE / rel


def fetch_all(limit: int | None = None) -> None:
    import requests
    TV_CACHE.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    rows = cdx_rows()
    todo = [(ts, u) for ts, u in rows if not _cache_path(u).exists()]
    print(f"{len(rows)} pages in the index, {len(todo)} to fetch", flush=True)
    for i, (ts, u) in enumerate(todo[:limit], 1):
        out = _cache_path(u)
        out.parent.mkdir(parents=True, exist_ok=True)
        for wait in (0, 5, 15, 45, 120):
            time.sleep(wait or PAUSE_S)
            try:
                r = s.get(f"http://web.archive.org/web/{ts}id_/{u}", timeout=60)
            except Exception as exc:
                print(f"  retry {u}: {exc!r}", flush=True)
                continue
            if r.status_code == 200 and "<html" in r.text.lower():
                out.write_text(r.text, encoding="utf-8")
                break
            if r.status_code == 404:
                out.write_text("", encoding="utf-8")
                break
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    print("done", flush=True)


def build_texts() -> dict:
    """{(show_type, air_date): {text, parts, urls}} from every cached page."""
    out = defaultdict(lambda: {"parts": {}, "urls": []})
    for p in TV_CACHE.rglob("*.html"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        if not raw:
            continue
        rec = parse_page(raw, "/tv/archives/" + str(p.relative_to(TV_CACHE)))
        if not rec:
            continue
        key = (rec["show_type"], rec["air_date"])
        out[key]["parts"][rec["part"]] = rec["text"]
        out[key]["urls"].append("http://web.archive.org/web/*/http://www.wwf.com/tv/archives/" + str(p.relative_to(TV_CACHE)))
    for key, v in out.items():
        v["text"] = " ".join(v["parts"][k] for k in sorted(v["parts"]))
    return {f"{k[0]}|{k[1]}": {"text": v["text"], "urls": v["urls"], "parts": len(v["parts"])} for k, v in out.items()}


def _names_in(text: str, names) -> set:
    low = text.lower()
    return {n for n in names if n and n.lower() in low}


def _line_names(line: str) -> list[str]:
    from cawthon_parse import parse_match_line
    m = parse_match_line(line) if line else None
    return (m["winners"] + m["losers"]) if m else []


def _our_names(ours: str) -> list[str]:
    """Names on our side of a review row: the raw match text with its prefix,
    escorts, result and time removed, split on the side and member joins."""
    s = re.sub(r"\(w/[^)]*\)|\(c\)|\(\d{1,2}:\d{1,2}\)|\\- .*$| by [A-Z][A-Za-z ]*$", " ", ours or "")
    s = re.sub(r"^[^:()]*:", "", s)          # the type or title prefix, once the time is gone
    s = re.sub(r"[^()&,:]+?\s*\(\s*", " ", s)  # "The Nasty Boys ( Brian Knobbs & ..." keeps the members only
    s = re.sub(r"\s*\)", " ", s)
    parts = re.split(r"\s+defeats?\s+|\s+vs\.\s+|\s+&\s+|\s+and\s+|,\s+", s)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def check(review_rows, texts) -> list[dict]:
    rulings = []
    for r in review_rows:
        key = f"{r['show_type']}|{r['air_date']}"
        rec = texts.get(key)
        if not rec:
            continue
        text, url = rec["text"], rec["urls"][0] if rec["urls"] else ""
        cls = r["class"]
        ours, theirs = _our_names(r.get("ours", "")), _line_names(r.get("cawthon", ""))
        ours_in, theirs_in = _names_in(text, ours), _names_in(text, theirs)
        ruling, evidence = None, ""
        if cls == "date_unconfirmed":
            ruling = "date_confirmed_wwf"
        elif cls == "different_opponent":
            only_ours = set(ours) - set(theirs)
            only_theirs = set(theirs) - set(ours)
            if only_ours and only_theirs:
                a, b = _names_in(text, only_ours), _names_in(text, only_theirs)
                if a and not b:
                    ruling = "keep"
                elif b and not a:
                    ruling = "fix_lineup"
        elif cls == "missing_match" and theirs:
            if len(theirs_in) == len(set(theirs)):
                ruling = "add_match"
        elif cls == "unpaired" and ours:
            if len(ours_in) == len(set(ours)):
                ruling = "aired"
        elif cls == "result":
            sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if ours and any(n.lower() in s.lower() for n in ours[:2])]
            evidence = " ".join(sents)[:600]
        if ruling or evidence:
            rulings.append({"event_key": r["event_key"], "match_order": r.get("match_order", ""), "class": cls,
                            "ruling": ruling or "evidence", "source_url": url, "evidence": evidence})
    return rulings


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["fetch"]:
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
        fetch_all(limit)
        return 0
    texts = build_texts()
    write_json(OUT / "wwf_tv_texts.json", texts)
    with (OUT / "review.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rulings = check(rows, texts)
    with (OUT / "rulings_wayback.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_key", "match_order", "class", "ruling", "source_url", "evidence"])
        w.writeheader()
        w.writerows(rulings)
    by = defaultdict(int)
    for r in rulings:
        by[(r["class"], r["ruling"])] += 1
    print(f"{len(texts)} WWF write-ups; {len(rulings)} rows touched:")
    for k in sorted(by):
        print(f"  {k[0]:20s} {k[1]:20s} {by[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
