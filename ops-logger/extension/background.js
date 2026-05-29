/**
 * Ops Logger - Background Service Worker v2.1.0
 * - Full body (no truncation)
 * - Structured fields (shopId/Name, itemId/Name, before snapshot)
 * - Immediate push on capture (1s debounce)
 * - Auto-update: checks server version, reloads if newer
 */

const VERSION = "5.0.0";
const SERVER_URL = "http://127.0.0.1:5500";
const MAX_LOCAL_LOGS = 5000;
const LOG_RETENTION_DAYS = 7;
const CONFIG_REFRESH = 300000;
const UPDATE_CHECK_INTERVAL = 86400000; // 24h

// ========== Caches ==========
let foodCache = {};   // itemId/globalId -> {name, price, specs, shopId}
let shopCache = {};   // shopId -> shopName

// 启动时从storage恢复缓存（service worker重启不丢）
chrome.storage.local.get(["ops_shop_cache", "ops_food_cache"], (data) => {
  if (data.ops_shop_cache) {
    shopCache = data.ops_shop_cache;
    console.log("[OpsLogger] shopCache restored:", Object.keys(shopCache).length);
  }
  if (data.ops_food_cache) {
    foodCache = data.ops_food_cache;
    console.log("[OpsLogger] foodCache restored:", Object.keys(foodCache).length);
  }
});

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
  // 方法名本身以get/query/list/count/check/fetch/search/find开头的是查询，不是修改
  const methodName = l.includes('.') ? l.split('.').pop() : l;
  const QUERY_PREFIXES = ['get', 'query', 'list', 'count', 'check', 'fetch', 'search', 'find', 'load', 'pull', 'poll',
    'batchquery', 'batchget', 'batchfetch', 'batchcheck', 'batchlist', 'batchcount', 'batchfind', 'batchsearch', 'batchload'];
  if (QUERY_PREFIXES.some(p => methodName.startsWith(p))) return false;
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

// 异步补全shopId和shopName：body提取 → cookie wmPoiId → tab title
async function resolveShopName(entry, tabId, shopId) {
  // 1. body里有shopId且cache有名字，直接用
  if (shopId && shopCache[shopId]) {
    entry.shopName = shopCache[shopId];
    return;
  }
  // 2. body没shopId，从美团cookie读wmPoiId
  if (!shopId) {
    try {
      const c = await chrome.cookies.get({ url: 'https://e.waimai.meituan.com', name: 'wmPoiId' });
      if (c && c.value) {
        shopId = c.value;
        entry.shopId = shopId;
        if (shopCache[shopId]) {
          entry.shopName = shopCache[shopId];
          return;
        }
      }
    } catch(e) {}
  }
  // 3. 饿了么：从cookie读店铺名（SHOPNAME / shopName）
  if (!entry.shopName && entry.url && entry.url.includes('ele.me')) {
    for (const cname of ['SHOPNAME', 'shopName', 'SHOP_NAME']) {
      try {
        const c = await chrome.cookies.get({ url: 'https://melody.shop.ele.me', name: cname });
        if (c && c.value) {
          let decoded = c.value;
          try { decoded = decodeURIComponent(c.value); } catch(e) {}
          if (decoded.length > 1 && decoded.length < 60) {
            entry.shopName = decoded;
            if (shopId) {
              shopCache[shopId] = decoded;
              chrome.storage.local.set({ ops_shop_cache: shopCache });
            }
            break;
          }
        }
      } catch(e) {}
    }
  }
  // 3.5 饿了么：从页面DOM主动读店铺名（cookie拿不到时）
  if (!entry.shopName && tabId > 0 && entry.url && entry.url.includes('ele.me')) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          // 1) 常见DOM选择器
          const sels = [
            '.shop-name', '.shopName', '[class*="shopName"]',
            '[class*="shop-name"]', '[class*="storeName"]',
            '[class*="store-name"]', '.header-shop-name'
          ];
          for (const sel of sels) {
            const el = document.querySelector(sel);
            if (el && el.textContent.trim().length > 1 && el.textContent.trim().length < 40) {
              return el.textContent.trim();
            }
          }
          // 2) 从title提取：常见格式 "页面名 - 店铺名 - 饿了么商家版"
          const parts = document.title.split(/\s*[-–—|]\s*/);
          if (parts.length >= 3) {
            const mid = parts[parts.length - 2];
            if (mid && mid.length > 1 && mid.length < 30
                && !mid.includes('饿了么') && !mid.includes('商家')) {
              return mid;
            }
          }
          // 3) 从window状态对象找shopName
          try {
            const nd = window.__NEXT_DATA__ || window.__INITIAL_STATE__ || window.__APP_DATA__;
            if (nd) {
              const s = JSON.stringify(nd);
              const m = s.match(/"(?:shopName|restaurantName|storeName)"\s*:\s*"([^"]{2,30})"/);
              if (m) return m[1];
            }
          } catch(e) {}
          return null;
        }
      });
      if (results && results[0] && results[0].result) {
        entry.shopName = results[0].result;
        if (shopId) {
          shopCache[shopId] = results[0].result;
          chrome.storage.local.set({ ops_shop_cache: shopCache });
        }
      }
    } catch(e) {}
  }
  // 4. 从tab title兜底（尝试两次，第二次延迟500ms等SPA渲染完）
  if (!entry.shopName && tabId > 0) {
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) await new Promise(r => setTimeout(r, 500));
      try {
        const tab = await chrome.tabs.get(tabId);
        if (tab && tab.title && !tab.title.startsWith('http')) {
          let tName = tab.title.replace(/\s*[-–—|·]\s*(饿了么|美团|商家).*$/i, '').trim();
          const BAD_TITLES = ['淘宝闪购商家版', '饿了么商家版', '美团外卖商家版', '商家版', '饿了么', '美团', 'melody'];
          if (tName && tName.length > 1 && tName.length < 40 && !BAD_TITLES.includes(tName)) {
            entry.shopName = tName;
            if (shopId) {
              shopCache[shopId] = tName;
              chrome.storage.local.set({ ops_shop_cache: shopCache });
            }
            break;
          }
        }
      } catch(e) {}
    }
  }
}

// 缓存拿不到菜名时，从页面DOM读取
async function resolveItemName(entry, tabId) {
  if (entry.itemName || !entry.itemId || tabId <= 0) return;
  try {
    const itemIds = entry.itemId.split(',').map(s => s.trim()).filter(Boolean);
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (ids) => {
        // 饿了么/美团菜品管理页，菜名通常在列表项里
        // 策略1：找所有菜品名元素，匹配选中/高亮的
        var names = [];
        // 通用：找所有看起来像菜品名的元素
        var sels = [
          '[class*="food-name"]', '[class*="foodName"]', '[class*="item-name"]',
          '[class*="itemName"]', '[class*="dish-name"]', '[class*="goods-name"]',
          '.food-name', '.item-name', '.dish-name',
          'td.name', 'div.name', 'span.name'
        ];
        for (var i = 0; i < sels.length; i++) {
          var els = document.querySelectorAll(sels[i]);
          if (els.length > 0) {
            els.forEach(function(el) {
              var t = el.textContent.trim();
              if (t && t.length > 1 && t.length < 60) names.push(t);
            });
            if (names.length > 0) break;
          }
        }
        // 策略2：找被选中/checked的行里的文字
        if (names.length === 0) {
          var checked = document.querySelectorAll('tr.selected, tr.checked, [class*="selected"], [class*="checked"]');
          checked.forEach(function(row) {
            var t = row.querySelector('[class*="name"], td:nth-child(2), td:nth-child(3)');
            if (t && t.textContent.trim().length > 1) names.push(t.textContent.trim());
          });
        }
        return names.length > 0 ? names : null;
      },
      args: [itemIds]
    });
    if (results && results[0] && results[0].result) {
      var domNames = results[0].result;
      // 如果只有一个ID，取第一个DOM名字
      if (itemIds.length === 1 && domNames.length > 0) {
        entry.itemName = domNames[0];
        foodCache[itemIds[0]] = foodCache[itemIds[0]] || {};
        foodCache[itemIds[0]].name = domNames[0];
      } else if (domNames.length > 0) {
        entry.itemName = domNames.slice(0, itemIds.length).join(',');
      }
    }
  } catch(e) {}
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

// ========== v2: DOM读取 + 日志合并 ==========

async function sendDomRead(tabId, action) {
  // 向content script发消息读DOM，支持主frame和所有子frame
  if (!tabId || tabId <= 0) return null;
  try {
    // 先尝试直接发消息给tab（content script在all_frames里都有注入）
    const response = await chrome.tabs.sendMessage(tabId, {
      type: 'OPS_READ_DOM', action: action
    });
    if (response && (response.shopName || (response.foods && response.foods.length > 0))) {
      return response;
    }
  } catch(e) {
    // content script可能没加载（页面刚打开），用scripting.executeScript兜底
  }

  // 兜底：用chrome.scripting.executeScript注入一次性读取
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        // 简化版DOM读取（和content-ops-reader.js逻辑一致）
        var platform = location.hostname.indexOf('meituan') !== -1 ? 'meituan' :
                       location.hostname.indexOf('ele.me') !== -1 ? 'eleme' : 'unknown';
        var shopName = null;
        if (platform === 'meituan') {
          var el = document.querySelector('[class*=current-poi] [class*=txt_]') ||
                   document.querySelector('[class*=txt_]');
          if (el) { var t = el.textContent.trim(); if (t.length > 1 && t.length < 60) shopName = t; }
        } else if (platform === 'eleme') {
          var el2 = document.querySelector('[class*=shopSwitcher]');
          if (el2) { var t2 = el2.textContent.trim(); if (t2.length > 1 && t2.length < 60) shopName = t2; }
        }

        var foods = [];
        if (platform === 'meituan') {
          document.querySelectorAll('[class*=product-card]').forEach(function(card) {
            var inp = card.querySelector('[class*=title] input');
            var h3 = card.querySelector('h3[class*=title]');
            var price = card.querySelector('[class*=price-val]');
            var name = inp ? inp.value : (h3 ? (h3.getAttribute('title') || h3.textContent.trim()) : '');
            if (name) foods.push({ name: name, price: price ? price.textContent.trim().replace(/[^\d.]/g,'') : '' });
          });
        } else if (platform === 'eleme') {
          document.querySelectorAll('[class*=tableRowWithBorderContainer]').forEach(function(row) {
            var nameEl = row.querySelector('[class*=goodsComNameDisplay] span');
            var priceEl = row.querySelector('[class*=price]');
            if (nameEl) foods.push({
              name: nameEl.textContent.trim(),
              price: priceEl ? priceEl.textContent.trim().replace(/[^\d.]/g,'') : ''
            });
          });
        }

        if (!shopName && foods.length === 0) return null;
        return { platform: platform, shopName: shopName, foods: foods, url: location.href };
      }
    });
    // 合并所有frame的结果（取第一个有数据的）
    for (const r of results) {
      if (r.result && (r.result.shopName || (r.result.foods && r.result.foods.length > 0))) {
        return r.result;
      }
    }
  } catch(e) {}
  return null;
}

async function readDomAndSave(entry, tabId, shopId) {
  // 1. 读before快照（操作发生时的DOM状态）
  var domBefore = await sendDomRead(tabId, 'before');

  // 2. 从DOM补全店名
  if (domBefore && domBefore.shopName && !entry.shopName) {
    entry.shopName = domBefore.shopName;
    if (shopId) {
      shopCache[shopId] = domBefore.shopName;
      chrome.storage.local.set({ ops_shop_cache: shopCache });
    }
  }

  // 3. 从DOM补全菜名（如果body里没有）
  if (domBefore && domBefore.foods && domBefore.foods.length > 0 && !entry.itemName) {
    // 尝试通过itemId匹配DOM里的菜品名
    var domFoodNames = domBefore.foods.map(function(f) { return f.name; }).filter(Boolean);
    if (domFoodNames.length > 0) {
      // 如果只有一个菜品操作且DOM有数据，取第一个匹配的
      var ids = (entry.itemId || '').split(',').filter(Boolean);
      if (ids.length === 1 && domFoodNames.length > 0) {
        // 先查缓存名匹配
        var cached = foodCache[ids[0]];
        if (cached && cached.name) {
          var match = domFoodNames.find(function(n) { return n === cached.name; });
          if (match) entry.itemName = match;
        }
        // 缓存没匹配到，但DOM只有少量菜品（可能是当前操作的），就不强制赋值避免误匹配
      } else if (ids.length > 1) {
        // 多菜品操作，取DOM里所有名字
        entry.itemName = domFoodNames.slice(0, ids.length).join(',');
      }
    }
  }

  // 4. DOM没读到的，降级到原有逻辑（缓存+cookie+tab title）
  if (!entry.shopName) {
    await resolveShopName(entry, tabId, shopId);
  }
  if (!entry.itemName) {
    await resolveItemName(entry, tabId);
  }

  // 5. 保存before快照
  if (domBefore && domBefore.foods && domBefore.foods.length > 0) {
    entry.beforeSnapshot = JSON.stringify({
      source: 'dom',
      foods: domBefore.foods.slice(0, 20),
      readAt: domBefore.readAt || new Date().toISOString()
    });
  }

  // 6. 立刻保存日志（不等after，避免延迟）
  chrome.storage.local.get("ops_operator", (data) => {
    entry.operator = data.ops_operator || "";
    saveLog(entry);
  });

  // 7. 异步：等2秒读after快照，更新已保存的日志
  setTimeout(async function() {
    try {
      var domAfter = await sendDomRead(tabId, 'after');
      if (domAfter && domAfter.foods && domAfter.foods.length > 0) {
        entry.afterSnapshot = JSON.stringify({
          source: 'dom',
          foods: domAfter.foods.slice(0, 20),
          readAt: new Date().toISOString()
        });
        // 更新本地已保存的日志
        var data = await chrome.storage.local.get("ops_logs");
        var logs = data.ops_logs || [];
        // 找到刚保存的那条（最后一条匹配timestamp的）
        for (var i = logs.length - 1; i >= 0; i--) {
          if (logs[i].timestamp === entry.timestamp && logs[i].apiMethod === entry.apiMethod) {
            logs[i].afterSnapshot = entry.afterSnapshot;
            await chrome.storage.local.set({ ops_logs: logs });
            break;
          }
        }
      }
    } catch(e) {
      console.log("[OpsLogger] after snapshot failed:", e);
    }
  }, 2000);
}

// ========== Request capture ==========

// 去重：相同apiMethod+itemId在3秒内不重复记录
let _recentOps = {};
function isDuplicate(apiMethod, itemId) {
  var key = apiMethod + '|' + (itemId || '');
  var now = Date.now();
  if (_recentOps[key] && now - _recentOps[key] < 3000) return true;
  _recentOps[key] = now;
  // 清理过期key（避免内存泄漏）
  if (Object.keys(_recentOps).length > 100) {
    for (var k in _recentOps) {
      if (now - _recentOps[k] > 10000) delete _recentOps[k];
    }
  }
  return false;
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.method === "GET") return;
    if (isIgnoredUrl(details.url)) return;

    const body = parseRequestBody(details.requestBody);
    const apiMethod = extractApiMethod(details.url, body);
    if (isIgnoredApi(apiMethod)) return;
    if (!isMutationApi(apiMethod)) return;

    let shopId = extractShopId(body);
    const { itemId, itemName, beforeSnapshot } = extractItemInfo(body);

    // 去重：同一个操作3秒内不重复记
    if (isDuplicate(apiMethod, itemId)) {
      console.log("[OpsLogger] skip duplicate:", apiMethod, itemId);
      return;
    }

    const entry = {
      timestamp: new Date().toISOString(),
      method: details.method,
      url: details.url.slice(0, 500),
      apiMethod: apiMethod,
      body: body ? JSON.stringify(body) : null,
      shopId: shopId,
      shopName: '',
      itemId: itemId,
      itemName: itemName,
      beforeSnapshot: beforeSnapshot ? JSON.stringify(beforeSnapshot) : '',
      tab_id: details.tabId,
      pushed: false
    };

    // v2: 先通过content script读DOM拿before快照，立刻保存，after异步更新
    readDomAndSave(entry, details.tabId, shopId);
    debouncedPush();
    console.log("[OpsLogger]", apiMethod, shopId, itemName || itemId);
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
      console.log("[OpsLogger] pushed", result.saved, "/", unpushed.length, "logs");
      if (result.saved > 0) {
        // 服务端实际保存了，标记为已推送
        unpushed.forEach(l => l.pushed = true);
      } else {
        // 服务端全部过滤掉了（查询类API），直接丢弃这些无效日志
        const pushedIds = new Set(unpushed.map(l => l.timestamp));
        const cleaned = ops_logs.filter(l => !pushedIds.has(l.timestamp) || l.pushed);
        ops_logs.length = 0;
        cleaned.forEach(l => ops_logs.push(l));
      }
      await chrome.storage.local.set({ ops_logs });
      const remaining = ops_logs.filter(l => !l.pushed).length;
      chrome.action.setBadgeText({ text: remaining > 0 ? String(remaining) : "" });
      // 通知popup实时刷新操作日志
      chrome.runtime.sendMessage({ type: "OPS_LOGS_PUSHED", saved: result.saved }).catch(() => {});
    }
  } catch (e) {
    console.error("[OpsLogger] push error:", e.message);
  }
}

// Fallback periodic push (catches any missed)
setInterval(pushLogs, 60000);

// ========== Install / Update: 清理旧状态 ==========

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // 首次安装：全部清空，让运营重新输入身份
    chrome.storage.local.clear();
    chrome.action.setBadgeText({ text: '' });
    console.log('[OpsLogger] install -> cleared all state');
  } else if (details.reason === 'update') {
    // 更新：只清临时状态，保留 ops_operator / ops_shop_cache / ops_food_cache
    chrome.storage.local.remove([
      'ops_logs',
      'ops_update_available',
      'dismissed_alerts',
    ]);
    chrome.action.setBadgeText({ text: '' });
    console.log('[OpsLogger] update -> cleared stale state');
  }
});

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
  if (newFoods.length > 0) {
    syncCacheToServer("foods", newFoods);
    // 持久化foodCache，service worker重启后恢复
    chrome.storage.local.set({ ops_food_cache: foodCache });
  }
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
  if (newShops.length > 0) {
    syncCacheToServer("shops", newShops);
    // 持久化shopCache，service worker重启后恢复
    chrome.storage.local.set({ ops_shop_cache: shopCache });
  }
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
          var sid=o.shopId||o.restaurantId||o.storeId||o.poiId;
          var sn=o.shopName||o.restaurantName||o.storeName||o.poiName||o.shop_name||o.store_name;
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
    // 只计算实际预警（不含auth/error）
    const realAlerts = alerts.filter(a => a.type !== "auth" && a.type !== "error");
    const hasRed = realAlerts.some(a => a.level === "red");
    const alertCount = realAlerts.length;

    if (alertCount > 0) {
      chrome.action.setBadgeBackgroundColor({ color: hasRed ? "#c62828" : "#e65100" });
      chrome.action.setBadgeText({ text: String(alertCount) });
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
