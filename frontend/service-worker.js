const CACHE = 'aniwhere-app-v13-name-avatar';
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
  './assets/naruto-history-user.png'
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
