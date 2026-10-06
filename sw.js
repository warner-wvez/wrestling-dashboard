// Service worker for the WWE dashboard Pages build.
//
// The page inlines a lean core and lazy-fetches per-era match shards from
// shards/matches-<era>.json. This worker keeps the site working offline after
// the first visit, with different strategies per asset:
//
//  - Shell (index.html, which carries the baked roster/title indexes):
//    NETWORK-first, cache as offline fallback. A deploy therefore reaches
//    returning visitors on their next load; the old stale-while-revalidate
//    strategy could pin them to a previous build's stats indefinitely
//    because the background refresh was not kept alive with waitUntil.
//  - Shards: cache-first for speed, refreshed in the background under
//    event.waitUntil so the refresh survives the response being returned.
//
// Bump CACHE on data or schema changes to retire old entries wholesale.
// v7: the match shards changed (multi-man sides un-fused), and shards are served
// cache-first, so a returning visitor would otherwise keep the old teams until a
// background refresh landed on some later load.
// v8: matches-2001 gained the January 1 2001 Raw (#397), previously missing.
// v9: modern shards changed (phantom group labels un-fused from participants).
// v10: corpus refresh ingested new shows through July 2026, and the present-day
// shards re-parsed clean against the source site's rewritten match lines.
// v11: titles.json changed shape ({active, retired}, per-reign belt stamps),
// the Mysterio/Veer typo strays merged into their real entries, and
// belts/wwe-championship.webp was replaced (it was big gold, not the WWE
// Championship, so every Undisputed champion wore the wrong belt).
// v12: the reign walk gained three guards, so title_reigns and titles.json both
// changed. Fabricated reigns are gone (Triple H's 2006 WWE Championship, Edge's
// 2004 World Heavyweight, Kofi Kingston's Universal, five wrong inaugural
// champions), champions respelled mid-reign no longer read as title changes, and
// a retired belt's last champion no longer holds its revived namesake for years.
// Shards are served cache-first, so without this bump a returning visitor keeps
// the old champions board indefinitely.
// v13: 2001-2019 match shards changed. 433 sides got back the wrestler the old
// parser dropped when a partner was named before a stable ("Billy Gunn & The
// APA"), and two sides that had become their special referee got their real
// wrestlers back. Four zero-day phantom tag reigns left title_reigns with them.
// v14: 760 2001-2013 dark matches now carry aired: false (greyed, "Not on the
// broadcast"), 13 wrestlers a stored lineup had lost are back, and 73 junk
// participant names ("countout", "Jeff Hardy by TKO", "and") are cleaned. The
// card template changed too, so index.html and every match shard are new.
// v15: 23 "vs." result sides a hyphen had cut short are whole again (D-Von
// Dudley, R-Truth, Rated-RKO, The X-Factor), and 9 more dark matches are greyed.
// v16: 31 match results corrected where all three sources (ours, Cawthon,
// SmackDown Hotel) list the same people and the other two agree on the winner,
// and 4 missing matches added in card order. Match shards changed.
// v17: 14 shows that held the next episode's card moved to their real dates,
// 13 recovered shows and 4 missing ones (incl. One Night Stand 2007/2008 and
// Fatal 4-Way 2010) added, 3 dates fixed. Core and match shards changed.
// v18: 8 shows moved to the dates WWE's archive and Wikipedia give (the 2011-12
// Tuesday SmackDowns, Raw's 2006 and 2007 Thursday airings), the 2005-11-29
// SmackDown special and the four UK PPVs added.
// v19: 3 same-night Hardcore title swaps added (Raw 2001-01-22 and 2001-09-10,
// SmackDown 2002-02-28) and 3 more dark matches greyed. Match shards and the
// title history changed.
// v20: 8 DQ and count-out results corrected to the no contests WWE's own
// recaps report, and 15 more dark matches greyed. Match shards changed.
// v21: title history fixed where a belt was won while vacant (Christian's IC
// title at Judgment Day 2003 and about 30 more), the 2007 ECW chain (Vince
// McMahon, not Shane) and the Jazz 2003 fragment; Raw #896 and the Best of
// SmackDown 2006 episode added; 9 more dark matches greyed. Core and match
// shards and titles changed.
// v22: the 2001-02 Hardcore title history rebuilt: 29 televised 24/7 title
// changes added to their cards, 5 changes inside matches, and 125 house-show
// changes (data/offcard-title-changes.json). Match shards and titles changed.
// v23: a stand-in now wins a belt for the man he replaced (Booker T's 2006 US
// title, the 2018 NXT tag titles), and two garbled match records repaired.
// v24: belts filed by which belt they were on each date (one WWE Championship
// instead of nine, the 1956 Women's title apart from the 2016 ones, the 1971 and
// 2024 World Tag Team titles apart), eight wrong title changes fixed, and 18
// misspelled names corrected. Core, match shards and titles changed.
// v25: vacancies from the title histories end reigns on the day a belt was
// vacated (45 of them), titles awarded without a match added, and Becky
// Lynch's 2024 Women's World title reign restored. Core and titles changed.
// v26: tag title histories matched to Wikipedia (Freebird defenses no longer
// split a reign, house-show changes dated, WrestleMania XL's ladder match
// split between its two winning teams), three more vacancies, and seven DQ
// or count-out results fixed. Core, match shards and titles changed.
// v27: result text taken out of 315 side names ("The Big Show by Count Out",
// "Christian to retain the ...") and a 2018 tag battle royal given its six
// teams back. Core and match shards changed.
// v28: 226 multi-man sides split back into the sides the match text lists
// (Elimination Chambers, ladder matches, gauntlets, multi-team tag matches drew
// as handicap matches). Core and match shards changed.
// v29: the 24/7 title's full history, 74 reigns to 205 (changes backstage, at
// ringside, at house shows), and Reggie's 2021-11-08 win credited over Drake
// Maverick. Core, the 2019 match shard and titles changed.
// v30: the NXT Cruiserweight title's full history, 15 reigns to 20 (changes on
// NXT, 205 Live and pay-per-view pre-shows), every reign on its real start
// date, and Devlin's reign running beside Escobar's interim one. Core and
// titles changed.
// v31: the six NXT belts' full histories (changes on NXT TV, and the four won
// on our NXT cards without a title-change mark), three NXT vacancies, and two
// rulings (Fyre and Dawn the last NXT women's tag champions, Zaria a stand-in
// for Sol Ruca). Core, the 2022 and 2025 match shards and titles changed.
// v32: Raven's Hardcore title win at Columbia, SC, 2002-07-28, the night's
// first change, which the records told three ways (WWE.com breaks the tie).
// Core and titles changed.
// v33: WCW's 2001 belt named "WCW World Heavyweight Championship", not "World
// Heavyweight Championship (2001)", and the 2002-13 belt loses the years it
// carried only to tell the two apart. Titles changed.
// v34: 32 main-roster reigns start on the day the histories give: changes on
// shows we don't carry (Velocity, Main Event, ECW), on pre-shows, outside a
// match (the 2021 draft swap), and nine card wins the walk could not read
// (WrestleMania 38, Big E's cash-in, Christian's DQ win). Ezekiel Jackson is
// the last ECW champion. Core, the 2004, 2007, 2019, 2022 and 2025 match
// shards and titles changed.
// v35: the three NXT UK belts' full histories to their unification at Worlds
// Collide 2022 (UK title 3 reigns to 5, UK Women's 3 to 4, UK Tag 2 to 7), the
// UK title's own page, two NXT vacancies, and belt pictures for 14 more title
// names. Core, the 2022 match shard, titles and belts changed.
// v36: every unnamed opponent reads "a local competitor" or "N local
// competitors" (was "a jobber", "2 jobbers", "3 local athletes"). Core and
// the 2019 and 2022 match shards changed.
// v37: match reports from Wikipedia's results tables read as names, not link
// code ("[[Kay Lee Ray]] defeated [[Mia Yim]]"). Core changed.
// v38: valets read to the end of their bracket: 34 ringside lines lose their
// link code and 13 valets leave the wrestler lists (Roxanne Perez beside
// Dominik Mysterio, three of Legado del Fantasma at WrestleMania XL), and three
// multi-team matches get their sides back. Core and the 2007, 2019, 2022 and
// 2025 match shards changed.
const CACHE = 'wrestling-dashboard-v38';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Only manage the app shell + match shards; let everything else hit the network.
  // Every shard, not a list of them. The old whitelist named matches-*, media
  // and profiles, and then the app grew belts, titles, promos, feuds and
  // tournaments shards that it never learned about, so the Titles view and the
  // promo/feud/tournament shelves fetched from a network that is not there and
  // failed offline, against the promise at the top of this file.
  const isShard = url.pathname.includes('/shards/');
  const isShell = url.pathname.endsWith('/') || url.pathname.endsWith('/index.html');
  if (!isShard && !isShell) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    // Fetch + cache as one unit so a single waitUntil keeps both alive.
    const network = fetch(req).then(async (res) => {
      if (res && res.ok) await cache.put(req, res.clone());
      return res;
    }).catch(() => null);

    if (isShell) {
      return (await network) || (await cache.match(req))
        || new Response('offline', { status: 503 });
    }
    const cached = await cache.match(req);
    if (cached) {
      event.waitUntil(network);   // refresh completes even after we respond
      return cached;
    }
    return (await network) || new Response('offline', { status: 503 });
  })());
});
