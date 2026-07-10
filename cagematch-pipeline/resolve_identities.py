#!/usr/bin/env python3
"""Decide one roster identity per Cagematch worker, and name it.

Reads the join tables from parse_raw.py plus the shipped bundle, and writes a
canon map the export builder can consume. Nothing is applied here; see
apply_merge.py.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/resolve_identities.py

## The problem

The roster renders JBL and John Bradshaw Layfield as two wrestlers, 102 matches
and 152 matches, because `CURATED` in src/roster_aliases.py keys him as
`John "Bradshaw" Layfield` and `normkey` strips quoted nicknames, yielding
`johnlayfield`. The corpus stores him unquoted, yielding `johnbradshawlayfield`.
The keys never meet, so the merge silently no-ops. Four other curated keys are
dead the same way. Keying on the Cagematch worker nr instead of a name string
removes the whole failure class.

## Resolving which worker a name belongs to

Not by name. 95 ring names are claimed by two workers: `Kane` is Glenn Jacobs
2719 times and Luke Gallows once (the 2006 impostor angle), `Butch` is a
Bushwhacker and also Pete Dunne. A participation is resolved by looking up the
name inside the Cagematch event it happened at, where only one Kane wrestled.
Each dashboard wrestler then votes across its whole career; the majority worker
wins. Kane resolves to 379 and Luke Gallows to 2049, both unanimously.

## Naming the merged identity

Warner's rule: the name the wrestler is best known by in the industry, never a
real name, and never a one-off storyline alias. Match cards keep the era-accurate
alias; only the roster aggregates under the canonical name.

Two counting windows disagree on 26 of the 133 splits. Full WWE history favours
pre-corpus gimmicks the dashboard never shows (Mankind, Diesel). The corpus
window favours whatever name happened to be current, and its counts are often
near-ties that carry no signal (Robert Roode 65 vs Bobby Roode 62). So: trust
the corpus window only when it is decisive, otherwise fall back to full history.
That reproduces every call by hand, except two threshold artifacts, which are
listed in OVERRIDES.

The SmackDownHotel roster is deliberately NOT consulted. It records the name a
wrestler carries *today*, which for Pete Dunne is "Rayo Americano" and for
Humberto Carrillo is "Berto". Current gimmick is not best-known name.

Only the 133 split workers are renamed. Every other wrestler keeps the display
name the shipped bundle already gives it, so this cannot disturb merges that
already work (WALTER -> Gunther).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import slugify  # noqa: E402  (one slug source of truth)
from src.roster_aliases import PROTECTED, normkey  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"

# Corpus counts win only when the dominant name is at least this many times the
# runner-up. Below it the counts are a coin flip and full history decides.
MARGIN = 2.0

# Human calls, keyed by Cagematch worker nr so a ring-name spelling can never
# silently unhook them the way the quoted CURATED keys did.
#
#   193  corpus prefers 'John Bradshaw Layfield' 151-101 (1.5x, under MARGIN),
#        so full history decides and picks Bradshaw 730-397. Confirmed.
#   7828 'Tonga Loa' leads 11-6, a ratio of 1.83, just under MARGIN, so the rule
#        would fall through to his old name Camacho. Threshold artifact.
#   994  'Scotty Goldman' leads 5-2, a ratio of 2.5, just over MARGIN, so the
#        rule would keep it over the far better known Colt Cabana. Same artifact,
#        other direction.
OVERRIDES = {
    "7828": "Tonga Loa",
    "994": "Colt Cabana",
}


def load_bundle():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="wrestling-data" type="application/json">(.*?)</script>',
                  html, re.S)
    return json.loads(m.group(1))


def load_events_with_matches(bundle):
    events = {eid: dict(ev, matches=[]) for eid, ev in bundle["events"].items()}
    for f in sorted((ROOT / "shards").glob("matches-*.json")):
        for eid, ms in json.loads(f.read_text(encoding="utf-8")).items():
            if eid in events:
                events[eid]["matches"] = ms
    return events


def main():
    cm_events = json.loads((OUT / "cm_events.json").read_text(encoding="utf-8"))
    cm_ew = json.loads((OUT / "cm_event_workers.json").read_text(encoding="utf-8"))
    cm_w = json.loads((OUT / "cm_workers.json").read_text(encoding="utf-8"))

    bundle = load_bundle()
    events = load_events_with_matches(bundle)
    W, by_name = bundle["wrestlers"], bundle["wrestlers_by_name"]

    by_ds = defaultdict(list)
    for e in cm_events.values():
        by_ds[(e["air_date"], e["show_type"])].append(e)

    def cm_for(ev):
        nr = ev.get("cagematch_nr")
        if nr and str(nr) in cm_events:
            return str(nr)
        c = by_ds.get((ev["air_date"], ev["show_type"]), [])
        return str(c[0]["cagematch_nr"]) if len(c) == 1 else None

    # --- resolve each participation to a worker, inside its own event ---------
    corpus_names: dict[str, Counter] = defaultdict(Counter)   # worker -> name counts
    slug_votes: dict[str, Counter] = defaultdict(Counter)     # slug -> worker votes
    joined = 0
    for ev in events.values():
        cnr = cm_for(ev)
        if not cnr:
            continue
        joined += 1
        # Match a dashboard participant against the night's roster by exact name
        # first, then by normkey. The two corpora spell 329 participations
        # differently ('Finn Balor'/'Finn Bálor', 'T-BAR'/'T-Bar', 'Big Show'/
        # 'The Big Show', 'Seth "Freakin" Rollins'), and an exact-only lookup
        # drops them, leaving orphan fragments like a 2-match 'dijak' beside a
        # 35-match 'T-BAR'. normkey collides for only 3 participations corpus-wide.
        night, night_key = defaultdict(list), defaultdict(list)
        for w, nm in cm_ew.get(cnr, {}).items():
            night[nm].append(w)
            night_key[normkey(nm)].append(w)
        for m in ev["matches"]:
            for t in m["teams"]:
                for p in t["participants"]:
                    slug = by_name.get(p)
                    if not slug:
                        continue
                    cands = night.get(p) or night_key.get(normkey(p), [])
                    if not cands:
                        continue
                    # A true tie means both wrestled that night under the same
                    # name (Vengeance 2006, Kane vs the impostor). Give it to
                    # whoever owns the name across history; the career-wide
                    # majority vote below absorbs the one bad ballot.
                    w = cands[0] if len(cands) == 1 else max(
                        cands, key=lambda x: cm_w[x].get(p, 0))
                    corpus_names[w][p] += 1
                    slug_votes[slug][w] += 1

    resolved = {s: c.most_common(1)[0][0] for s, c in slug_votes.items()}
    worker_slugs = defaultdict(set)
    for s, w in resolved.items():
        worker_slugs[w].add(s)
    splits = {w: ss for w, ss in worker_slugs.items() if len(ss) > 1}

    # --- name the merged identity --------------------------------------------
    protected_by_key = {normkey(p): p for p in PROTECTED}
    assert not (set(OVERRIDES) & {w for w in splits
                                  if any(normkey(n) in protected_by_key
                                         for n in corpus_names[w])}), \
        "an OVERRIDE collides with PROTECTED; resolve by hand"

    def decide(w):
        if w in OVERRIDES:
            return OVERRIDES[w], "override"
        for n in corpus_names[w]:
            if normkey(n) in protected_by_key:
                return protected_by_key[normkey(n)], "protected"
        nc = corpus_names[w].most_common()
        if len(nc) == 1:
            return nc[0][0], "corpus-only"
        if nc[0][1] >= MARGIN * nc[1][1]:
            return nc[0][0], "corpus-decisive"
        return max(cm_w[w], key=cm_w[w].get), "full-history"

    # --- emit the canon map ---------------------------------------------------
    # Only names owned by a split worker are remapped. Everything else keeps the
    # display name the shipped bundle already computed, so working merges stay.
    #
    # `canon` in build_wrestlers_index is a global name -> name function: it has
    # no way to say "this name meant a different person that night". So a name
    # worn by more than one wrestler must NOT be remapped, or the majority owner
    # swallows everyone else's matches. 'El Grande Americano' is a mask worn by
    # both Chad Gable and Ludwig Kaiser; 'Doink' by four different workers.
    # Those names keep the behaviour they have today: their own roster entry.
    owners = defaultdict(set)
    for w, c in corpus_names.items():
        for n in c:
            owners[n].add(w)
    shared = {n for n, ws in owners.items() if len(ws) > 1}

    canon_map, identity, why = {}, {}, Counter()
    skipped_shared = []
    for w, members in splits.items():
        name, reason = decide(w)
        why[reason] += 1
        for n in corpus_names[w]:
            if n in shared:
                if n != name:
                    skipped_shared.append((n, name))
                continue
            canon_map[n] = name
        identity[slugify(name)] = {
            "cagematch_id": int(w),
            "name": name,
            "reason": reason,
            "merged_from": sorted(members),
            "aliases": sorted(n for n in corpus_names[w] if n not in shared),
            "total_matches": sum(W[s]["total_matches"] for s in members),
        }

    # --- asset plan -----------------------------------------------------------
    roster = {f.stem for f in (ROOT / "roster-img").glob("*.webp")}
    sdh_src = {}
    for line in (ROOT / "roster-img/_pipeline/sdh-fetched.tsv").read_text().splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        local, src = line.split("\t")[:2]
        sdh_src.setdefault(slugify(src), local)

    rekey, fetch = [], []
    for cslug, rec in identity.items():
        if cslug in roster:
            continue
        w = str(rec["cagematch_id"])
        # Donor names must be names ONLY this worker used in this corpus.
        # Steve Lombardi wrestled once as "MVP"; without this guard the Brooklyn
        # Brawler inherits MVP's headshot.
        safe = {slugify(n) for n in corpus_names[w] if n not in shared}
        safe |= {sdh_src[s] for s in list(safe) if s in sdh_src}
        hit = sorted(s for s in safe if s in roster)
        (rekey if hit else fetch).append(
            (rec["total_matches"], cslug, hit[0] if hit else None, rec["name"]))

    OUT.mkdir(exist_ok=True)
    (OUT / "canon_map.json").write_text(
        json.dumps(canon_map, ensure_ascii=False, indent=0, sort_keys=True) + "\n", "utf-8")
    (OUT / "wrestler_identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    rekey.sort(reverse=True)
    fetch.sort(reverse=True)
    (OUT / "asset_rekey.tsv").write_text(
        "# canonical-slug\tcopy-from (roster-img/*.webp)\n"
        + "".join(f"{c}\t{src}\n" for _, c, src, _ in rekey), "utf-8")
    (OUT / "needs_fetch.tsv").write_text(
        "# canonical-slug\tname\tmatches  (no image anywhere on disk)\n"
        + "".join(f"{c}\t{n}\t{t}\n" for t, c, _, n in fetch), "utf-8")

    print(f"events joined to cagematch  {joined}/{len(events)}")
    print(f"wrestlers resolved to a worker  {len(resolved)}/{len(W)}")
    print(f"split identities  {len(splits)}   names remapped  {len(canon_map)}")
    print(f"  named by: {dict(why)}")
    if skipped_shared:
        print(f"\nrefused to remap {len(skipped_shared)} shared ring name(s) "
              f"(worn by more than one wrestler, so they keep their own entry):")
        for n, would_be in skipped_shared:
            print(f"  {n!r} would have become {would_be!r}  owners={sorted(owners[n])}")
    print(f"\nassets: {len(identity) - len(rekey) - len(fetch)} canonical slugs already have a "
          f"headshot | {len(rekey)} re-key | {len(fetch)} need a fetch")
    print("\nre-keys:")
    for t, c, src, _ in rekey:
        print(f"  {t:>4}m  {c:24} <- {src}.webp")
    print(f"\nwrote canon_map.json, wrestler_identity.json, asset_rekey.tsv, needs_fetch.tsv")


if __name__ == "__main__":
    main()
