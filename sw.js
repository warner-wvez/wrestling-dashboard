// Service worker for the WWE dashboard Pages build.
//
// The page inlines a lean core and lazy-fetches per-era match shards from
// shards/matches-<era>.json. This worker caches those shards (and the app shell)
// so the site keeps working offline after the first visit. Strategy is
// stale-while-revalidate: serve from cache instantly when present, and refresh
// in the background so a rebuilt shard is picked up on the next load. Bump CACHE
// when the data schema changes to retire old entries.
const CACHE = 'wrestling-dashboard-v3';

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
  const isShard = url.pathname.includes('/shards/matches-');
  const isShell = url.pathname.endsWith('/') || url.pathname.endsWith('/index.html');
  if (!isShard && !isShell) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(req);
    const network = fetch(req).then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    }).catch(() => null);
    return cached || (await network) || new Response('offline', { status: 503 });
  })());
});
