/**
 * Content script (MAIN world) - Intercept API responses to cache food + shop data
 */
(function() {
  'use strict';

  function extractFoods(obj) {
    const foods = [];
    function walk(o) {
      if (!o || typeof o !== 'object') return;
      if (Array.isArray(o)) { o.forEach(walk); return; }
      if ((o.itemId || o.id) && o.name && typeof o.name === 'string' && o.name.length > 1) {
        foods.push({
          itemId: String(o.itemId || o.id),
          itemGlobalId: String(o.itemGlobalId || o.globalId || ''),
          name: o.name || '',
          price: o.price || o.currentPrice || 0,
          shopId: o.shopId ? String(o.shopId) : '',
          specs: (o.sfoodSpecs || o.specs || []).map(function(s) {
            return { id: s.id, name: s.name || '', price: s.price, stock: s.stock };
          })
        });
      }
      try { Object.values(o).forEach(walk); } catch(e) {}
    }
    walk(obj);
    return foods;
  }

  function extractShopInfo(obj) {
    var shops = [];
    function walk(o) {
      if (!o || typeof o !== 'object') return;
      if (Array.isArray(o)) { o.forEach(walk); return; }
      if (o.shopId && (o.shopName || o.restaurantName)) {
        shops.push({ shopId: String(o.shopId), shopName: o.shopName || o.restaurantName });
      }
      if (o.shopId && o.name && typeof o.name === 'string' && !o.itemId && !o.itemGlobalId && o.name.length > 1) {
        shops.push({ shopId: String(o.shopId), shopName: o.name });
      }
      try { Object.values(o).forEach(walk); } catch(e) {}
    }
    walk(obj);
    return shops;
  }

  function processResponse(responseText, requestBody) {
    try {
      if (!responseText || responseText.length < 20) return;
      var data = JSON.parse(responseText);

      // Extract foods
      var foods = extractFoods(data);
      if (foods.length > 0) {
        window.postMessage({ type: 'OPS_FOOD_CACHE_DATA', foods: foods }, '*');
      }

      // Extract shop info
      var shops = extractShopInfo(data);
      if (shops.length > 0) {
        window.postMessage({ type: 'OPS_SHOP_CACHE_DATA', shops: shops }, '*');
      }
    } catch(e) {}
  }

  // Patch XMLHttpRequest
  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url) {
    this._opsMethod = method;
    return origOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function(body) {
    var self = this;
    if (self._opsMethod === 'POST') {
      self.addEventListener('load', function() {
        processResponse(self.responseText, body);
      });
    }
    return origSend.apply(this, arguments);
  };

  // Patch fetch
  var origFetch = window.fetch;
  window.fetch = async function(input, init) {
    var resp = await origFetch.apply(this, arguments);
    var method = (init && init.method) || (typeof input === 'object' ? input.method : 'GET');
    if (method === 'POST') {
      try {
        var clone = resp.clone();
        var text = await clone.text();
        processResponse(text, init && init.body);
      } catch(e) {}
    }
    return resp;
  };

  console.log('[OpsLogger] cache interceptor active');
})();
