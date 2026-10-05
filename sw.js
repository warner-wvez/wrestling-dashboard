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
const CACHE = 'wrestling-dashboard-v19';

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
