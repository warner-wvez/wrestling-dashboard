#!/usr/bin/env python3
"""Translate the last German strings the bulk Cagematch scrape left in the bundle.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fix_german_leftovers.py [--dry-run]

The untargeted scrape was fetched without the `/en/` prefix, and fill_locations
cleaned the country names it left behind, but a few user-entered German strings
slipped through in fields the `/en/` view does not translate either:

    tv_network  "PPV Sender"            -> "Pay-Per-View"      (109 events)
                "lokale TV Sender (USA)" -> "Local TV (USA)"    (2)
    city        "Bagdad"                -> "Baghdad"            (3)
                "Mailand"               -> "Milan"              (2)

These are labels, not real network or place spellings ("PPV Sender" is German for
"PPV channel"), so the fix is a straight rename, not a re-scrape. Every change is
a value the frontend prints in a show header, so leaving them German is the one
visibly-wrong thing on those pages.

Idempotent: a second run finds nothing left to translate. Prints any German-
looking value it does NOT know how to translate, so a new straggler is loud
rather than silently shipped.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import inject  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'

TV_NETWORK = {
    "PPV Sender": "Pay-Per-View",
    "lokale TV Sender (USA)": "Local TV (USA)",
}
CITY = {
    "Bagdad": "Baghdad",
    "Mailand": "Milan",
}
# A last-line tripwire: German tokens that should never survive in these fields.
# If one shows up unmapped, the run flags it instead of shipping it.
SUSPECT = re.compile(r"\b(Sender|lokale|Bagdad|Mailand|Irak|Italien|Frankreich|"
                     r"Saudi-Arabien|Vereinigte|Deutschland|Mexiko|Spanien)\b", re.I)


def main() -> None:
    dry = "--dry-run" in sys.argv
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG, html, re.S).group(1))
    events = bundle["events"]

    fixed = Counter()
    for e in events.values():
        if e.get("tv_network") in TV_NETWORK:
            e["tv_network"] = TV_NETWORK[e["tv_network"]]
            fixed["tv_network"] += 1
        if e.get("city") in CITY:
            e["city"] = CITY[e["city"]]
            fixed["city"] += 1

    # Tripwire scan across the fields that carry free text.
    stragglers = Counter()
    for e in events.values():
        for f in ("tv_network", "city", "state_province", "country", "venue"):
            v = e.get(f)
            if v and SUSPECT.search(v):
                stragglers[f"{f}={v!r}"] += 1

    print("translated:")
    for k, v in fixed.most_common():
        print(f"  {v:>4}  {k}")
    if stragglers:
        print("\nUNTRANSLATED German-looking values still present (add a mapping):")
        for k, v in stragglers.most_common():
            print(f"  {v:>4}  {k}")
    else:
        print("\nno German-looking stragglers remain")

    if dry:
        print("\n--dry-run: nothing written")
        return
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    print("\nrewrote index.html")


if __name__ == "__main__":
    main()
