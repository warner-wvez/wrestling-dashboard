#!/usr/bin/env python3
"""Extract the era-accurate show logos and stamp one onto every event.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/extract_logos.py [HAR] [--dry-run]

The HAR is a capture of Cagematch's WWE promotion page. Its 85 logo requests all
carry their bytes inline (base64 in `content.text`), so nothing is fetched here.

Two ways to pick a logo, and only one of them is guesswork:

**Read it off the event.** Every results row in the scrape names the logo
Cagematch rendered beside it, and parse_raw kept that in `cm_events.json`. With
3041 of 3046 events now carrying a `cagematch_nr`, the logo is a lookup, not an
inference. A 1998 Raw gets RAW IS WAR, a 2003 Raw gets the WWE RAW of that year,
a PPV gets the promotion logo of its era, and an NXT TakeOver gets the TakeOver
logo. 30 distinct logos cover the corpus.

**Fall back to the date range**, for the 5 events that never joined. The
filenames encode it: `1_WWF RAW is WAR_19970310-20010910.gif` is valid from
1997-03-10 to 2001-09-10, and a missing end means "still current". Ranges are
read from the logos the corpus actually uses, so the fallback can only ever pick
something a real event of that show type wore.

Writes `logo-img/<slug>.gif` plus a manifest, and adds `event.logo` to the
bundle. Idempotent.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import inject  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
LOGO_DIR = ROOT / "logo-img"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
DEFAULT_HAR = Path.home() / "Downloads" / "xage.har"

# Which logo families a dashboard show_type may wear. Only used by the date-range
# fallback; the primary path reads the logo Cagematch actually rendered.
FAMILIES = {
    "Raw": ("wwf-raw-is-war", "wwf-raw", "wwe-raw", "wwe-monday-night-raw"),
    "SmackDown": ("wwf-smackdown", "wwe-smackdown", "wwe-smackdown-live",
                  "wwe-friday-night-smackdown", "wwe-thursday-night-smackdown"),
    "PPV": ("promotion",),
}


def parse_logo_name(name: str):
    """'1_WWF RAW is WAR_19970310-20010910.gif' -> ('WWF RAW is WAR', '19970310', '20010910')

    '1.gif' is the promotion's current logo: no show, no range."""
    stem = name[:-4]
    if not stem.startswith("1"):
        raise ValueError(name)
    stem = stem[1:]
    if not stem:
        return "", None, None
    stem = stem[1:]                                     # drop the separating '_'
    m = re.match(r"^(.*?)_?(\d{4}(?:\d{4})?)?-(\d{4}(?:\d{4})?)?$", stem)
    if m and (m.group(2) or m.group(3)):
        return m.group(1).rstrip("_"), m.group(2), m.group(3)
    return stem, None, None


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def bound(v, lo):
    """'2016' -> 20160101 (start) or 20161231 (end). None -> open."""
    if not v:
        return None
    return int(v) if len(v) == 8 else int(v + ("0101" if lo else "1231"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    har_path = Path(args[0]) if args else DEFAULT_HAR
    dry = "--dry-run" in sys.argv
    if not har_path.exists():
        sys.exit(f"HAR not found: {har_path}")

    har = json.loads(har_path.read_text(encoding="utf-8"))
    blobs = {}
    for e in har["log"]["entries"]:
        url = e["request"]["url"]
        if "/img/ligen/normal/" not in url:
            continue
        name = urllib.parse.unquote(url.rsplit("/", 1)[1])
        c = e["response"].get("content", {})
        if c.get("encoding") == "base64" and c.get("text"):
            blobs[name] = base64.b64decode(c["text"])
    print(f"logos in HAR (bytes inline): {len(blobs)}")

    cm = json.loads((OUT / "cm_events.json").read_text(encoding="utf-8"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG, html, re.S).group(1))
    events = bundle["events"]

    logo_of = {}                                        # dashboard event id -> filename
    for eid, e in events.items():
        nr = e.get("cagematch_nr")
        if nr and str(nr) in cm and cm[str(nr)].get("logo"):
            logo_of[eid] = cm[str(nr)]["logo"]

    needed = sorted(set(logo_of.values()))
    missing = [n for n in needed if n not in blobs]
    if missing:
        sys.exit(f"HAR is missing {len(missing)} logo(s) the corpus needs: {missing}")

    manifest, slug_of = {}, {}
    for name in needed:
        show, start, end = parse_logo_name(name)
        base = slugify(show) if show else "promotion"
        slug = f"{base}-{start}" if start else base
        slug_of[name] = slug
        manifest[slug] = {"file": f"{slug}.gif", "show": show or "WWE (promotion)",
                          "valid_from": start, "valid_to": end, "source": name}

    # Date-range fallback for events that never joined Cagematch.
    families = defaultdict(list)
    for slug, m in manifest.items():
        fam = re.sub(r"-\d{4,8}$", "", slug)
        families[fam].append((bound(m["valid_from"], True) or 0,
                              bound(m["valid_to"], False) or 99999999, slug))
    for v in families.values():
        v.sort()

    def fallback(show_type, air_date):
        day = int(air_date.replace("-", ""))
        for fam in FAMILIES.get(show_type, ()):
            for lo, hi, slug in families.get(fam, ()):
                if lo <= day <= hi:
                    return slug
        return None

    stamped, how = 0, Counter()
    for eid, e in events.items():
        if eid in logo_of:
            slug = slug_of[logo_of[eid]]
            how["from-cagematch"] += 1
        else:
            slug = fallback(e["show_type"], e["air_date"])
            how["date-range fallback" if slug else "no logo"] += 1
        if slug and e.get("logo") != slug:
            e["logo"] = slug
            stamped += 1

    print(f"distinct logos used: {len(needed)}")
    for k, v in how.most_common():
        print(f"  {v:>5}  {k}")
    print(f"events newly stamped: {stamped}")
    print("\nfallback assignments:")
    for eid, e in events.items():
        if eid not in logo_of:
            print(f"  {e['air_date']} {e['show_type']:10} -> {e.get('logo')}")

    if dry:
        print("\n--dry-run: nothing written")
        return

    LOGO_DIR.mkdir(exist_ok=True)
    for name in needed:
        (LOGO_DIR / f"{slug_of[name]}.gif").write_bytes(blobs[name])
    (LOGO_DIR / "logos.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    total = sum((LOGO_DIR / f"{slug_of[n]}.gif").stat().st_size for n in needed)
    print(f"\nwrote {len(needed)} gifs to logo-img/ ({total/1024:.0f} KB) + logos.json; rewrote index.html")


if __name__ == "__main__":
    main()
