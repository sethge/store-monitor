/**
 * Bridge - 运行在隔离世界(ISOLATED)，监听主世界的postMessage
 * 转发给 background service worker 存储
 */
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (event.data && event.data.type === "__OPS_LOG__" && event.data.data) {
    try {
      chrome.runtime.sendMessage({ type: "OPS_LOG", data: event.data.data });
    } catch {}
  }
});
