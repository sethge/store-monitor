/**
 * Content script (ISOLATED world) - Bridge messages from page to extension
 */
window.addEventListener('message', function(event) {
  if (event.source !== window || !event.data) return;
  if (event.data.type === 'OPS_FOOD_CACHE_DATA') {
    chrome.runtime.sendMessage({ type: 'OPS_FOOD_CACHE', foods: event.data.foods });
  }
  if (event.data.type === 'OPS_SHOP_CACHE_DATA') {
    chrome.runtime.sendMessage({ type: 'OPS_SHOP_CACHE', shops: event.data.shops });
  }
});
