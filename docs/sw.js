/* Service worker: offline app shell, always-fresh data, and push notifications. */
const VERSION = "sc-2.2.1";  // match APP_VERSION in scanner/config.py
const SHELL = [
  "./", "index.html", "style.css", "app.js", "manifest.webmanifest",
  "vendor/lightweight-charts.standalone.production.js",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/favicon.png",
  "fonts/plex-400.woff2", "fonts/plex-500.woff2", "fonts/plex-600.woff2", "fonts/plex-700.woff2",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // Data: network first (fresh), fall back to the last copy when offline.
  if (url.pathname.includes("/data/")) {
    e.respondWith((async () => {
      const cache = await caches.open(VERSION);
      const key = url.origin + url.pathname;              // ignore cache-busting query
      try {
        const res = await fetch(e.request, {cache: "no-store"});
        if (res.ok) cache.put(key, res.clone());
        return res;
      } catch (err) {
        const hit = await cache.match(key);
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }

  // App shell: serve cached copy instantly, refresh it in the background.
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const hit = await cache.match(e.request, {ignoreSearch: true});
    const net = fetch(e.request).then(res => { if (res.ok) cache.put(e.request, res.clone()); return res; })
      .catch(() => hit);
    return hit || net;
  })());
});

// ---- push notifications (sent by the daily scan) ----
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {body: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.title || "Stock Crawler", {
    body: d.body || "New scan results are ready.",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    tag: d.tag || "daily-scan",
    renotify: true,
    data: {url: d.url || "./"},
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const target = new URL(e.notification.data?.url || "./", self.registration.scope).href;
  e.waitUntil((async () => {
    const wins = await clients.matchAll({type: "window", includeUncontrolled: true});
    for (const w of wins) {
      if (w.url.startsWith(self.registration.scope)) { w.postMessage({type: "refresh"}); return w.focus(); }
    }
    return clients.openWindow(target);
  })());
});
