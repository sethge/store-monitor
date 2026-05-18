/**
 * Ops Logger - Content Script
 * 注入到美团/饿了么商家后台页面，拦截所有写请求（POST/PUT/DELETE/PATCH）
 * 静默运行，运营零感知
 */
(function () {
  "use strict";

  // 埋点/静态资源等无关请求，直接跳过
  const IGNORE = [
    "/log/", "/track/", "/beacon/", "/analytics/", "/collect",
    "report.meituan.com", "sentry", "aegis", "arms-retcode",
    ".png", ".jpg", ".gif", ".css", ".woff", ".ttf",
    "/pv", "/webdfpid", "/fingerprint/", "/bio/info/report",
    "spiderindefence", "yoda_seed", "sdk_ver"
  ];

  const WRITE_METHODS = new Set(["POST", "PUT", "DELETE", "PATCH"]);

  function shouldCapture(url, method) {
    if (!WRITE_METHODS.has(method.toUpperCase())) return false;
    const lower = url.toLowerCase();
    for (const p of IGNORE) {
      if (lower.includes(p)) return false;
    }
    return true;
  }

  function detectPlatform(url) {
    if (url.includes("meituan.com")) return "meituan";
    if (url.includes("ele.me") || url.includes("eleme.cn")) return "eleme";
    return "other";
  }

  function extractPath(url) {
    try {
      const u = new URL(url);
      return u.pathname + u.search;
    } catch {
      return url;
    }
  }

  function safeParseBody(body) {
    if (!body) return null;
    if (typeof body !== "string") return String(body);
    try {
      return JSON.parse(body);
    } catch {
      // 可能是 form-urlencoded
      if (body.includes("=")) {
        try {
          const obj = {};
          for (const pair of body.split("&")) {
            const [k, v] = pair.split("=");
            if (k) obj[decodeURIComponent(k)] = v ? decodeURIComponent(v) : "";
          }
          return obj;
        } catch { /* fall through */ }
      }
      return body.slice(0, 2000); // 截断过长的原始字符串
    }
  }

  function sendLog(entry) {
    // 发给 background service worker 存储
    try {
      chrome.runtime.sendMessage({ type: "OPS_LOG", data: entry });
    } catch { /* 扩展被卸载或更新中，静默 */ }
  }

  function buildEntry(method, url, body) {
    return {
      timestamp: new Date().toISOString(),
      platform: detectPlatform(url),
      method: method.toUpperCase(),
      url: url,
      path: extractPath(url),
      body: safeParseBody(body),
      page_url: location.href,
      page_title: document.title
    };
  }

  // ---- 拦截 fetch ----
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const method = (init && init.method) || "GET";
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const fullUrl = url.startsWith("http") ? url : location.origin + url;

    if (shouldCapture(fullUrl, method)) {
      const body = init && init.body;
      let bodyStr = null;
      if (typeof body === "string") {
        bodyStr = body;
      } else if (body instanceof URLSearchParams) {
        bodyStr = body.toString();
      }
      // 对于其他类型(FormData, Blob等)，暂不解析
      sendLog(buildEntry(method, fullUrl, bodyStr));
    }

    return origFetch.apply(this, arguments);
  };

  // ---- 拦截 XMLHttpRequest ----
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    this._opsMethod = method;
    this._opsUrl = url;
    return origOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (body) {
    const method = this._opsMethod || "GET";
    const url = this._opsUrl || "";
    const fullUrl = url.startsWith("http") ? url : location.origin + url;

    if (shouldCapture(fullUrl, method)) {
      sendLog(buildEntry(method, fullUrl, body));
    }

    return origSend.apply(this, arguments);
  };
})();
