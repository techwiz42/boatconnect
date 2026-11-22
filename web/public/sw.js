// boatconnect's service worker. It exists so the installed app opens at once and shows its own page, with a clear message, when the phone has no signal.
//
// It keeps ONLY the app's own files (the page, the hashed scripts and styles, the icons). It never touches /api/: boats, members, phone numbers, trips and photos are never
// stored on the phone by this worker, so nothing about other people is left behind when someone logs out or hands the phone to someone else.
const CACHE = "boatconnect-v1";
const SHELL = "/__shell";                       // the page that every route of the app is served as (index.html), kept under one name

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; // the browser handles these as it always did

  if (request.mode === "navigate") {
    event.respondWith(page(request));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(fromCacheFirst(request));                  // file names carry a hash of their content, so a cached one is never stale
  } else if (/\.(png|svg|jpg|webmanifest)$/.test(url.pathname)) {
    event.respondWith(refreshing(request));                      // icons and the background photo: use what we have, fetch a fresh copy for next time
  }
});

/** A page: from the network when it can be reached (so a deploy shows at once), otherwise the kept copy of the app. */
async function page(request) {
  try {
    const response = await fetch(request);
    if (response.ok && (response.headers.get("content-type") || "").includes("text/html")) {
      const cache = await caches.open(CACHE);
      await cache.put(SHELL, response.clone());
    }
    return response;
  } catch {
    const kept = await caches.match(SHELL);
    return kept || new Response("boatconnect cannot be reached. Check your connection and try again.", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}

async function fromCacheFirst(request) {
  const kept = await caches.match(request);
  if (kept) return kept;
  const response = await fetch(request);
  if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
  return response;
}

async function refreshing(request) {
  const cache = await caches.open(CACHE);
  const kept = await cache.match(request);
  const fresh = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  });
  if (kept) {
    fresh.catch(() => undefined);
    return kept;
  }
  return fresh;
}
