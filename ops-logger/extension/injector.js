/**
 * Injector - 运行在主世界(MAIN)，拦截页面真实的fetch/XHR写请求
 * 通过 window.postMessage 把数据传给 bridge.js
 */
(function () {
  "use strict";

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
      if (body.includes("=")) {
        try {
          const obj = {};
          for (const pair of body.split("&")) {
            const [k, v] = pair.split("=");
            if (k) obj[decodeURIComponent(k)] = v ? decodeURIComponent(v) : "";
          }
          return obj;
        } catch {}
      }
      return body.slice(0, 2000);
    }
  }

  function sendLog(entry) {
    window.postMessage({ type: "__OPS_LOG__", data: entry }, "*");
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
