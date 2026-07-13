#!/usr/bin/env python3
"""Re-derive title_reigns from the corpus with lineage-merged belts: index.html.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_title_reigns.py [--dry-run]

The shipped title_reigns grouped reign chains by the EXACT title_at_stake string,
so a belt the corpus spells three ways ("WWF Intercontinental Title", "WWE
Intercontinental Title", "Intercontinental Title") became three overlapping
chains, each dangling its own open "current" reign, and Triple H's IC reign ran
2002 -> 2009 because the WWE-spelled chain saw no matches while the belt was
tagged the short way. build_title_reigns now groups by a lineage key
(src.export_to_html._title_lineage_key), so this rebuilds the whole title_reigns
block and everything derived from it, then patches it into index.html.

Every title change is already in the corpus (the match shards); nothing is
scraped. There is no local wrestling.db, so the bundle is patched in place:
events are reconstructed from the shards exactly as apply_merge.load_events does.

These move together, or the roster, profiles and timeline disagree:
  * title_reigns                              -> Titles timeline pages; fill_belts / fill_titles input
  * wrestler_reigns_by_date                   -> roster belts, the "Champ" match badge, "as of your date" holder
  * wrestlers[*].title_wins / signature_title -> profile title counts
  * wrestlers[*].longest_match                -> refreshed from the current shards as a side effect.
    The duration backfill had left it stale for 58 wrestlers (all gains, no
    losses); refreshing it restores apply_merge's fidelity gate, which asserts
    the wrestler index rebuilds from the shards.

Idempotent: build_title_reigns reads the shards, not the current title_reigns, so
a second run reproduces the same bundle. --dry-run writes nothing.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import (  # noqa: E402
    build_title_reigns, build_wrestler_reigns_by_date, build_wrestlers_index, inject)
from src.ship_guard import atomic_write_text  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_merge import load_events  # noqa: E402  (reuse the exact shard -> events rebuild)

TAG_RE = r'<script id="wrestling-data" type="application/json">(.*?)</script>'

# Only these wrestler fields depend on title_reigns (or on shard durations the
# backfill refreshed). Everything else in the index must be byte-identical after
# the rebuild; the assertion below is the tripwire if that stops being true.
PATCH_FIELDS = ("title_wins", "signature_title", "longest_match")


def main() -> None:
    dry = "--dry-run" in sys.argv
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG_RE, html, re.S).group(1))
    old_w = bundle["wrestlers"]
    old_bn = bundle["wrestlers_by_name"]
    old_reigns = bundle["title_reigns"]

    events = load_events(bundle)

    # Re-derive reigns, now lineage-grouped. build_title_reigns asserts each chain
    # is contiguous and non-overlapping; build_wrestler_reigns_by_date asserts no
    # wrestler holds one title twice at once. A bad merge raises here, not on the
    # page.
    new_reigns = build_title_reigns(events)
    new_wrbd = build_wrestler_reigns_by_date(new_reigns)

    # Rebuild the wrestler index the way the shipped one was built. shipped_canon
    # is self-referential to the current bundle, so it reproduces the current
    # canonicalization exactly; only the reign-derived fields (and durations the
    # backfill refreshed) move. Same lambda apply_merge's fidelity gate uses.
    shipped_canon = lambda n: (old_w[old_bn[n]]["name"] if n in old_bn else n)  # noqa: E731
    new_w_obj, _ = build_wrestlers_index(events, canon=shipped_canon, title_reigns=new_reigns)
    new_w = json.loads(json.dumps(new_w_obj))  # tuples -> lists, matching the shipped JSON

    assert set(new_w) == set(old_w), "slug set changed; title_reigns must not affect slugging"
    unexpected = []
    for slug, nw in new_w.items():
        ow = old_w[slug]
        for k in set(ow) | set(nw):
            if k in PATCH_FIELDS:
                continue
            if ow.get(k) != nw.get(k):
                unexpected.append((slug, k))
    assert not unexpected, f"rebuild changed fields beyond {PATCH_FIELDS}: {unexpected[:10]}"

    # ---- report ----
    def opens(tr):
        return sum(1 for rs in tr.values() for r in rs if r["end"] is None)

    changed_wins = sum(1 for s in old_w if old_w[s].get("title_wins") != new_w[s].get("title_wins"))
    changed_sig = sum(1 for s in old_w if old_w[s].get("signature_title") != new_w[s].get("signature_title"))
    changed_long = sum(1 for s in old_w if old_w[s].get("longest_match") != new_w[s].get("longest_match"))
    renamed = sorted(set(new_reigns) - set(old_reigns))
    dropped = sorted(set(old_reigns) - set(new_reigns))

    print(f"title lineages: {len(old_reigns)} -> {len(new_reigns)}  "
          f"(dangling 'current' reigns {opens(old_reigns)} -> {opens(new_reigns)})")
    print(f"wrestlers changed: title_wins {changed_wins}, signature_title {changed_sig}, "
          f"longest_match refreshed {changed_long}")
    print(f"\ncanonical belt names now standing in for merged spellings ({len(renamed)} new keys):")
    for k in renamed:
        print(f"   + {k:36} {len(new_reigns[k]):3} reigns")
    print(f"absorbed spellings ({len(dropped)}):")
    for k in dropped:
        print(f"   - {k}")

    if dry:
        print("\n--dry-run: nothing written")
        return

    bundle["title_reigns"] = new_reigns
    bundle["wrestler_reigns_by_date"] = new_wrbd
    for slug, nw in new_w.items():
        w = bundle["wrestlers"][slug]
        for k in PATCH_FIELDS:
            w[k] = nw[k]

    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    print("\nrewrote index.html")


if __name__ == "__main__":
    main()
