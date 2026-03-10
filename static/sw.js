const CACHE_NAME = 'pallicare-v1';
const ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/images/pwa-icon.png',
    '/static/images/real_ward.png',
    '/static/images/real_care.png'
];

// Install Event
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

// Fetch Event
self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
