#!/usr/bin/env python3
"""Copy an existing headshot onto the slug the roster actually renders.

    python3 cagematch-pipeline/rekey_orphan_assets.py [--dry-run]

`roster-img/_pipeline/alias-copies.tsv` copies headshots *between alias slugs*
(`bradshaw` <- `john-bradshaw-layfield`) but never onto the canonical slug the
wrestler index renders. So A-Train's face sits at `albert.webp` while the roster
asks for `a-train.webp` and shows an initials placeholder. Six wrestlers are in
that state, and none of them are split identities, so apply_merge's re-key pass
never considered them.

The rule: for every live wrestler with no headshot, look at every name that
routes to them in `wrestlers_by_name` and copy the first image that exists.
Names route to exactly one slug, so a name can never pull down another
wrestler's face. Copies, never moves, so the donor stays put and re-running is
a no-op.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.export_to_html import slugify  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402


def main():
    dry = "--dry-run" in sys.argv
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    b = json.loads(re.search(r'<script id="wrestling-data" type="application/json">(.*?)</script>',
                             html, re.S).group(1))
    wrestlers, by_name = b["wrestlers"], b["wrestlers_by_name"]
    roster = {f.stem for f in (ROOT / "roster-img").glob("*.webp")}

    aliases = defaultdict(list)
    for name, slug in by_name.items():
        aliases[slug].append(name)

    plan = []
    for slug in wrestlers:
        if slug in roster:
            continue
        for src in (slugify(n) for n in aliases.get(slug, [])):
            if src != slug and src in roster:
                plan.append((slug, src))
                break

    copied = 0
    profiles_path = ROOT / "shards" / "profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    added = 0
    for slug, src in plan:
        s, t = ROOT / "roster-img" / f"{src}.webp", ROOT / "roster-img" / f"{slug}.webp"
        if not dry:
            shutil.copy2(s, t)
        copied += 1
        for d in ("era-img", "gimmick-img"):
            for f in sorted((ROOT / d).glob(f"{src}-*.webp")):
                dst = ROOT / d / f"{slug}{f.stem[len(src):]}.webp"
                if not dst.exists():
                    if not dry:
                        shutil.copy2(f, dst)
                    copied += 1
        if src in profiles and slug not in profiles:
            profiles[slug] = profiles[src]
            added += 1
        print(f"  {slug:24} <- {src}.webp")

    if added and not dry:
        atomic_write_text(profiles_path, json.dumps(profiles, ensure_ascii=False,
                                                    separators=(",", ":"), sort_keys=True) + "\n")
    print(f"\nwrestlers rescued: {len(plan)}   files copied: {copied}   profiles re-keyed: {added}"
          + ("   (--dry-run: nothing written)" if dry else ""))


if __name__ == "__main__":
    main()
