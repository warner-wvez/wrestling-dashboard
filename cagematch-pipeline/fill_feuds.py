#!/usr/bin/env python3
"""Turn the parsed feuds into a roster-grounded rivalry sidecar: shards/feuds.json.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_feuds.py [--dry-run]

parse_feuds.py lifts the rows; this pulls a clean `X vs. Y` out of each German
title and keeps only the ones both of whose sides are real wrestlers. The event
page loads the list and shows, on each show, the feuds whose month window covers
it: "Storylines around this show".

## Reading the matchup out of German prose

A feud title is a German phrase with the matchup embedded: "Das Comeback des
Showstoppers: Michaels vs. Triple H". The names are language-neutral, so the
matchup is found by taking the text after the last ':' or dash, splitting on
'vs.' or the German 'gegen', and trimming stray prose off each side. The catch is
that prose can look like a matchup ("Legend vs. Icon"), so a candidate is only
accepted when every side resolves to the roster: a real wrestler by full name
(Rey Mysterio) or by the surname the title uses (Mysterio). 'Legend' and 'Icon'
are nobody, so that one is dropped rather than shown.

Only feuds whose window reaches into the 2001+ corpus are kept, since there is no
earlier show to hang them on. ~176 of the 300 corpus-era feuds survive; the rest
are titles with no matchup, team-nickname matchups (Hardys vs. E&C) whose sides
are not individual names, or phrases too German to parse. Better a clean 176 than
a padded list with `Cena entthront JBL` in it.

Idempotent: the sidecar is rebuilt from scratch each run.
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

from src.roster_aliases import normkey  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
FEUD_URL = "https://www.cagematch.net/?id=87&nr={}"
CORPUS_START = "2001-01"

# 'vs' / 'vs.' / German 'gegen' separate the sides; '&' / 'and' / 'und' join a tag.
_SIDES = re.compile(r"\s+(?:vs\.?|gegen)\s+", re.I)
_TAG = re.compile(r"\s*(?:&|and|und)\s+", re.I)


def build_roster(events_bundle):
    """A full-name set and a name-token set, so a side can be checked by its full
    name (Rey Mysterio) or by the surname a title uses (Mysterio). normkey drops
    spaces, so tokens come from the raw words, not from splitting the normkey."""
    full, tok = set(), set()
    for name in events_bundle["wrestlers_by_name"]:
        nk = normkey(name)
        if nk:
            full.add(nk)
        for word in re.split(r"\s+", name):
            wk = normkey(word)
            if len(wk) >= 4:
                tok.add(wk)
    return full, tok


def clean_side(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.split(r"[?!]", s)[-1].strip()             # keep only after a question/bang
    s = re.sub(r"\s+\d{4}$", "", s).strip()          # a trailing year is not a name
    words = s.split(" ")
    while words and not re.match(r"^[A-Z0-9]", words[0]):   # drop leading prose
        words.pop(0)
    return " ".join(words).strip(" .-")


def side_ok(s, full, tok) -> bool:
    if normkey(s) in full:
        return True
    for sub in _TAG.split(s):                          # a tag side is ok if a member is
        if normkey(sub) in full:
            return True
        words = re.split(r"\s+", sub.strip())
        if words and len(normkey(words[-1])) >= 4 and normkey(words[-1]) in tok:
            return True
    return False


def extract(title, full, tok):
    regions = [title.rsplit(sep, 1)[1] for sep in (":", " – ", " — ", " - ", "\x96")
               if sep in title]
    regions.append(title)
    for region in regions:
        parts = [clean_side(p) for p in _SIDES.split(region)]
        if len(parts) >= 2 and all(parts) and all(side_ok(p, full, tok) for p in parts):
            return " vs. ".join(parts)
    return None


def main() -> None:
    dry = "--dry-run" in sys.argv
    feuds = json.loads((OUT / "cm_feuds.json").read_text(encoding="utf-8"))
    bundle = json.loads(re.search(TAG, (ROOT / "index.html").read_text("utf-8"), re.S).group(1))
    full, tok = build_roster(bundle)

    out, how = [], Counter()
    for f in feuds:
        if f["end"] < CORPUS_START:
            how["pre-corpus (no show to attach)"] += 1
            continue
        matchup = extract(f["title"], full, tok)
        if not matchup:
            how["no roster-valid matchup"] += 1
            continue
        how["kept"] += 1
        out.append({
            "matchup": matchup,
            "start": f["start"],
            "end": f["end"],
            "rating": f["rating"],
            "votes": f["votes"],
            "url": FEUD_URL.format(f["cagematch_feud_nr"]),
        })

    out.sort(key=lambda x: (x["rating"] is not None, x["rating"] or 0), reverse=True)

    print("feuds:")
    for k, v in how.most_common():
        print(f"  {v:>5}  {k}")
    print(f"\nkept {len(out)} rivalries")
    print("highest-rated:")
    for x in out[:6]:
        print(f"  {x['rating']}  {x['start']}..{x['end']}  {x['matchup']}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    atomic_write_text(ROOT / "shards" / "feuds.json",
                      json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("\nwrote shards/feuds.json")


if __name__ == "__main__":
    main()
