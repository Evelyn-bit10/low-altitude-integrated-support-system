/* =========================================================================
 * 挺中航空 · Service Worker
 * -------------------------------------------------------------------------
 * 作用：让 App 可离线打开（PWA 安装后断网也能进界面，数据自动回退演示）。
 * 策略：
 *   - 同源静态资源（html/css/js/svg/manifest）：缓存优先 + 后台更新
 *   - /api/ 等后端请求：直接走网络，不缓存（避免拿到过期运行数据）
 * ========================================================================= */
var CACHE = 'flyer-app-v1';

var ASSETS = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './api.js',
  './mock.js',
  './map.js',
  './manifest.webmanifest',
  './icons/icon.svg',
  './icons/icon-maskable.svg'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return Promise.all(ASSETS.map(function (url) {
        return c.add(new Request(url, { cache: 'reload' })).catch(function () { });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) { return k === CACHE ? null : caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') { return; }

  var url = new URL(req.url);

  // 后端接口不缓存
  if (url.pathname.indexOf('/api/') === 0 || url.port === '8080' || url.port === '8090') { return; }

  // 只处理同源静态资源
  if (url.origin !== location.origin) { return; }

  e.respondWith(
    caches.match(req).then(function (cached) {
      var network = fetch(req).then(function (res) {
        if (res && res.status === 200 && res.type === 'basic') {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return cached; });

      return cached || network;
    })
  );
});
