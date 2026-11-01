const CACHE='eduscan-v35';
const ASSETS=['./','./index.html','./styles.css','./vendor/zxing-browser.min.js','./offline-db.js','./app.js','./manifest.webmanifest','./icons/icon.svg','./icons/luna-school-logo.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request))));
