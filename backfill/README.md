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
    uv run --with requests python backfill/wayback_tv.py fetch     # WWF's own 1999 to 2000 write-ups, hours
    uv run --with requests --with beautifulsoup4 python backfill/wayback_tv.py check   # -> out/rulings_wayback.csv
    (Warner rules on out/review.csv; rulings go in out/rulings.csv)
    uv run --with requests --with beautifulsoup4 python backfill/apply.py
    uv run --with requests --with beautifulsoup4 lineup-check/title_audit.py

Spine per family: the cached Cagematch results rows (`.firecrawl/cagematch-raw/results-*.md`) for every TV family; Wikipedia for PPV and SNME. Cawthon (thehistoryofwwe.com) gives every TV air date, durations and finishes. SmackDown Hotel votes on Raw, SmackDown and Heat; Fandom votes on Raw and SmackDown.

Buckets (`verification_status`): `verified` = spine and a vote agree on every match's sides and winner; `flagged` = they split, the spine's card ships and the rows are in `out/review.csv`; `single-source` = only the spine exists.

Traps: Cagematch dates the taping night (three Superstars episodes on one date); episode numbers differ between sources and are never a join key; 95 ring names belong to two workers, so identity is per event by Cagematch worker number; Cawthon's headers read "Taped 8/3/88; City; Venue" with the air date on the next line.

Two sources against the spine change the card: when the comparer's third-source vote says SmackDown Hotel or Fandom sides with Cawthon against the Cagematch card, the join swaps the winner, appends the missing match, or drops the extra name, and lists the change in `out/applied_votes.csv`. Name-level lineup swaps stay with a person.

Gold source for June 1999 to June 2000: WWF's own results archive (wwf.com/tv/archives) through the Wayback Machine. `wayback_tv.py check` settles review rows by who WWF names on the page and writes `out/rulings_wayback.csv` with the archive URL per row; copy the rows you accept into `out/rulings.csv`. Nothing earlier survives online.
