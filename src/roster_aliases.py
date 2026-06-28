#!/usr/bin/env python3
"""WWE roster alias resolution: collapse a wrestler's ring-name changes and
spelling variants into one canonical identity for the roster index.

Sources, in priority order:
  1. The SmackDown Hotel WWE roster page. Each card's profile slug preserves the
     wrestler's earlier name while the displayed/title name is current, so
     `<a href="/wrestlers/walter" title="Gunther">` encodes WALTER -> Gunther.
     This auto-captures every current-roster rename without hand-curation.
  2. A small curated map for notable renames of wrestlers no longer on the live
     roster (not derivable from the page).
  3. Automatic normalized-key grouping for pure spelling variants (caps, a
     leading "The", apostrophes/diacritics): "IYO SKY"/"Iyo Sky",
     "Big Show"/"The Big Show". Canonical display = the roster name when any
     variant is on the roster, else the most frequently used form in the data.

Usage:
    from src.roster_aliases import build_canon_map
    canon = build_canon_map(name_counts)        # {raw_name: canonical_name}
"""
import html as _html
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.export_to_html import slugify  # noqa: E402  (one slug source of truth)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
ROSTER_URL = "https://www.thesmackdownhotel.com/roster/wwe/"

# Curated renames the live roster page cannot supply: wrestlers who changed
# names while in WWE but are off the current roster, where BOTH names appear in
# the 2001-2026 data. Keep the WWE-era name as canonical for a WWE dashboard.
CURATED = {
    "Big E Langston": "Big E",
    "Antonio Cesaro": "Cesaro",
    'Andrade "Cien" Almas': "Andrade",
    "Andrade Almas": "Andrade",
    "Andrade El Idolo": "Andrade",
    # Fold a protected wrestler's nickname / real name back into the ring name
    # (the live roster lists these as the current name, see PROTECTED below).
    "Nattie": "Natalya",
    "TJ Wilson": "Tyson Kidd",
}

# Names that must keep their established ring name and never be aliased away.
# The live roster page sometimes lists a wrestler under a real name (Triple H ->
# "Paul Levesque", Tyson Kidd -> "TJ Wilson"), a temporary masked gimmick (Tyler
# Bate / Pete Dunne / Marcel Barthel -> the rotating "...Americano" luchador), or
# a nickname (Natalya -> "Nattie"); those would mis-rename well-known wrestlers.
PROTECTED = {
    "Triple H", "Tyson Kidd", "Natalya", "Tyler Bate", "Pete Dunne",
    "Marcel Barthel", "Will Hobbs",
}


def normkey(name):
    """Spelling-insensitive identity key: lowercase, drop a leading 'the',
    strip everything but a-z0-9. 'The Big Show'/'Big Show' -> 'bigshow'."""
    n = (name or "").lower().strip()
    n = re.sub(r"^the\s+", "", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def scrape_roster(html=None):
    """Return [(profile_slug, current_display_name)] from the WWE roster page."""
    if html is None:
        req = urllib.request.Request(ROSTER_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            html = r.read().decode("utf-8", "replace")
    pairs = []
    for m in re.finditer(r'href="/wrestlers/([^"#?]+)"[^>]*?\stitle="([^"]+)"', html):
        slug, name = m.group(1).strip("/"), _html.unescape(m.group(2)).strip()
        if slug and name:
            pairs.append((slug, name))
    return pairs


def build_canon_map(name_counts, roster_pairs=None, curated=None):
    """Map every raw participant name to its canonical wrestler name.

    name_counts: {raw_name: how_many_matches} (used to pick the dominant display
    for spelling-variant groups). roster_pairs: override the live scrape (tests).
    """
    curated = CURATED if curated is None else curated
    if roster_pairs is None:
        try:
            roster_pairs = scrape_roster()
        except Exception as exc:  # offline / page moved: fall back to variants+curated
            print(f"  roster scrape failed ({exc}); aliasing from curated + variants only")
            roster_pairs = []

    canonical_by_key = {}
    for slug, name in roster_pairs:               # name-key and slug-key -> current name
        canonical_by_key[normkey(name)] = name
        canonical_by_key.setdefault(normkey(slug), name)
    for old, new in curated.items():
        canonical_by_key[normkey(old)] = new
        canonical_by_key.setdefault(normkey(new), new)
    protected_by_key = {normkey(p): p for p in PROTECTED}   # highest priority

    groups = defaultdict(Counter)                 # spelling-variant fallback
    for n, c in name_counts.items():
        groups[normkey(n)][n] += c

    out = {}
    for n in name_counts:
        k = normkey(n)
        out[n] = (protected_by_key.get(k) or canonical_by_key.get(k)
                  or groups[k].most_common(1)[0][0])
    return out


def main():
    import json
    pairs = scrape_roster()
    renames = [(s, n) for s, n in pairs if normkey(s) != normkey(n)]
    print(f"roster cards: {len(pairs)} | encoded renames (slug != name): {len(renames)}")
    for s, n in renames[:40]:
        print(f"   {s:28s} -> {n}")


if __name__ == "__main__":
    main()
