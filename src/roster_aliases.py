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
import json
import re
import sys
import unicodedata
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
# the 2001-2026 data. Keep the best-established WWE name as canonical for a WWE
# dashboard. Every entry was verified against the corpus (both names present,
# same person, plausible non-overlapping runs) before being added; do not add
# a pair from memory without checking the data first. Names that only differ
# by spelling/case/diacritics do NOT belong here (normkey grouping merges
# those automatically).
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
    # --- 2001-2010 era renames ---
    "Bradshaw": "JBL",
    # Both spellings, because normkey drops quoted nicknames and the two sources
    # disagree about whether "Bradshaw" is one. The official billing quotes it
    # ('John "Bradshaw" Layfield' -> johnlayfield, nickname stripped like
    # '"Stone Cold" Steve Austin' -> steveaustin), but Cagematch prints it bare,
    # so the corpus keys as johnbradshawlayfield. The quoted entry alone never
    # matched a single match and left him split from Bradshaw for 152 matches.
    'John "Bradshaw" Layfield': "JBL",
    "John Bradshaw Layfield": "JBL",
    "K-Kwik": "R-Truth",
    "Ron Killings": "R-Truth",
    "Albert": "A-Train",
    "Tensai": "A-Train",
    "Lord Tensai": "A-Train",
    "Kerwin White": "Chavo Guerrero",
    "The Goodfather": "The Godfather",
    "Chuck": "Chuck Palumbo",
    "Billy": "Billy Gunn",
    "Chaz": "Mosh",
    "Crash": "Crash Holly",
    "Kung Fu Naki": "Funaki",
    "Yoshihiro Tajiri": "Tajiri",
    "Chris Kanyon": "Kanyon",
    "Hugh Morrus": "Bill DeMott",
    "Stevie Richards": "Steven Richards",
    "Spanky": "Brian Kendrick",
    "Khosrow Daivari": "Daivari",
    "Jon Heidenreich": "Heidenreich",
    "Sylvan": "Sylvain Grenier",
    "Carlito Caribbean Cool": "Carlito",
    "Ken Kennedy": "Mr. Kennedy",
    "Sim Snuka": "Deuce",
    "Akio": "Jimmy Wang Yang",
    "AJ": "AJ Lee",
    "Mr. McMahon": "Vince McMahon",
    "Cactus Jack": "Mick Foley",
    "King Booker": "Booker T",
    "Rhino": "Rhyno",
    "Mighty Molly": "Molly Holly",
    "Gregory Helms": "The Hurricane",
    "Hurricane Helms": "The Hurricane",
    "Stephanie McMahon-Helmsley": "Stephanie McMahon",
    "Dave Batista": "Batista",
    "Lashley": "Bobby Lashley",
    "Dustin Rhodes": "Goldust",
    "B-2": "Bull Buchanan",
    "B²": "Bull Buchanan",
    "Santina Marella": "Santino Marella",
    "DH Smith": "David Hart Smith",
    "Brett Major": "Zack Ryder",
    "Brian Major": "Curt Hawkins",
    "Garrison Cade": "Lance Cade",
    "Armando Alejandro Estrada": "Armando Estrada",
    "Jillian": "Jillian Hall",
    "Slam Master J": "Jesse",
    "Tamina Snuka": "Tamina",
    "Jamal": "Umaga",
    "Montel Vontavious Porter": "MVP",
    "Big Daddy V": "Viscera",
    "Festus": "Luke Gallows",
    "Johnny Nitro": "John Morrison",
    "Nicky": "Dolph Ziggler",
    "Sheamus O'Shaunessy": "Sheamus",
    "Johnny Curtis": "Fandango",
    # --- 2010s-2020s renames ---
    "Husky Harris": "Bray Wyatt",
    "The Fiend": "Bray Wyatt",
    '"The Fiend" Bray Wyatt': "Bray Wyatt",
    "Michael McGillicutty": "Curtis Axel",
    "Skip Sheffield": "Ryback",
    "Colin Cassady": "Big Cass",
    "Ezekiel": "Elias",
    "Ali": "Mustafa Ali",
    "Apollo": "Apollo Crews",
    "Theory": "Austin Theory",
    "Madcap Moss": "Riddick Moss",
    "Happy Corbin": "Baron Corbin",
    "King Corbin": "Baron Corbin",
    "Nikki A.S.H.": "Nikki Cross",
    "Doudrop": "Piper Niven",
    "Derrick Bateman": "EC3",
    "Stardust": "Cody Rhodes",
    "Otis Dozovic": "Otis",
    "Tozawa": "Akira Tozawa",
    "Marcel Barthel": "Ludwig Kaiser",
    "Fabian Aichner": "Giovanni Vinci",
    "Hanson": "Ivar",
    "Rowe": "Erik",
    "Butch": "Pete Dunne",
    "Charlotte": "Charlotte Flair",
    "Riddle": "Matt Riddle",
    "Shorty G": "Chad Gable",
    "Robert Roode": "Bobby Roode",
    "Rowan": "Erick Rowan",
    "Harper": "Luke Harper",
    "Murphy": "Buddy Murphy",
    "Angel": "Angel Garza",
    "Humberto": "Humberto Carrillo",
    "Dabba-Kato": "Commander Azeez",
    "Reginald": "Reggie",
    "T-BAR": "Dijak",
    "Dominik Dijakovic": "Dijak",
    "Slapjack": "Shane Thorne",
    "Queen Zelina": "Zelina Vega",
    "Shotzi Blackheart": "Shotzi",
    "Valhalla": "Sarah Logan",
    "Ruby Riot": "Ruby Riott",
    "Veer": "Veer Mahaan",
    "Kacy Catanzaro": "Katana Chance",
    "Uncle Howdy": "Bo Dallas",
    "Tucker Knight": "Tucker",
    "Bad News Barrett": "Wade Barrett",
    "King Barrett": "Wade Barrett",
    'Seth "Freakin" Rollins': "Seth Rollins",
    "Diego": "Primo",
    "Fernando": "Epico",
    # --- gimmick-era billings and short forms (unquoted, so normkey's
    # quoted-nickname stripping cannot catch them) ---
    "Broken Matt Hardy": "Matt Hardy",
    "Matt Hardy Version 1.0": "Matt Hardy",
    "#DIY Tommaso Ciampa": "Tommaso Ciampa",
    "Gentleman Jack Gallagher": "Jack Gallagher",
    "Reverend D-Von": "D-Von Dudley",
    "D-Von": "D-Von Dudley",
    "Bubba Ray": "Bubba Ray Dudley",
    "Katie Lea Burchill": "Katie Lea",
    "Rey Mysterio Jr": "Rey Mysterio",
    "Ted DiBiase Jr": "Ted DiBiase",
    "Chavo Guerrero Jr": "Chavo Guerrero",
    "Chavo Guerrero Classic": "Chavo Guerrero Sr",
    "Buh Buh Ray Dudley": "Bubba Ray Dudley",
    "Terri": "Terri Runnels",
    # --- scraper prose glued onto a participant name (result-method text) ---
    "Matt Hardy by TKO": "Matt Hardy",
    "Jeff Hardy by TKO": "Jeff Hardy",
    "Shawn Stasiak by TKO": "Shawn Stasiak",
    "Daniel Bryan by Reverse Decision": "Daniel Bryan",
    "Isla Dawn to unify the titles": "Isla Dawn",
    "The Rock Non": "The Rock",
}

# Distinct people who shared or reused a ring name; never merge these even if
# a pair of them looks like a rename (documented so nobody "fixes" them later):
#   Naomi vs Cameron (Funkadactyls teammates), Kayden Carter vs Katana Chance
#   (tag partners), Sin Cara (Mistico then Hunico under the same mask),
#   Ariya Daivari vs Daivari (brothers), Ivory vs Tori, Gillberg vs Goldberg,
#   Chavo Guerrero Sr / "Chavo Guerrero Classic" vs Chavo Guerrero (father vs
#   son), Mini Mr. Kennedy vs Mr. Kennedy (lookalike performer), Jack
#   Swagger's Soaring Eagle (costumed extra, not Swagger).

# Names that must keep their established ring name and never be aliased away.
# The live roster page sometimes lists a wrestler under a real name (Triple H ->
# "Paul Levesque", Tyson Kidd -> "TJ Wilson"), a temporary masked gimmick (Tyler
# Bate / Pete Dunne -> the rotating "...Americano" luchador), or a nickname
# (Natalya -> "Nattie"); those would mis-rename well-known wrestlers.
# Marcel Barthel is intentionally NOT protected: his permanent rename to Ludwig
# Kaiser is handled in CURATED, which outranks whatever the roster page says.
PROTECTED = {
    "Triple H", "Tyson Kidd", "Natalya", "Tyler Bate", "Pete Dunne",
    "Will Hobbs",
    # The rotating "...Americano" luchadors are a storyline in which several
    # wrestlers appear as the same masked character, so the mask is its own
    # identity and must not fold into whoever is under it this month. Protecting
    # only the wrestlers (Tyler Bate, Pete Dunne) is not enough: it stops the
    # wrestler being renamed to the mask, not the mask being renamed to the
    # wrestler, and the roster page encodes exactly that direction. Without
    # these, a rebuild merges El Grande Americano into Ludwig Kaiser, Bravo
    # Americano into Tyler Bate, and Rayo Americano into Pete Dunne.
    # One entry per identity: normkey drops quoted nicknames, so
    # '"Original" El Grande Americano' is the same key as "El Grande Americano"
    # and listing both would leave protected_by_key's winner up to set iteration
    # order (and crown the quoted spelling). See
    # test_protected_has_no_duplicate_identity_keys.
    "El Grande Americano", "Bravo Americano", "Rayo Americano",
    "Bruto Americano", "Julio Americano",
}



_QUOTED_NICK_RE = re.compile(r'["“”][^"“”]*["“”]')


def normkey(name):
    """Spelling-insensitive identity key: drop quoted nicknames, transliterate
    diacritics, lowercase, drop a leading 'the', strip everything but a-z0-9.
    'The Big Show'/'Big Show' -> 'bigshow'; 'Rey Fénix'/'Rey Fenix' -> 'reyfenix';
    '"Dirty" Dominik Mysterio'/'Dominik Mysterio' -> 'dominikmysterio'.
    A name that is nothing but its quoted part keeps it (never key on '')."""
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower().strip()
    unquoted = _QUOTED_NICK_RE.sub(" ", n).strip()
    if unquoted:
        n = unquoted
    n = re.sub(r"^the\s+", "", n)
    key = re.sub(r"[^a-z0-9]+", "", n)
    # An all-symbol name ('"???"') would key to '' and collide with every
    # other all-symbol name; keep its symbols as its identity instead.
    return key or re.sub(r"\s+", "", n)


# Re-spell a name the corpus gets wrong more often than right.
#
# Display is chosen by usage, which is right nearly always, and inherits the
# source's typos when it is not: Cagematch prints the Right To Censor character
# as "The Good Father" 10 times and "The Goodfather" (the actual name) 7, so the
# typo wins the vote and lands on the roster. CURATED cannot fix that, because
# both spellings are one identity to normkey, and CURATED only ever answers "who
# is this", never "how is it spelled".
#
# Keyed by normkey, so an entry may only re-spell a name, never re-identify it
# (test_display_spelling_never_changes_identity enforces exactly that). Reach for
# this only when the source is wrong, not to overrule a ring name you happen to
# like less: a wrestler billed under a name they really used stays labelled by
# usage.
DISPLAY_SPELLING = {
    normkey("The Goodfather"): "The Goodfather",
}


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


# Committed snapshot of the last successful roster scrape. Rebuilds fall back
# to it when the live page is unreachable, so a scrape failure can never
# silently un-merge every roster-derived rename (it used to).
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "sdh-roster-pairs.json"


def save_roster_snapshot(pairs, path=None):
    p = Path(path) if path else SNAPSHOT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([list(x) for x in pairs], indent=0) + "\n", encoding="utf-8")


def load_roster_snapshot(path=None):
    """Return the saved [(slug, name)] pairs, or None if no snapshot exists."""
    p = Path(path) if path else SNAPSHOT_PATH
    if not p.exists():
        return None
    return [tuple(x) for x in json.loads(p.read_text(encoding="utf-8"))]


def build_canon_map(name_counts, roster_pairs=None, curated=None):
    """Map every raw participant name to its canonical wrestler name.

    name_counts: {raw_name: how_many_matches} (used to pick the dominant display
    for spelling-variant groups). roster_pairs: override the live scrape (tests).
    """
    curated = CURATED if curated is None else curated
    if roster_pairs is None:
        try:
            roster_pairs = scrape_roster()
        except Exception as exc:  # offline / page moved: fall back to the snapshot
            roster_pairs = load_roster_snapshot() or []
            src = "committed snapshot" if roster_pairs else "curated + variants only"
            print(f"  roster scrape failed ({exc}); aliasing from {src}")

    canonical_by_key = {}
    for slug, name in roster_pairs:               # name-key and slug-key -> current name
        canonical_by_key[normkey(name)] = name
        canonical_by_key.setdefault(normkey(slug), name)
    # Curated outranks the scrape and must own BOTH keys of each pair: with a
    # setdefault here, a scrape entry that already claimed the new-name key
    # (e.g. the page slug "angel-garza" titled "Angel") would leave the two
    # names pointing at different canonicals, keeping the split alive.
    for old, new in curated.items():
        canonical_by_key[normkey(old)] = new
        canonical_by_key[normkey(new)] = new
    protected_by_key = {normkey(p): p for p in PROTECTED}   # highest priority

    groups = defaultdict(Counter)                 # spelling-variant fallback
    for n, c in name_counts.items():
        groups[normkey(n)][n] += c

    # Pass 1: WHO is this. The curated table and the roster page answer identity
    # only; the target they name is a merge key, not necessarily what we call the
    # person.
    identity = {}
    for n in name_counts:
        k = normkey(n)
        identity[n] = (protected_by_key.get(k) or canonical_by_key.get(k)
                       or groups[k].most_common(1)[0][0])

    # Pass 2: WHAT do we call them. The display is the ring name the corpus
    # actually used most for that person, not whichever spelling the curated
    # table happened to point at. Those are different questions, and conflating
    # them shipped names nobody is ever billed under: CURATED said to call the
    # APA/Layfield wrestler "JBL", a string that appears in zero matches, and to
    # call T-BAR (31 matches) "Dijak" (5).
    #
    # A PROTECTED identity keeps its declared name: it is protected precisely
    # because the sources try to rename it, so frequency is not the authority
    # there. Everyone else is labelled by usage, which also makes it impossible
    # for the roster to show a name that never appears on a card.
    members = defaultdict(list)
    for n, ident in identity.items():
        members[ident].append(n)

    out = {}
    for ident, names in members.items():
        if normkey(ident) in protected_by_key:
            display = ident
        else:
            # Most-used spelling wins. On a tie, defer to the declared identity:
            # usage has no opinion there, and the sources do know which name is
            # current (a rename the corpus has barely seen yet ties at low counts,
            # and WALTER must not out-rank Gunther on a coin flip). Name breaks
            # the remaining ties so a rebuild is deterministic rather than
            # dict-order dependent.
            display = max(names, key=lambda n: (name_counts.get(n, 0),
                                                normkey(n) == normkey(ident), n))
            # Usage picked the winning spelling; correct it if the corpus spells
            # that name wrong more often than right. Identity is already settled
            # above, so this can only change how the name reads.
            display = DISPLAY_SPELLING.get(normkey(display), display)
        for n in names:
            out[n] = display
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
