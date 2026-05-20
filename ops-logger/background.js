/**
 * Ops Logger - Background Service Worker v2.1.0
 * - Full body (no truncation)
 * - Structured fields (shopId/Name, itemId/Name, before snapshot)
 * - Immediate push on capture (1s debounce)
 * - Auto-update: checks server version, reloads if newer
 */

const VERSION = "4.1.0";
const SERVER_URL = "http://127.0.0.1:5500";
const MAX_LOCAL_LOGS = 5000;
const LOG_RETENTION_DAYS = 7;
const CONFIG_REFRESH = 300000;
const UPDATE_CHECK_INTERVAL = 86400000; // 24h

// ========== Caches ==========
let foodCache = {};   // itemId/globalId -> {name, price, specs, shopId}
let shopCache = {};   // shopId -> shopName

// ========== Runtime config ==========
let ignoreApiMethods = new Set();
let ignoreApiPrefixes = [];
let ignoreUrls = [];

const FALLBACK_IGNORE = new Set([
  "HeadNoticeService.queryTabHeadNotice",
  "TraceService.trace",
  "PollingService.unprocessedOrders",
  "PollingService.abnormalOrders",
  "PollingService.nonCoreOrders",
  "PushService.polling",
  "IMChatService.getChatInfo",
  "IMChatService.getImInfo",
]);

async function discoverServer() {
  // v4.0.1: 直连本地server.py，不再从OSS拉远程地址
  // 清除旧的远程地址缓存
  chrome.storage.local.remove("ops_server_url");
  console.log("[OpsLogger] server:", SERVER_URL);
}

async function fetchConfig() {
  if (!SERVER_URL) await discoverServer();
  if (!SERVER_URL) return;
  try {
    const res = await fetch(SERVER_URL + "/api/config?t=" + Date.now());
    if (!res.ok) return;
    const cfg = await res.json();
    if (cfg.ignore_api_methods) ignoreApiMethods = new Set(cfg.ignore_api_methods);
    if (cfg.ignore_api_prefixes) ignoreApiPrefixes = cfg.ignore_api_prefixes;
    if (cfg.ignore_urls) ignoreUrls = cfg.ignore_urls;
    console.log("[OpsLogger] config loaded, rules:", ignoreApiMethods.size);
  } catch (e) {
    if (ignoreApiMethods.size === 0) ignoreApiMethods = FALLBACK_IGNORE;
  }
}

// ========== Auto-update (notify only, no auto-reload) ==========
async function checkForUpdate() {
  if (!SERVER_URL) return;
  try {
    const res = await fetch(SERVER_URL + "/api/extension/version?t=" + Date.now());
    if (!res.ok) return;
    const data = await res.json();
    if (data.version && data.version !== VERSION) {
      console.log("[OpsLogger] New version available:", VERSION, "->", data.version);
      chrome.storage.local.set({ ops_update_available: data.version });
    }
  } catch (e) {}
}

// ========== Mutation filter ==========
const MUTATION_KEYWORDS = [
  'update', 'create', 'add', 'delete', 'remove', 'save', 'submit',
  'modify', 'set', 'cancel', 'close', 'batch', 'edit', 'insert',
  'publish', 'offline', 'online', 'enable', 'disable', 'bind', 'unbind',
  'apply', 'confirm', 'reject', 'approve', 'revoke', 'upload', 'import',
  'adjust', 'reply', 'send', 'put', 'rename', 'sort', 'move',
  'copy', 'transfer', 'shelf', 'launch', 'stop', 'pause', 'resume'
];

function isMutationApi(m) {
  if (!m) return false;
  const l = m.toLowerCase();
  return MUTATION_KEYWORDS.some(kw => l.includes(kw));
}

function isIgnoredUrl(url) {
  const l = url.toLowerCase();
  for (const p of ignoreUrls) { if (l.includes(p)) return true; }
  return false;
}

function isIgnoredApi(m) {
  if (!m) return false;
  if (ignoreApiMethods.has(m)) return true;
  for (const p of ignoreApiPrefixes) { if (m.startsWith(p)) return true; }
  return false;
}

function parseRequestBody(rb) {
  if (!rb) return null;
  if (rb.raw && rb.raw.length > 0) {
    try {
      const decoder = new TextDecoder("utf-8");
      const raw = rb.raw.map(r => r.bytes ? decoder.decode(r.bytes) : "").join("");
      try { return JSON.parse(raw); } catch { return raw; }
    } catch { return "[binary]"; }
  }
  if (rb.formData) return rb.formData;
  return null;
}

function extractApiMethod(url, body) {
  const m1 = url.match(/[?&]method=([^&]+)/i) || url.match(/[?&]m=([^&]+)/i);
  if (m1) return m1[1];
  if (body && typeof body === 'object' && body.method) {
    return (body.service ? body.service + "." : "") + body.method;
  }
  const m2 = url.match(/\/xtop\/([^?]+)/);
  if (m2) return m2[1];
  return "";
}

// ========== Structured extraction ==========

function extractShopId(body) {
  if (!body || typeof body !== 'object') return '';
  if (body.metas && body.metas.shopId) return String(body.metas.shopId);
  const params = body.params;
  if (!params) return '';
  for (const k of Object.keys(params)) {
    const v = params[k];
    if (v && typeof v === 'object' && v.shopId) return String(v.shopId);
  }
  return '';
}

function extractItemInfo(body) {
  if (!body || typeof body !== 'object') return { itemId: '', itemName: '', beforeSnapshot: null };
  const params = body.params || {};

  // updateGoodsAttr
  if (params.updateGoodsAttr) {
    const attr = params.updateGoodsAttr;
    const itemId = String(attr.itemId || '');
    const cached = foodCache[itemId];
    return {
      itemId: itemId,
      itemName: attr.name || cached?.name || '',
      beforeSnapshot: cached || null
    };
  }

  // batchUpdateFood
  if (params.request && params.request.itemGlobalIds) {
    const ids = params.request.itemGlobalIds;
    const names = [];
    const befores = {};
    for (const gid of ids) {
      const cached = foodCache[gid];
      if (cached) {
        names.push(cached.name);
        befores[gid] = cached;
      }
    }
    return {
      itemId: ids.join(','),
      itemName: names.join(','),
      beforeSnapshot: Object.keys(befores).length > 0 ? befores : null
    };
  }

  // updateFood / generic
  if (params.food || params.request) {
    const food = params.food || params.request;
    if (food && typeof food === 'object') {
      const itemId = String(food.id || food.itemId || food.itemGlobalId || '');
      const cached = foodCache[itemId];
      return {
        itemId: itemId,
        itemName: food.name || food.foodName || cached?.name || '',
        beforeSnapshot: cached || null
      };
    }
  }

  return { itemId: '', itemName: '', beforeSnapshot: null };
}

// ========== Request capture ==========

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.method === "GET") return;
    if (isIgnoredUrl(details.url)) return;

    const body = parseRequestBody(details.requestBody);
    const apiMethod = extractApiMethod(details.url, body);
    if (isIgnoredApi(apiMethod)) return;
    if (!isMutationApi(apiMethod)) return;

    const shopId = extractShopId(body);
    const shopName = shopCache[shopId] || '';
    const { itemId, itemName, beforeSnapshot } = extractItemInfo(body);

    const entry = {
      timestamp: new Date().toISOString(),
      method: details.method,
      url: details.url.slice(0, 500),
      apiMethod: apiMethod,
      body: body ? JSON.stringify(body) : null,
      shopId: shopId,
      shopName: shopName,
      itemId: itemId,
      itemName: itemName,
      beforeSnapshot: beforeSnapshot ? JSON.stringify(beforeSnapshot) : '',
      tab_id: details.tabId,
      pushed: false
    };

    // 记录时就打上当前operator，换人不影响已有log
    chrome.storage.local.get("ops_operator", (data) => {
      entry.operator = data.ops_operator || "";
      saveLog(entry);
    });
    debouncedPush();
    console.log("[OpsLogger]", apiMethod, shopName || shopId, itemName || itemId);
  },
  {
    urls: [
      "*://*.waimai.meituan.com/*",
      "*://*.meituan.com/*",
      "*://*.ele.me/*",
      "*://*.eleme.cn/*",
      "*://*.koubei.com/*"
    ]
  },
  ["requestBody"]
);

// ========== Storage ==========

async function saveLog(entry) {
  try {
    const { ops_logs = [] } = await chrome.storage.local.get("ops_logs");
    ops_logs.push(entry);
    if (ops_logs.length > MAX_LOCAL_LOGS) {
      ops_logs.splice(0, ops_logs.length - MAX_LOCAL_LOGS);
    }
    await chrome.storage.local.set({ ops_logs });
    const unpushed = ops_logs.filter(l => !l.pushed).length;
    chrome.action.setBadgeBackgroundColor({ color: "#e94560" });
    chrome.action.setBadgeText({ text: String(unpushed) });
  } catch (e) {
    console.error("[OpsLogger] save failed:", e);
  }
}

// ========== Push (immediate with 1s debounce) ==========

let pushTimer = null;

function debouncedPush() {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(() => { pushTimer = null; pushLogs(); }, 1000);
}

async function pushLogs() {
  try {
    if (!SERVER_URL) await discoverServer();
    if (!SERVER_URL) return;
    const { ops_operator } = await chrome.storage.local.get("ops_operator");
    if (!ops_operator) return;

    const { ops_logs = [] } = await chrome.storage.local.get("ops_logs");
    const unpushed = ops_logs.filter(l => !l.pushed);
    if (unpushed.length === 0) return;

    // 用log自带的operator（记录时绑定），没有的fallback到当前operator
    unpushed.forEach(l => { if (!l.operator) l.operator = ops_operator; });

    const res = await fetch(SERVER_URL + "/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator: ops_operator, logs: unpushed })
    });

    if (res.ok) {
      const result = await res.json();
      console.log("[OpsLogger] pushed", result.saved, "logs");
      unpushed.forEach(l => l.pushed = true);
      await chrome.storage.local.set({ ops_logs });
      const remaining = ops_logs.filter(l => !l.pushed).length;
      chrome.action.setBadgeText({ text: remaining > 0 ? String(remaining) : "" });
    }
  } catch (e) {
    console.error("[OpsLogger] push error:", e.message);
  }
}

// Fallback periodic push (catches any missed)
setInterval(pushLogs, 60000);

// ========== Startup ==========

discoverServer().then(() => {
  fetchConfig();
  checkForUpdate();
  pushLogs();
});
setInterval(fetchConfig, CONFIG_REFRESH);
setInterval(discoverServer, 3600000);
setInterval(checkForUpdate, UPDATE_CHECK_INTERVAL);

// ========== Messages ==========

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "OPS_GET_STATE") {
    chrome.storage.local.get(["ops_operator", "ops_logs"], (data) => {
      const logs = data.ops_logs || [];
      sendResponse({
        version: VERSION,
        operator: data.ops_operator || "",
        logCount: logs.length,
        unpushed: logs.filter(l => !l.pushed).length,
        foodCacheSize: Object.keys(foodCache).length,
        shopCacheSize: Object.keys(shopCache).length,
        recentLogs: logs.slice(-30).reverse(),
      });
    });
    return true;
  }
  if (msg.type === "OPS_RELOAD") {
    chrome.runtime.reload();
    return;
  }
  if (msg.type === "OPS_SET_OPERATOR") {
    chrome.storage.local.set({ ops_operator: msg.name }, () => {
      sendResponse({ ok: true });
      pushLogs();
    });
    return true;
  }
  if (msg.type === "OPS_FOOD_CACHE") {
    processFoodCache(msg.foods);
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OPS_SHOP_CACHE") {
    processShopCache(msg.shops);
    sendResponse({ ok: true });
    return true;
  }
});

function processFoodCache(foods) {
  if (!Array.isArray(foods)) return;
  const newFoods = [];
  for (const f of foods) {
    const entry = {
      name: f.name || '', price: f.price || 0, shopId: f.shopId || '',
      specs: f.specs || [], image: f.image || '', description: f.description || '',
      monthlySales: f.monthlySales || 0, isOnShelf: f.isOnShelf,
      categoryName: f.categoryName || ''
    };
    if (f.itemId) {
      const key = String(f.itemId);
      if (!foodCache[key] || foodCache[key].name !== entry.name) newFoods.push({...entry, itemId: f.itemId, itemGlobalId: f.itemGlobalId || ''});
      foodCache[key] = entry;
    }
    if (f.itemGlobalId) {
      const key = String(f.itemGlobalId);
      if (!foodCache[key]) newFoods.push({...entry, itemId: f.itemId || '', itemGlobalId: f.itemGlobalId});
      foodCache[key] = entry;
    }
  }
  console.log("[OpsLogger] food cache:", Object.keys(foodCache).length, "new:", newFoods.length);
  // Sync to server
  if (newFoods.length > 0) syncCacheToServer("foods", newFoods);
}

function processShopCache(shops) {
  if (!Array.isArray(shops)) return;
  const newShops = [];
  for (const s of shops) {
    if (s.shopId && s.shopName) {
      const key = String(s.shopId);
      if (!shopCache[key] || shopCache[key] !== s.shopName) newShops.push(s);
      shopCache[key] = s.shopName;
    }
  }
  console.log("[OpsLogger] shop cache:", Object.keys(shopCache).length, "new:", newShops.length);
  if (newShops.length > 0) syncCacheToServer("shops", newShops);
}

async function syncCacheToServer(type, data) {
  if (!SERVER_URL) await discoverServer();
  if (!SERVER_URL) return;
  try {
    const res = await fetch(SERVER_URL + "/api/cache/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, data })
    });
    if (res.ok) {
      const result = await res.json();
      console.log("[OpsLogger] cache synced:", type, result.saved || 0);
    }
  } catch (e) {
    console.error("[OpsLogger] cache sync error:", e.message);
  }
}

// ========== Tab-based cache injection ==========
// Inject API response interceptor into ele.me/meituan pages
// Uses chrome.scripting.executeScript which bypasses CSP

const injectedTabs = new Set();

function injectCacheInterceptor(tabId) {
  if (injectedTabs.has(tabId)) return;

  // Inject MAIN world script to intercept XHR/fetch responses
  chrome.scripting.executeScript({
    target: { tabId: tabId, allFrames: true },
    world: "MAIN",
    func: function() {
      if (window.__OPS_LOGGER_INJECTED__) return;
      window.__OPS_LOGGER_INJECTED__ = true;

      function extractFoods(obj, shopId) {
        var foods = [];
        var seen = {};
        function walk(o, depth) {
          if (!o || typeof o !== 'object' || depth > 10) return;
          if (Array.isArray(o)) { o.forEach(function(x) { walk(x, depth+1); }); return; }
          var cn = o._cat || '';
          // Match ele.me food items: must have itemGlobalId or (itemId && name)
          var gid = o.itemGlobalId || o.globalId || '';
          var iid = o.itemId || o.vfoodId || o.id || '';
          var fname = o.name || o.foodName || '';
          if (gid && fname && fname.length > 1 && !seen[gid]) {
            seen[gid] = true;
            var specs = (o.sfoodSpecs || o.specs || o.skuList || []).filter(function(s){return s && typeof s==='object'});
            var price = 0;
            var parsedSpecs = specs.map(function(s){
              var sp = {id:String(s.id||s.specId||s.specGlobalId||''), name:s.name||s.specName||'', price:s.price||0, stock:s.stock!==undefined?s.stock:-1};
              if (sp.price && !price) price = sp.price;
              return sp;
            });
            if (!price) price = o.price || o.currentPrice || 0;
            foods.push({
              itemId: String(iid),
              itemGlobalId: String(gid),
              name: fname,
              price: price,
              image: o.imagePath || o.image || o.imageUrl || '',
              shopId: String(o.shopId || o.restaurantId || shopId || ''),
              description: o.description || o.desc || '',
              monthlySales: o.recentSales || o.monthSale || o.monthlySales || 0,
              isOnShelf: o.onShelf !== undefined ? o.onShelf : (o.isOnShelf !== undefined ? o.isOnShelf : true),
              categoryName: cn,
              specs: parsedSpecs
            });
          } else if (iid && fname && fname.length > 1 && !gid && !seen[iid]) {
            // Fallback for items without globalId
            seen[iid] = true;
            foods.push({
              itemId: String(iid), itemGlobalId: '',
              name: fname, price: o.price || 0,
              image: o.imageUrl || o.image || '',
              shopId: String(o.shopId || o.restaurantId || shopId || ''),
              description: '', monthlySales: o.recentSales || 0,
              isOnShelf: o.onShelf !== undefined ? o.onShelf : true,
              categoryName: cn, specs: []
            });
          }
          try { Object.keys(o).forEach(function(k) { var v=o[k]; if(v&&typeof v==='object') walk(v,depth+1); }); } catch(e){}
        }
        // Annotate categories
        function annCat(o, cn) {
          if (!o||typeof o!=='object') return;
          if (Array.isArray(o)) { o.forEach(function(x){annCat(x,cn);}); return; }
          var c = o.categoryName || o.name || cn || '';
          (o.foodList||o.foods||o.itemList||[]).forEach(function(f){if(f&&typeof f==='object')f._cat=c;});
          (o.childCategories||o.subCategories||o.children||[]).forEach(function(s){annCat(s,c);});
        }
        annCat(obj, '');
        walk(obj, 0);
        return foods;
      }

      function extractShops(obj) {
        var shops = [], seen = {};
        function walk(o, d) {
          if(!o||typeof o!=='object'||d>8) return;
          if(Array.isArray(o)){o.forEach(function(x){walk(x,d+1);});return;}
          var sid=o.shopId||o.restaurantId, sn=o.shopName||o.restaurantName;
          if(sid&&sn&&!seen[sid]){seen[sid]=true;shops.push({shopId:String(sid),shopName:String(sn)});}
          try{Object.values(o).forEach(function(v){if(v&&typeof v==='object')walk(v,d+1);});}catch(e){}
        }
        walk(obj, 0);
        return shops;
      }

      function getShopId() {
        var m = location.href.match(/shop\/(\d+)/);
        return m ? m[1] : '';
      }

      function processResponse(text, url) {
        try {
          if (!text || text.length < 50) return;
          var data = JSON.parse(text);
          var sid = getShopId();
          var foods = extractFoods(data, sid);
          if (foods.length > 0) {
            window.postMessage({type:'OPS_FOOD_CACHE_DATA', foods:foods, url:(url||'').substring(0,200)}, '*');
          }
          var shops = extractShops(data);
          if (shops.length > 0) {
            window.postMessage({type:'OPS_SHOP_CACHE_DATA', shops:shops}, '*');
          }
        } catch(e) {}
      }

      function shouldProcess(url) {
        return url && (url.indexOf('app-api.shop.ele.me')!==-1 || url.indexOf('meituan.com')!==-1);
      }

      // Intercept XHR
      var oOpen = XMLHttpRequest.prototype.open;
      var oSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function(m,u) { this._ou=u; this._om=m; return oOpen.apply(this,arguments); };
      XMLHttpRequest.prototype.send = function(b) {
        var self=this;
        if(self._om==='POST'&&shouldProcess(self._ou||'')) {
          self.addEventListener('load',function(){try{processResponse(self.responseText,self._ou);}catch(e){}});
        }
        return oSend.apply(this,arguments);
      };

      // Intercept fetch
      var oFetch = window.fetch;
      window.fetch = function(input, init) {
        var url = typeof input==='string' ? input : (input&&input.url?input.url:'');
        var method = (init&&init.method)||(typeof input==='object'?input.method:'GET');
        return oFetch.apply(this,arguments).then(function(resp) {
          if(method==='POST'&&shouldProcess(url)) {
            try{var c=resp.clone();c.text().then(function(t){processResponse(t,url);}).catch(function(){});}catch(e){}
          }
          return resp;
        });
      };
      console.log('[OpsLogger] MAIN world interceptor active');
    }
  }).catch(e => console.log("[OpsLogger] MAIN inject error:", e.message));

  // Inject ISOLATED world bridge to relay postMessage to extension
  chrome.scripting.executeScript({
    target: { tabId: tabId, allFrames: true },
    func: function() {
      if (window.__OPS_BRIDGE__) return;
      window.__OPS_BRIDGE__ = true;
      window.addEventListener('message', function(event) {
        if (event.source !== window || !event.data) return;
        if (event.data.type === 'OPS_FOOD_CACHE_DATA') {
          chrome.runtime.sendMessage({type:'OPS_FOOD_CACHE', foods:event.data.foods});
        }
        if (event.data.type === 'OPS_SHOP_CACHE_DATA') {
          chrome.runtime.sendMessage({type:'OPS_SHOP_CACHE', shops:event.data.shops});
        }
      });
      console.log('[OpsLogger] Bridge active');
    }
  }).catch(e => console.log("[OpsLogger] bridge inject error:", e.message));

  injectedTabs.add(tabId);
  console.log("[OpsLogger] injected cache interceptor into tab", tabId);
}

// Inject on tab updates (page loads)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    if (tab.url.includes('ele.me') || tab.url.includes('meituan.com')) {
      // Re-inject on each page load (SPA might recreate contexts)
      injectedTabs.delete(tabId);
      injectCacheInterceptor(tabId);
    }
  }
});

// Clean up closed tabs
chrome.tabs.onRemoved.addListener((tabId) => {
  injectedTabs.delete(tabId);
});

// Inject into existing tabs on startup
chrome.tabs.query({ url: ["*://*.ele.me/*", "*://*.meituan.com/*"] }, (tabs) => {
  for (const tab of tabs) {
    injectCacheInterceptor(tab.id);
  }
});

// Auto-cleanup: remove logs older than 7 days
function cleanupOldLogs() {
  chrome.storage.local.get("ops_logs", (data) => {
    const logs = data.ops_logs || [];
    const cutoff = Date.now() - LOG_RETENTION_DAYS * 86400000;
    const kept = logs.filter(l => {
      try { return new Date(l.timestamp).getTime() > cutoff; } catch(e) { return true; }
    });
    if (kept.length < logs.length) {
      chrome.storage.local.set({ ops_logs: kept });
      console.log("[OpsLogger] cleanup: removed", logs.length - kept.length, "old logs, kept", kept.length);
    }
  });
}
cleanupOldLogs();
setInterval(cleanupOldLogs, 3600000); // check every hour

// ========== Alert polling ==========
// Check server for alerts and update badge

async function pollAlerts() {
  if (!SERVER_URL) return;
  try {
    const res = await fetch(SERVER_URL + "/api/alerts?t=" + Date.now());
    if (!res.ok) return;
    const alerts = await res.json();
    const redCount = alerts.filter(a => a.level === "red").length;
    const totalCount = alerts.length;

    if (redCount > 0) {
      chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
      chrome.action.setBadgeText({ text: String(redCount) });
    } else if (totalCount > 0) {
      chrome.action.setBadgeBackgroundColor({ color: "#e65100" });
      chrome.action.setBadgeText({ text: String(totalCount) });
    } else {
      // Check for unpushed logs
      const { ops_logs = [] } = await chrome.storage.local.get("ops_logs");
      const unpushed = ops_logs.filter(l => !l.pushed).length;
      if (unpushed > 0) {
        chrome.action.setBadgeBackgroundColor({ color: "#e94560" });
        chrome.action.setBadgeText({ text: String(unpushed) });
      } else {
        chrome.action.setBadgeText({ text: "" });
      }
    }
  } catch (e) {
    // Server unreachable, fall back to unpushed count
    try {
      const { ops_logs = [] } = await chrome.storage.local.get("ops_logs");
      const unpushed = ops_logs.filter(l => !l.pushed).length;
      if (unpushed > 0) {
        chrome.action.setBadgeBackgroundColor({ color: "#e94560" });
        chrome.action.setBadgeText({ text: String(unpushed) });
      }
    } catch(e2) {}
  }
}

// Poll alerts every 2 minutes
setInterval(pollAlerts, 120000);

// Startup: init badge
chrome.storage.local.get("ops_logs", (data) => {
  const unpushed = (data.ops_logs || []).filter(l => !l.pushed).length;
  if (unpushed > 0) {
    chrome.action.setBadgeBackgroundColor({ color: "#e94560" });
    chrome.action.setBadgeText({ text: String(unpushed) });
  }
  // Delayed first poll (wait for server discovery)
  setTimeout(pollAlerts, 5000);
});
