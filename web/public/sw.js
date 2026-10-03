/* Chakula service worker: installable app + works on patchy networks (spec section 5).
 *
 * - Pages: network first, falling back to the cached app shell when offline.
 * - Built assets, fonts, photos: cache first (they are content-hashed or never change).
 * - Hotels, menus, offers, config: show the cached copy at once, refresh in the background.
 * - Everything else (orders, payments, tracking, staff APIs): network only. Never cache money.
 */
const VERSION = "v1";
const SHELL = `chakula-shell-${VERSION}`;
const STATIC = `chakula-static-${VERSION}`;
const DATA = `chakula-data-${VERSION}`;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  const keep = new Set([SHELL, STATIC, DATA]);
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

const PUBLIC_DATA = [/^\/api\/v1\/hotels$/, /^\/api\/v1\/hotels\/[^/]+\/menu$/, /^\/api\/v1\/offers$/, /^\/api\/v1\/config$/];

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  const sameOrigin = url.origin === self.location.origin;
  const isStatic =
    (sameOrigin && (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/media/") || /\.(png|svg|webp|ico)$/.test(url.pathname))) ||
    url.hostname === "fonts.gstatic.com" ||
    url.hostname === "fonts.googleapis.com";
  if (isStatic) {
    event.respondWith(
      caches.open(STATIC).then((c) =>
        c.match(req).then(
          (hit) =>
            hit ||
            fetch(req).then((res) => {
              if (res.ok || res.type === "opaque") c.put(req, res.clone());
              return res;
            }),
        ),
      ),
    );
    return;
  }

  if (sameOrigin && PUBLIC_DATA.some((re) => re.test(url.pathname))) {
    event.respondWith(
      caches.open(DATA).then((c) =>
        c.match(req).then((hit) => {
          const fresh = fetch(req)
            .then((res) => {
              if (res.ok) c.put(req, res.clone());
              return res;
            })
            .catch(() => hit);
          return hit || fresh;
        }),
      ),
    );
  }
  // Anything else goes straight to the network.
});
