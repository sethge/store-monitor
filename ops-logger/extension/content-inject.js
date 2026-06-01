/**
 * Content Script (ISOLATED world) - Injects shop name probe into page
 *
 * Strategy: Use <script> tag injection to run in MAIN world.
 * Extracts shop info from API responses and probes DOM for shop name.
 *
 * Data flow: page MAIN world -> postMessage -> ISOLATED world -> chrome.runtime.sendMessage -> background.js
 */

const interceptorCode = `
(function() {
  'use strict';
  if (window.__OPS_LOGGER_INJECTED__) return;
  window.__OPS_LOGGER_INJECTED__ = true;

  function extractShops(obj) {
    var shops = [];
    var seen = {};
    function walk(o, depth) {
      if (!o || typeof o !== 'object' || depth > 8) return;
      if (Array.isArray(o)) { o.forEach(function(x) { walk(x, depth + 1); }); return; }
      var sid = o.shopId || o.restaurantId;
      var sname = o.shopName || o.restaurantName;
      if (sid && sname && !seen[sid]) {
        seen[sid] = true;
        shops.push({ shopId: String(sid), shopName: String(sname) });
      }
      try {
        Object.values(o).forEach(function(v) {
          if (v && typeof v === 'object') walk(v, depth + 1);
        });
      } catch(e) {}
    }
    walk(obj, 0);
    return shops;
  }

  function getShopIdFromUrl() {
    var m = location.href.match(/shop\\/(\\d+)/);
    return m ? m[1] : '';
  }

  function processApiResponse(responseText) {
    try {
      if (!responseText || responseText.length < 50) return;
      var data = JSON.parse(responseText);
      var shops = extractShops(data);
      if (shops.length > 0) {
        window.postMessage({ type: 'OPS_SHOP_CACHE_DATA', shops: shops }, '*');
      }
    } catch(e) {}
  }

  function shouldProcess(url) {
    return url && (url.indexOf('app-api.shop.ele.me') !== -1 || url.indexOf('meituan.com') !== -1);
  }

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this._opsUrl = url; this._opsMethod = method;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    var self = this;
    if (self._opsMethod === 'POST' && shouldProcess(self._opsUrl || '')) {
      self.addEventListener('load', function() {
        try { processApiResponse(self.responseText); } catch(e) {}
      });
    }
    return origSend.apply(this, arguments);
  };

  var origFetch = window.fetch;
  window.fetch = function(input, init) {
    var url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    var method = (init && init.method) || (typeof input === 'object' ? input.method : 'GET');
    return origFetch.apply(this, arguments).then(function(response) {
      if (method === 'POST' && shouldProcess(url)) {
        try { var c = response.clone(); c.text().then(function(t) { processApiResponse(t); }).catch(function(){}); } catch(e) {}
      }
      return response;
    });
  };

  function probeShopName() {
    var shopId = getShopIdFromUrl();
    var selectors = [
      '.shop-name', '.restaurant-name',
      '[class*="shopName"]', '[class*="shop-name"]',
      '.header-shop-name', '.sidebar-shop-name', 'title'
    ];
    for (var i = 0; i < selectors.length; i++) {
      try {
        var el = document.querySelector(selectors[i]);
        if (!el) continue;
        var text = selectors[i] === 'title' ? document.title : (el.textContent || el.innerText || '');
        text = text.replace(/\\s*[-\\u2013\\u2014|\\u00b7]\\s*(\\u997f\\u4e86\\u4e48|\\u7f8e\\u56e2|\\u5546\\u5bb6).*$/i, '').trim();
        var BAD = ['\\u6dd8\\u5b9d\\u95ea\\u8d2d\\u5546\\u5bb6\\u7248','\\u997f\\u4e86\\u4e48\\u5546\\u5bb6\\u7248','\\u7f8e\\u56e2\\u5916\\u5356\\u5546\\u5bb6\\u7248','\\u5546\\u5bb6\\u7248','\\u997f\\u4e86\\u4e48','\\u7f8e\\u56e2','melody',''];
        if (text.length > 1 && text.length < 60 && BAD.indexOf(text) === -1) {
          var sid = shopId || '';
          if (!sid && location.hostname.indexOf('meituan') !== -1) {
            var m = document.cookie.match(/wmPoiId=(\\d+)/); if (m) sid = m[1];
          }
          if (!sid && location.hostname.indexOf('ele.me') !== -1) {
            var m2 = document.cookie.match(/shopId=(\\d+)/); if (m2) sid = m2[1];
          }
          if (sid) {
            window.postMessage({type:'OPS_SHOP_CACHE_DATA', shops:[{shopId:String(sid), shopName:text}]}, '*');
          }
          return;
        }
      } catch(e) {}
    }
  }
  setTimeout(probeShopName, 2000);
  setTimeout(probeShopName, 5000);

  console.log('[OpsLogger] Shop interceptor active');
})();
`;

try {
  const script = document.createElement('script');
  script.textContent = interceptorCode;
  (document.head || document.documentElement).appendChild(script);
  script.remove();
} catch (e) {}

// ========== Message Bridge: MAIN world -> extension ==========

window.addEventListener('message', function(event) {
  if (event.source !== window || !event.data) return;
  if (event.data.type === 'OPS_SHOP_CACHE_DATA') {
    chrome.runtime.sendMessage({
      type: 'OPS_SHOP_CACHE',
      shops: event.data.shops || [],
    });
  }
});
