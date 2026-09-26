// sw.js — Service Worker for offline-capable operation.
//
// Strategy:
// - App shell (HTML/CSS/JS/icons): cache-first, so the UI itself loads with
//   zero connectivity, not just previously-viewed data.
// - API GET requests (report lists, notifications, statistics): network-first
//   with cache fallback, so the most recent data is shown when online, and
//   the last-known data is shown when offline (clearly marked stale by the
//   page itself, not by the service worker).
// - API POST/PATCH/write requests: always pass straight to the network.
//   If that fails because the device is offline, the failure is caught at
//   the application layer (app.js), which queues the submission in
//   IndexedDB instead. The service worker does not attempt background sync
//   itself, for simpler, more predictable cross-browser behaviour.

const CACHE_NAME = "drainage-watch-v1";

const APP_SHELL = [
  "/", "/index.html", "/register.html", "/login.html",
  "/resident_dashboard.html", "/report_form.html", "/my_reports.html",
  "/report_detail.html", "/notifications.html", "/profile.html",
  "/admin_dashboard.html", "/manage_reports.html", "/report_triage.html",
  "/statistics.html",
  "/style.css", "/app.js", "/idb.js", "/locationpicker.js", "/manifest.json",
  "/icon-192.png", "/icon-512.png",
];

const CDN_ASSETS = [
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(APP_SHELL);
      // Cache CDN assets opportunistically; don't fail install if this errors
      // (e.g. offline during first install) since the app shell is the priority.
      try {
        await Promise.all(
          CDN_ASSETS.map((url) => cache.add(new Request(url, { mode: "no-cors" })))
        );
      } catch (e) {
        console.warn("Could not pre-cache CDN assets:", e);
      }
      self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
      self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never intercept write operations — let the app layer handle offline queuing.
  if (req.method !== "GET") return;

  // API GET requests: network-first, fall back to cache when offline.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(req);
          const cache = await caches.open(CACHE_NAME);
          cache.put(req, fresh.clone());
          return fresh;
        } catch (err) {
          const cached = await caches.match(req);
          if (cached) return cached;
          return new Response(
            JSON.stringify({ error: "You are offline and no cached data is available for this request." }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      })()
    );
    return;
  }

  // App shell / static assets / CDN libs: cache-first, network fallback.
  event.respondWith(
    (async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone());
        return fresh;
      } catch (err) {
        if (req.mode === "navigate") {
          return caches.match("/index.html");
        }
        throw err;
      }
    })()
  );
});
