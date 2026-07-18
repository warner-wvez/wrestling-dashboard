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
const CACHE = 'wrestling-dashboard-v8';

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
