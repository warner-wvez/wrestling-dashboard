#!/usr/bin/env python3
"""Map every title in the corpus to its belt image: shards/belts.json.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_belts.py [--dry-run]

belts/ holds one webp per belt (see belts/_pipeline/extract_belts.py). This joins
each title the corpus names, both the `title_reigns` lineage keys and every
`title_at_stake` value on a match, to a belt key, and writes a flat lookup the
frontend reads directly.

The join is by the words in the title, not an exact string, because the corpus
spells a belt a dozen ways ("WWF Hardcore Title", "WWE Hardcore Championship").
Two era splits matter: the big-gold World Heavyweight (2002-2013) and the white
strap revived in 2023 are different belts, and the corpus keeps them as different
titles, so they map to different images. A title with no belt image (AAA / TNA /
IWGP guest titles, and a couple of niche women's variants) maps to null and shows
no belt, which is correct, not a miss.

Idempotent: rebuilt from scratch each run. Prints every distinct title it could
not map, so a new belt is loud.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
BELTS_DIR = ROOT / "belts"


def norm(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(championship|title|the|of)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def belt_for(title: str):
    """Return a belt key for a title name, or None. Order is specific -> general."""
    n = norm(title)
    has = lambda *w: all(x in n for x in w)  # noqa: E731

    # Promotions whose belts are not in the HAR: a WWE-wrestler's guest defence
    # of an AAA / TNA / NJPW title should show no belt, not a WWE one. WCW and
    # ECW stay, since their belts were extracted.
    if re.search(r"\b(aaa|tna|iwgp|roh|njpw|impact|gcw|nwa)\b", n):
        return None

    # Distinctive single-name belts first.
    if has("million dollar"): return "million-dollar"
    if has("24 7") or "247" in n: return "24-7"
    if has("hardcore"): return "hardcore"
    if has("european"): return "european"
    if has("light heavyweight"): return "light-heavyweight"
    if has("ecw"): return "ecw"

    # NXT branch (before the generic belts, since NXT titles share those words).
    if has("nxt"):
        if has("cruiserweight"): return "nxt-cruiserweight"
        if has("north american") and (has("women") or has("womens")): return "nxt-womens-north-american"
        if has("north american"): return "nxt-north-american"
        if has("uk") and (has("women") or has("womens")): return "nxt-uk-womens"
        if has("uk") and has("tag"): return "uk-tag"
        if has("women") or has("womens"): return "nxt-womens"
        if has("uk"): return "united-kingdom"
        if has("tag"): return "tag-team"
        return "nxt"

    # Women's branch (before generic, same reason).
    if has("women") or has("womens") or has("divas"):
        if has("tag"): return "womens-tag"
        if has("intercontinental"): return "womens-intercontinental"
        if has("speed"): return "womens-speed"
        if has("evolve"): return "womens-evolve"
        if has("divas"): return "divas"
        return "womens"

    if has("cruiserweight"): return "cruiserweight"
    if has("speed"): return "speed"
    if has("evolve"): return "evolve"
    if has("intercontinental"): return "intercontinental"
    if has("united states") or re.search(r"\bus\b", n): return "united-states"
    if has("universal"): return "universal"
    if has("united kingdom") or re.search(r"\buk\b", n): return "united-kingdom"
    if has("tag"): return "tag-team"

    # World Heavyweight, four eras sharing the same words: WCW's big gold; the
    # 2002-2013 big gold; the 2001-2002 WWF/Undisputed and 2013-2016 unified
    # runs that lived under the WWE Championship's leather; and the white strap
    # revived in 2023. The bare name is ambiguous ACROSS eras ("World
    # Heavyweight Championship" is both big gold and the revival), so ambiguous
    # names get a date-split entry and the frontend resolves it per match or
    # reign date. Nothing sits near the cutoff: big gold retired 2013, the
    # 2013-2016 lineage died 2016, the revival began 2023.
    if has("world heavyweight"):
        if has("wcw"): return "world-heavyweight-classic"
        if has("wwf") and not has("undisputed"): return "wwe-championship"
        if has("undisputed") or has("wwe"):
            return {"cutoff": "2020-01-01", "before": "wwe-championship",
                    "after": "world-heavyweight-modern"}
        return {"cutoff": "2020-01-01", "before": "world-heavyweight-classic",
                "after": "world-heavyweight-modern"}
    if has("wcw") and has("world"): return "world-heavyweight-classic"

    # The main WWE/F Championship, under all its names.
    if has("wwe") or has("wwf") or has("undisputed") or has("heavyweight") or has("world"):
        return "wwe-championship"
    return None


def main() -> None:
    dry = "--dry-run" in sys.argv
    bundle = json.loads(re.search(TAG, (ROOT / "index.html").read_text("utf-8"), re.S).group(1))

    names = set(bundle["title_reigns"].keys())
    for p in sorted((ROOT / "shards").glob("matches-*.json")):
        for ms in json.loads(p.read_text(encoding="utf-8")).values():
            for m in ms:
                if m.get("title_at_stake"):
                    names.add(m["title_at_stake"])

    have = {p.stem for p in BELTS_DIR.glob("*.webp")}
    mapping, unmapped, missing_img = {}, [], set()
    for name in sorted(names):
        key = belt_for(name)
        if key is None:
            unmapped.append(name)
            continue
        # A date-split entry references two images; both must exist.
        keys = [key["before"], key["after"]] if isinstance(key, dict) else [key]
        absent = [k for k in keys if k not in have]
        if absent:
            missing_img.update(absent)
            continue
        mapping[name] = key

    by_key = Counter(k for v in mapping.values()
                     for k in ([v["before"], v["after"]] if isinstance(v, dict) else [v]))
    print(f"titles seen: {len(names)}   mapped: {len(mapping)}   unmapped: {len(unmapped)}")
    print("belt keys used:")
    for k, c in by_key.most_common():
        print(f"  {c:>4}  {k}")
    if missing_img:
        print("\nMAPPED TO A BELT KEY WITH NO IMAGE (run extract_belts.py):", sorted(missing_img))
    print("\nunmapped titles (no belt, shows nothing):")
    for name in unmapped:
        print(f"  {name}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    (ROOT / "shards" / "belts.json").write_text(
        json.dumps(mapping, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("\nwrote shards/belts.json")


if __name__ == "__main__":
    main()
