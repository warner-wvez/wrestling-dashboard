# Backfill 1985 to 2000

Adds every WWF show from 1985 to 2000 to the dashboard, cross-checked.

Run order (each step is resumable and writes into `out/`; fetched pages go to the gitignored `cache/`):

    uv run --with requests --with beautifulsoup4 python backfill/cm_results.py
    uv run --with requests python backfill/cawthon_fetch.py
    uv run --with requests --with beautifulsoup4 python backfill/cawthon_cards.py
    uv run --with requests --with beautifulsoup4 python backfill/wiki_discover.py
    uv run --with requests --with beautifulsoup4 python backfill/sdh_votes.py
    uv run --with requests --with beautifulsoup4 python backfill/fandom_votes.py --yes
    uv run --with requests --with beautifulsoup4 python backfill/join.py
    (Warner rules on out/review.csv)
    uv run --with requests --with beautifulsoup4 python backfill/apply.py
    uv run --with requests --with beautifulsoup4 lineup-check/title_audit.py

Spine per family: the cached Cagematch results rows (`.firecrawl/cagematch-raw/results-*.md`) for every TV family; Wikipedia for PPV and SNME. Cawthon (thehistoryofwwe.com) gives every TV air date, durations and finishes. SmackDown Hotel votes on Raw, SmackDown and Heat; Fandom votes on Raw and SmackDown.

Buckets (`verification_status`): `verified` = spine and a vote agree on every match's sides and winner; `flagged` = they split, the spine's card ships and the rows are in `out/review.csv`; `single-source` = only the spine exists.

Traps: Cagematch dates the taping night (three Superstars episodes on one date); episode numbers differ between sources and are never a join key; 95 ring names belong to two workers, so identity is per event by Cagematch worker number; Cawthon's headers read "Taped 8/3/88; City; Venue" with the air date on the next line.
