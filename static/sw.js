const CACHE_NAME = 'pallicare-v2';
const ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/images/pwa-icon.png',
    '/static/images/pwa-icon-192.png',
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

// Fetch Event - Network First Strategy with Dynamic Caching
self.addEventListener('fetch', (event) => {
    // Only cache GET requests to avoid issues with POST/Forms
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // To avoid caching errors, only cache OK 'basic' responses from our origin
                if (!response || response.status !== 200 || response.type !== 'basic') {
                    return response;
                }
                
                // Clone the response because the stream can only be consumed once
                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });
                
                return response;
            })
            .catch(() => {
                // If network fails (offline), fallback to whatever is in the cache
                return caches.match(event.request);
            })
    );
});
