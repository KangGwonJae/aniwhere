const CACHE = 'aniwhere-app-v24-api-integration';
const APP_SHELL = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './manifest.webmanifest',
  './assets/midoriya-mascot.png?v=2',
  './assets/midoriya-icon-192.png?v=3',
  './assets/midoriya-icon-512.png?v=3',
  './assets/midoriya-apple-touch-icon.png?v=3',
  './assets/my-hero-academia.jpg',
  './assets/spoiler-stop-dio.png',
  './assets/light-card-user.png',
  './assets/gon-card-user.png',
  './assets/okabe-card-user.png',
  './assets/l-detective-user.png',
  './assets/eren-spoiler-user.png',
  './assets/naruto-history-user.png',
  './assets/zoldyck-family-map.png',
  './assets/hxh-gon.png',
  './assets/hxh-killua.png',
  './assets/hxh-leorio.png',
  './assets/hxh-kurapika.png',
  './assets/hxh-netero.png',
  './assets/hxh-biske.png',
  './assets/hxh-hisoka.png',
  './assets/hxh-illumi.png',
  './assets/hxh-phantom-troupe.png',
  './assets/hxh-zeno.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) return;
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then(hit => {
        if (hit) return hit;
        if (event.request.mode === 'navigate') return caches.match('./index.html');
        return Response.error();
      }))
  );
});
