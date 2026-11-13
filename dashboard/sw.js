// Service worker of the selftopo dashboard: makes it installable and opens it offline.
//
// App files in this folder: network first, so a new version arrives with the next start;
// the cache is only the fallback without a connection. Everything else passes through
// untouched: the data files next to the dashboard, the GitHub API and the web fonts.
// The page keeps its own snapshot of the last loaded data (see "offline snapshot").

const VERSION = "25";
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

  // Opening the dashboard with any query (?lang=en) is one cached page; other pages such as
  // tests.html keep their own entry, so they never replace the cached dashboard.
  const dashboard = request.mode === "navigate" && (url.pathname === scope.pathname || url.pathname === `${scope.pathname}index.html`);
  const key = dashboard ? "./" : request;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      if (response.ok) await cache.put(key, response.clone());
      return response;
    } catch {
      const hit = await cache.match(key, { ignoreSearch: true });
      return hit || Response.error();
    }
  })());
});

// Push notifications: the daily workflow sends the Today card (python -m selftopo push).
// The payload is JSON with title, body, url and tag; a tap opens or focuses the dashboard.
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data ? event.data.text() : "" }; }
  const scope = self.registration.scope;
  event.waitUntil(self.registration.showNotification(data.title || "selftopo", {
    body: data.body || "",
    tag: data.tag || "selftopo",
    icon: new URL("icons/icon-192.png", scope).href,
    badge: new URL("icons/favicon-32.png", scope).href,
    data: { url: new URL(data.url || "./", scope).href },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || self.registration.scope;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = windows.find((w) => w.url.startsWith(self.registration.scope));
    if (open) {
      await open.focus();
      if ("navigate" in open) await open.navigate(url).catch(() => {});
      return;
    }
    await self.clients.openWindow(url);
  })());
});
