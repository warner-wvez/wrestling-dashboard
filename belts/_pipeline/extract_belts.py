#!/usr/bin/env python3
"""Extract championship belt cutouts from a saved wwe.com HAR into belts/.

    uv run --with pillow python belts/_pipeline/extract_belts.py [path/to/www.wwe.com.har]

wwe.com serves each title's belt as a transparent PNG on its championship pages;
a HAR capture of those pages embeds them as base64. This pulls the curated set,
renames each to a stable belt key the rest of the pipeline joins on, and resizes
to a small transparent webp (the originals are ~960x540, far larger than the
48-120px the UI ever draws).

Only the belts the corpus actually needs are taken; the HAR also holds wrestler
profile shots and duplicate crops, which are skipped. A belt whose source file is
missing from the HAR is reported, not silently dropped.

Default HAR path is ~/Downloads/www.wwe.com.har. Output is belts/<key>.webp,
committed; the HAR itself is not in the repo.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from PIL import Image
import io

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "belts"
DEFAULT_HAR = Path.home() / "Downloads" / "www.wwe.com.har"
WIDTH = 240   # display is 48-120px; 240 covers retina with headroom

# belt key -> the source file basename (sans the --<hash> wwe.com appends).
#
# TRAP: wwe.com file basenames LIE, and the same basename holds different belts
# on different pages. "WWE_Heavyweight" is their Belt_Retired render of BIG
# GOLD (shipping it as the WWE Championship put big gold on every Undisputed
# champion, found 2026-07-18), and "WWE_World_Championship" is the 2023 World
# Heavyweight belt in one capture but the WOMEN'S UNITED STATES belt in a
# titlehistory capture. Never map by filename alone: open the page's HTML in
# the HAR and pair each /titlehistory/<slug> link with its image, then eyeball
# the decoded image before committing. Do NOT re-run this wholesale against a
# new HAR without re-verifying every source below against that HAR's pages.
SOURCE = {
    # Current Undisputed WWE Championship render; wwe.com's own og:image for
    # /titlehistory/wwe-championship (belts.har capture, 2026-07-18).
    "wwe-championship": "TITLE_04192023gd_0062_Fin",
    "world-heavyweight-classic": "WCW_Heavyweight",       # the big gold belt, WCW + WWE 2002-2013
    "world-heavyweight-modern": "WWE_World_Championship",  # the 2023 revival (www.wwe.com.har capture ONLY, see TRAP)
    "universal": "Universal_Championship_SD",
    "intercontinental": "_Intercontinental_Title_Belts_1920x1080_updated",
    "united-states": "WWE_US_Championship",
    "tag-team": "WWE_World_Tag_Team_Championship",
    "divas": "Divas_Championship",
    "womens": "Womens_Champion",
    "womens-tag": "Womens_Tag_Team_Championship1",
    "womens-intercontinental": "WWE_Womens_IC_Champion",
    "womens-speed": "WWE_Womens_Speed_Championship",
    "womens-evolve": "WWE_Womens_Evolve_Champion",
    "cruiserweight": "WWE_Cruiserweight_Championship",
    "hardcore": "WWE_Hardcore_Championship",
    "european": "WWE_European_Championship",
    "ecw": "ECW_World_Heavyweight_Championship",
    "light-heavyweight": "WWE_Light_Heavyweight_Championship",
    "million-dollar": "Million_Dollar_Title_06152021cg_004_Crop_%281%29",
    "24-7": "20190522_24_7_Championship",
    "speed": "SpeedTitle",
    "evolve": "Evolve_Champion",
    "united-kingdom": "WWE_UK_Championship_Belt",
    "uk-tag": "UK_Tag_Championship_Belt",
    "nxt": "NXT_Champion",
    "nxt-womens": "NXT_Womens_Champion",
    "nxt-north-american": "NXT_North_American_Championship",
    "nxt-womens-north-american": "NXTWomansNorthAmericanTitle_06042024ak_0246_cropped",
    "nxt-cruiserweight": "NXT_Cruiserweight_Championship",
    "nxt-uk-womens": "NXTUK_womens_Championship",
}


def basename_of(url: str) -> str:
    fn = url.split("/")[-1].split("?")[0]
    fn = fn.rsplit("--", 1)[0]                 # drop wwe.com's --<hash> suffix
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if fn.lower().endswith(ext):
            fn = fn[: -len(ext)]
    return fn


def main() -> None:
    har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HAR
    if not har_path.exists():
        sys.exit(f"HAR not found: {har_path}")
    har = json.loads(har_path.read_text())

    # basename -> raw image bytes (first occurrence wins)
    images = {}
    for e in har["log"]["entries"]:
        ct = e["response"].get("content", {})
        if not ct.get("mimeType", "").startswith("image") or ct.get("encoding") != "base64":
            continue
        if not ct.get("text"):
            continue
        base = basename_of(e["request"]["url"])
        if base not in images:
            try:
                images[base] = base64.b64decode(ct["text"])
            except (ValueError, TypeError):
                pass

    OUT.mkdir(parents=True, exist_ok=True)
    made, missing = 0, []
    for key, src in SOURCE.items():
        data = images.get(src)
        if data is None:
            missing.append((key, src))
            continue
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = im.size
        im = im.resize((WIDTH, round(h * WIDTH / w)), Image.LANCZOS)
        im.save(OUT / f"{key}.webp", "WEBP", quality=88, method=6)
        made += 1

    print(f"wrote {made} belt webps to {OUT}")
    if missing:
        print("MISSING from HAR (belt key -> expected source basename):")
        for key, src in missing:
            print(f"  {key}  <-  {src}")


if __name__ == "__main__":
    main()
