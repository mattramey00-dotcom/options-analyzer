const CACHE_NAME = 'ep-v3';
// Relative to this script's own URL (i.e. the service worker's scope),
// NOT the site root — this is a GitHub Pages *project* site served
// under /options-analyzer/, so root-absolute paths like '/index.html'
// 404 against the bare domain. Keep these scope-relative.
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=DM+Sans:wght@400;500;600;700;800&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js',
];

// Install — cache core assets
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — network-first for JSON data, cache-first for static assets
self.addEventListener('fetch', e => {
  let pathname;
  try {
    pathname = new URL(e.request.url).pathname;
  } catch (err) {
    // If URL parsing itself ever throws in some browser edge case, don't
    // let that break the request — just pass it straight to the network.
    e.respondWith(fetch(e.request));
    return;
  }

  // Always fetch stock_data.json from network first (fresh data matters)
  if (pathname.includes('stock_data.json')) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets — cache first, network fallback
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        }
        return resp;
      });
    })
  );
});
