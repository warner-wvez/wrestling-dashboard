"""Third vote: SmackDown Hotel's card for the same show settles a disagreement
between our card and Cawthon's when it agrees with one of them.

SmackDown Hotel is editor-curated and read by the dashboard's own parser
(src/smackdownhotel.parse_year_html), so its matches arrive in our shape:
teams of participants with was_winner. Weekly Raw and SmackDown only; PPVs keep
their disagreements for review until a PPV third source is added.

Verdicts per row class, written to row["vote"]:
  unpaired           SDH has it -> "aired" (keep, his list missed it)
                     SDH lacks it -> "not_aired" (2 of 3 say it never aired)
  missing_match      SDH has it -> "add_match" (2 of 3 say it aired, ours lacks it)
                     SDH lacks it -> "keep" (2 of 3 do not have it)
  dark_but_televised SDH has it -> "aired" ; lacks it -> "not_aired"
  result             SDH winner agrees with ours -> "keep", with his -> "fix_result"
  different_opponent, extra_name, cawthon_only_name
                     SDH people equal ours -> "keep"; equal his -> "fix_lineup"
  anything else, or SDH silent/ambiguous -> "split" (Warner rules)
"""
from lineup_match import _people, best_match

AUTO = {"not_aired", "add_match", "fix_result", "fix_lineup"}


def _sdh_people(m, show_names):
    return {best_match(p, show_names) or p for t in m.get("teams") or [] for p in t.get("participants") or [] if p}


def _sdh_winners(m, show_names):
    w = next((t for t in m.get("teams") or [] if t.get("was_winner")), None)
    return {best_match(p, show_names) or p for p in (w or {}).get("participants") or [] if p}


def find(sdh_matches, people, show_names):
    """SDH match sharing at least half of the people both ways, or None."""
    people = set(people)
    best, best_s = None, 0.0
    for m in sdh_matches:
        sp = _sdh_people(m, show_names)
        common = len(sp & people)
        if not common:
            continue
        s = common / max(len(sp), len(people))
        if s > best_s:
            best, best_s = m, s
    return best if best_s >= 0.5 else None


def vote(row, ours_match, his_names, his_winners, sdh_matches, show_names):
    cls = row["class"]
    if sdh_matches is None:
        return "split"
    if cls in ("unpaired", "dark_but_televised"):
        return "aired" if find(sdh_matches, _people(ours_match), show_names) else "not_aired"
    if cls == "missing_match":
        return "add_match" if find(sdh_matches, his_names, show_names) else "keep"
    s = find(sdh_matches, _people(ours_match) if ours_match else his_names, show_names) \
        or (find(sdh_matches, his_names, show_names) if his_names else None)
    if s is None:
        return "split"
    if cls == "result":
        sw = _sdh_winners(s, show_names)
        ow = {p for t in ours_match["teams"] if t.get("was_winner") for p in t["participants"]}
        if sw == ow:
            return "keep"
        if his_winners and sw == set(his_winners):
            return "fix_result"
        return "split"
    if cls in ("different_opponent", "extra_name", "cawthon_only_name"):
        sp = _sdh_people(s, show_names)
        if sp == set(_people(ours_match)):
            return "keep"
        if his_names and sp == set(his_names):
            return "fix_lineup"
        return "split"
    return "split"
