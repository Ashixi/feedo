self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // Logic to intercept absolute paths from iframes
  // Currently a placeholder for the Feedo rendering engine logic.
  // When a site tries to fetch '/_next/static/xyz.js', this SW will intercept it
  // and rewrite the URL to the correct gateway domain based on the referrer.
  
  // For the initial demo, we just pass through.
  event.respondWith(fetch(event.request));
});
