importScripts('https://cdn.jsdelivr.net/npm/localforage@1.10.0/dist/localforage.min.js');

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

const MIME_TYPES = {
  'html': 'text/html',
  'css': 'text/css',
  'js': 'application/javascript',
  'json': 'application/json',
  'png': 'image/png',
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'gif': 'image/gif',
  'svg': 'image/svg+xml',
  'ico': 'image/x-icon',
  'woff': 'font/woff',
  'woff2': 'font/woff2',
  'ttf': 'font/ttf',
  'eot': 'application/vnd.ms-fontobject',
  'otf': 'font/otf'
};

function getMimeType(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  return MIME_TYPES[ext] || 'application/octet-stream';
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // Intercept /sandbox/[cid]/...
  if (url.pathname.startsWith('/sandbox/')) {
    event.respondWith(
      (async () => {
        try {
          const parts = url.pathname.split('/');
          // parts: ['', 'sandbox', 'cid', 'filepath...']
          const cid = parts[2];
          let filepath = parts.slice(3).join('/');
          
          if (!filepath || filepath === '') {
            filepath = 'index.html';
          }
          if (filepath.endsWith('/')) {
            filepath += 'index.html';
          }
          
          const key = `${cid}/${filepath}`;
          
          // Try to get the file from localforage
          const fileData = await localforage.getItem(key);
          
          if (fileData) {
            const mimeType = getMimeType(filepath);
            let responseData = fileData;
            
            // Inject link interceptor into HTML to prevent 404 navigation
            if (mimeType === 'text/html') {
              const text = await new Blob([fileData]).text();
              const injected = text + `
<script>
document.addEventListener('click', function(e) {
  const a = e.target.closest('a');
  if (a) {
    const href = a.getAttribute('href');
    if (href && !href.startsWith('#')) {
      e.preventDefault();
      window.parent.postMessage({ type: 'FEEDO_LINK_CLICKED', href: a.href }, '*');
    }
  }
}, true);
</script>`;
              responseData = new Blob([injected], { type: 'text/html' });
            }

            return new Response(responseData, {
              status: 200,
              headers: {
                'Content-Type': mimeType,
                'Cache-Control': 'public, max-age=3600'
              }
            });
          } else {
            // Not found in our IndexedDB sandbox
            console.error('[SW] File not found in sandbox:', key);
            return new Response('File not found in Feedo network sandbox.', { status: 404 });
          }
        } catch (error) {
          console.error('[SW] Error fetching from sandbox:', error);
          return new Response('Internal Server Error', { status: 500 });
        }
      })()
    );
  }
});
