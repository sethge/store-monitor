/**
 * Content Script (ISOLATED world) - Injects API interceptor into page
 *
 * Strategy: Use <script> tag injection instead of manifest "world": "MAIN"
 * to avoid Tabbit crash. The injected code runs in MAIN world and intercepts
 * all XHR/fetch responses, extracting food/shop data from query APIs.
 *
 * Data flow: page MAIN world -> postMessage -> ISOLATED world -> chrome.runtime.sendMessage -> background.js
 */

// Inject the interceptor code via <script> tag
const interceptorCode = `
(function() {
  'use strict';
  if (window.__OPS_LOGGER_INJECTED__) return;
  window.__OPS_LOGGER_INJECTED__ = true;

  // ========== Data Extraction ==========

  function extractFoods(obj, shopId) {
    var foods = [];
    function walk(o, depth) {
      if (!o || typeof o !== 'object' || depth > 10) return;
      if (Array.isArray(o)) { o.forEach(function(x) { walk(x, depth + 1); }); return; }

      // Is this a food item?
      if ((o.itemId || o.id) && o.name && typeof o.name === 'string' && o.name.length > 1) {
        var f = {
          itemId: String(o.itemId || o.id || ''),
          itemGlobalId: String(o.itemGlobalId || o.globalId || ''),
          name: o.name || o.foodName || '',
          price: o.price || o.currentPrice || 0,
          image: o.imagePath || o.image || o.imageUrl || '',
          shopId: String(o.shopId || shopId || ''),
          description: o.description || o.desc || '',
          monthlySales: o.monthSale || o.monthlySales || o.recentSales || 0,
          isOnShelf: o.isOnShelf !== undefined ? o.isOnShelf : (o.onShelf !== undefined ? o.onShelf : true),
          categoryName: o._categoryName || '',
          specs: []
        };
        var specs = o.sfoodSpecs || o.specs || o.skuList || [];
        if (Array.isArray(specs)) {
          specs.forEach(function(s) {
            if (s && typeof s === 'object') {
              f.specs.push({
                id: String(s.id || s.specId || ''),
                name: s.name || s.specName || '',
                price: s.price || 0,
                stock: s.stock !== undefined ? s.stock : (s.leftNum !== undefined ? s.leftNum : -1)
              });
            }
          });
        }
        foods.push(f);
      }

      // Walk children
      try {
        var keys = Object.keys(o);
        for (var i = 0; i < keys.length; i++) {
          var v = o[keys[i]];
          if (v && typeof v === 'object') walk(v, depth + 1);
        }
      } catch(e) {}
    }

    // First annotate categories
    function annotateCats(o, catName) {
      if (!o || typeof o !== 'object') return;
      if (Array.isArray(o)) { o.forEach(function(x) { annotateCats(x, catName); }); return; }
      var cn = o.categoryName || o.name || catName || '';
      var fl = o.foodList || o.foods || o.itemList;
      if (fl && Array.isArray(fl)) {
        fl.forEach(function(f) { if (f && typeof f === 'object') f._categoryName = cn; });
      }
      var subs = o.childCategories || o.subCategories || o.children;
      if (subs && Array.isArray(subs)) {
        subs.forEach(function(s) { annotateCats(s, cn); });
      }
    }
    annotateCats(obj, '');

    walk(obj, 0);
    return foods;
  }

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

  // ========== Response Processing ==========

  function processApiResponse(responseText, requestUrl) {
    try {
      if (!responseText || responseText.length < 50) return;
      var data = JSON.parse(responseText);

      var shopId = getShopIdFromUrl();

      // Extract foods (from food list queries)
      var foods = extractFoods(data, shopId);
      if (foods.length > 0) {
        // Send in batches to avoid message size limits
        var batch = 50;
        for (var i = 0; i < foods.length; i += batch) {
          window.postMessage({
            type: 'OPS_FOOD_CACHE_DATA',
            foods: foods.slice(i, i + batch),
            source: 'api_response',
            apiUrl: (requestUrl || '').substring(0, 200)
          }, '*');
        }
      }

      // Extract shop info
      var shops = extractShops(data);
      if (shops.length > 0) {
        window.postMessage({
          type: 'OPS_SHOP_CACHE_DATA',
          shops: shops,
          source: 'api_response'
        }, '*');
      }
    } catch(e) {}
  }

  function shouldProcess(url) {
    // Only process ele.me and meituan API calls
    return url && (
      url.indexOf('app-api.shop.ele.me') !== -1 ||
      url.indexOf('waimai.meituan.com') !== -1 ||
      url.indexOf('epassport') === -1  // Skip login APIs
    ) && (
      url.indexOf('app-api.shop.ele.me') !== -1 ||
      url.indexOf('meituan.com') !== -1
    );
  }

  // ========== XHR Interception ==========

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url) {
    this._opsUrl = url;
    this._opsMethod = method;
    return origOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function(body) {
    var self = this;
    if (self._opsMethod === 'POST' && shouldProcess(self._opsUrl || '')) {
      self.addEventListener('load', function() {
        try {
          processApiResponse(self.responseText, self._opsUrl);
        } catch(e) {}
      });
    }
    return origSend.apply(this, arguments);
  };

  // ========== Fetch Interception ==========

  var origFetch = window.fetch;
  window.fetch = function(input, init) {
    var url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    var method = (init && init.method) || (typeof input === 'object' ? input.method : 'GET');

    return origFetch.apply(this, arguments).then(function(response) {
      if (method === 'POST' && shouldProcess(url)) {
        try {
          var clone = response.clone();
          clone.text().then(function(text) {
            processApiResponse(text, url);
          }).catch(function() {});
        } catch(e) {}
      }
      return response;
    });
  };

  // ========== 页面加载后主动读店铺名（饿了么/美团） ==========
  function probeShopName() {
    var shopId = getShopIdFromUrl();
    // 饿了么：从页面DOM读店铺名（header里的店铺选择器/标题）
    var selectors = [
      '.shop-name',                    // 常见class
      '.restaurant-name',
      '[class*="shopName"]',
      '[class*="shop-name"]',
      '.header-shop-name',
      '.sidebar-shop-name',
      'title'                          // 最后从document.title读
    ];
    for (var i = 0; i < selectors.length; i++) {
      try {
        var el = document.querySelector(selectors[i]);
        if (!el) continue;
        var text = selectors[i] === 'title' ? document.title : (el.textContent || el.innerText || '');
        text = text.replace(/\\s*[-–—|·]\\s*(饿了么|美团|商家).*$/i, '').trim();
        var BAD = ['淘宝闪购商家版','饿了么商家版','美团外卖商家版','商家版','饿了么','美团','melody',''];
        if (text.length > 1 && text.length < 60 && BAD.indexOf(text) === -1) {
          var sid = shopId || '';
          // 美团从cookie读wmPoiId
          if (!sid && location.hostname.indexOf('meituan') !== -1) {
            var m = document.cookie.match(/wmPoiId=(\\d+)/);
            if (m) sid = m[1];
          }
          // 饿了么从cookie或metas
          if (!sid && location.hostname.indexOf('ele.me') !== -1) {
            var m2 = document.cookie.match(/shopId=(\\d+)/);
            if (m2) sid = m2[1];
          }
          if (sid) {
            window.postMessage({type:'OPS_SHOP_CACHE_DATA', shops:[{shopId:String(sid), shopName:text}]}, '*');
            console.log('[OpsLogger] probed shop:', sid, text);
          }
          return;
        }
      } catch(e) {}
    }
  }
  // 延迟执行，等SPA渲染完
  setTimeout(probeShopName, 2000);
  setTimeout(probeShopName, 5000);

  console.log('[OpsLogger] API response interceptor active');
})();
`;

// Inject via <script> tag - this runs in MAIN world
try {
  const script = document.createElement('script');
  script.textContent = interceptorCode;
  (document.head || document.documentElement).appendChild(script);
  script.remove();  // Clean up DOM, code already executed
  console.log('[OpsLogger] Injector loaded (ISOLATED -> MAIN via script tag)');
} catch (e) {
  console.error('[OpsLogger] Injection failed:', e);
}

// ========== Message Bridge: MAIN world -> extension ==========

let foodBatchBuffer = [];
let foodBatchTimer = null;

window.addEventListener('message', function(event) {
  if (event.source !== window || !event.data) return;

  if (event.data.type === 'OPS_FOOD_CACHE_DATA') {
    // Buffer food cache messages and send in batch
    foodBatchBuffer = foodBatchBuffer.concat(event.data.foods || []);
    if (foodBatchTimer) clearTimeout(foodBatchTimer);
    foodBatchTimer = setTimeout(function() {
      if (foodBatchBuffer.length > 0) {
        chrome.runtime.sendMessage({
          type: 'OPS_FOOD_CACHE',
          foods: foodBatchBuffer,
          source: event.data.source || 'unknown'
        });
        console.log('[OpsLogger] Sent', foodBatchBuffer.length, 'foods to background');
        foodBatchBuffer = [];
      }
    }, 500);
  }

  if (event.data.type === 'OPS_SHOP_CACHE_DATA') {
    chrome.runtime.sendMessage({
      type: 'OPS_SHOP_CACHE',
      shops: event.data.shops || [],
      source: event.data.source || 'unknown'
    });
    console.log('[OpsLogger] Sent', (event.data.shops || []).length, 'shops to background');
  }
});
