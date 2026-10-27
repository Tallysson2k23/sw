const CACHE='sw-public-v8';
const ASSETS=['/static/style.css','/static/style.css?v=home-8','/static/logo-sw-transparente.png','/static/fonts.css','/static/app.js','/static/icon.svg','/static/icon-192.png','/static/icon-512.png','/static/offline.html','/static/manifest.webmanifest'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('sw-public-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin)return;
 // Only immutable public assets enter the cache. Never store HTML sessions, CSRF tokens or private responses.
 const assetKey=url.pathname+url.search;
 if(ASSETS.includes(assetKey)){event.respondWith(caches.match(assetKey).then(cached=>cached||fetch(event.request)));return;}
 if(event.request.mode==='navigate')event.respondWith(fetch(event.request).catch(()=>caches.match('/static/offline.html')));
});
