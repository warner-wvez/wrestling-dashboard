"""Shared paths and builders for the 1985 to 2000 backfill.

Every lane writes its cards in the bundle's own event and match shape (the
one src/build_update.blank_event and map_match produce), so join.py and
apply.py never translate. The two builders here are those shapes with the
one field this backfill adds: `family` on the event.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CACHE = HERE / "cache"
YEARS = range(1985, 2001)

FAMILIES = {
    "Raw": "main", "SmackDown": "main", "PPV": "main", "SNME": "main",
    "Superstars": "syndicated", "Challenge": "syndicated", "PrimeTime": "syndicated",
    "AllAmerican": "syndicated", "Heat": "syndicated", "Shotgun": "syndicated",
    "Mania": "syndicated", "SundaySlam": "syndicated", "Jakked": "syndicated",
    "ActionZone": "syndicated",
}


def fresh_event(**kw) -> dict:
    base = dict(id=None, air_date=None, tape_date=None, date_derivation="live-broadcast",
                show_type=None, family=None, episode_number=None, title=None, ppv_name=None,
                venue=None, city=None, state_province=None, country=None, attendance=None,
                tv_network=None, tv_rating=None, broadcast_type=None, commentary=None,
                promotion="WWF", promotion_raw="WWF", cagematch_nr=None, cagematch_url=None,
                fandom_slug=None, fandom_url=None, primary_source="other",
                verification_status="unverified", match_count=0, matches=[], logo=None)
    base.update(kw)
    if base["family"] is None and base["show_type"] in FAMILIES:
        base["family"] = FAMILIES[base["show_type"]]
    base["match_count"] = len(base["matches"])
    return base


def _outcome(was_winner, method, decided):
    if not decided:
        return "no-contest"
    if was_winner is None:
        return None
    kind = "win" if was_winner else "loss"
    low = (method or "").lower()
    if "dq" in low or "disqualif" in low:
        return "dq-" + kind
    if "count" in low:
        return "countout-" + kind
    return kind


def fresh_match(order: int, teams: list[dict], **kw) -> dict:
    """teams: [{participants, was_winner, team_name?, accompaniment?, was_champion_entering?}]"""
    decided = any(t.get("was_winner") for t in teams)
    method = kw.get("result_method") or "defeated"
    out_teams = []
    for i, t in enumerate(teams, 1):
        parts = list(t.get("participants") or [])
        out_teams.append({
            "team_number": i,
            "team_name": t.get("team_name") or " & ".join(parts) or None,
            "accompaniment": t.get("accompaniment"),
            "was_winner": t.get("was_winner"),
            "match_outcome": _outcome(t.get("was_winner"), method, decided),
            "was_champion_entering": bool(t.get("was_champion_entering")),
            "participants": parts,
        })
    m = {"id": None, "match_order": order, "match_type": None, "stipulation": None,
         "title_at_stake": None, "duration_seconds": None, "result_method": method,
         "match_guide_rating": None, "raw_description": "", "teams": out_teams}
    m.update({k: v for k, v in kw.items() if k != "teams"})
    return m


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def record_status(lane: str, ok: bool, detail: str) -> None:
    """Each lane leaves a line apply.py reads for its ship gate."""
    p = OUT / "run_status.json"
    cur = read_json(p) if p.exists() else {}
    cur[lane] = {"ok": ok, "detail": detail,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_json(p, cur)
