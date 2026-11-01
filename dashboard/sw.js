// Service worker of the selftopo dashboard: makes it installable and opens it offline.
//
// App files in this folder: network first, so a new version arrives with the next start;
// the cache is only the fallback without a connection. Everything else passes through
// untouched: the data files next to the dashboard, the GitHub API and the web fonts.
// The page keeps its own snapshot of the last loaded data (see "offline snapshot").

const VERSION = "9";
const CACHE = `selftopo-app-${VERSION}`;
const APP_FILES = [
  "./",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/maskable-512.png",
  "./icons/apple-touch-icon.png",
  "./icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => (k.startsWith("selftopo-app-") || k.startsWith("healthsync-app-")) && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  const scope = new URL(self.registration.scope);
  if (request.method !== "GET" || url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      if (response.ok) await cache.put(request.mode === "navigate" ? "./" : request, response.clone());
      return response;
    } catch {
      const hit = await cache.match(request.mode === "navigate" ? "./" : request, { ignoreSearch: true });
      return hit || Response.error();
    }
  })());
});
