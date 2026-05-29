/**
 * Content Script (ISOLATED world) - v2操作日志DOM读取器
 *
 * 职责：接收background消息，按需从当前页面DOM读取：
 *   - 店名（页面头部固定位置）
 *   - 菜品名（根据上下文定位）
 *   - 当前状态快照（价格/库存/上下架）
 *
 * 运行在饿了么/美团后台页面，ISOLATED world，通过chrome.runtime通信
 */

(function() {
  'use strict';

  // ========== 平台检测 ==========
  function getPlatform() {
    var host = location.hostname;
    if (host.indexOf('meituan') !== -1) return 'meituan';
    if (host.indexOf('ele.me') !== -1) return 'eleme';
    return 'unknown';
  }

  // ========== 店名读取 ==========
  function readShopName() {
    var platform = getPlatform();

    if (platform === 'meituan') {
      // 美团：主frame span[class*=txt_]，父级 [class*=current-poi]
      var el = document.querySelector('[class*=current-poi] [class*=txt_]');
      if (el) {
        var t = el.textContent.trim();
        if (t.length > 1 && t.length < 60) return t;
      }
      // 备选：直接找 txt_ class
      el = document.querySelector('[class*=txt_]');
      if (el) {
        var t2 = el.textContent.trim();
        if (t2.length > 1 && t2.length < 60 && t2.indexOf('商家') === -1) return t2;
      }
    }

    if (platform === 'eleme') {
      // 饿了么：[class*=shopSwitcher]
      var el2 = document.querySelector('[class*=shopSwitcher]');
      if (el2) {
        var t3 = el2.textContent.trim();
        if (t3.length > 1 && t3.length < 60) return t3;
      }
    }

    // 通用兜底：从title拆分
    var parts = document.title.split(/\s*[-\u2013\u2014|]\s*/);
    if (parts.length >= 2) {
      for (var i = parts.length - 1; i >= 0; i--) {
        var p = parts[i].trim();
        var bad = ['\u6dd8\u5b9d\u95ea\u8d2d\u5546\u5bb6\u7248','\u997f\u4e86\u4e48\u5546\u5bb6\u7248','\u7f8e\u56e2\u5916\u5356\u5546\u5bb6\u7248','\u5546\u5bb6\u7248','\u997f\u4e86\u4e48','\u7f8e\u56e2','melody'];
        if (p.length > 1 && p.length < 40 && bad.indexOf(p) === -1) return p;
      }
    }

    return null;
  }

  // ========== 美团菜品读取 ==========
  function readMeituanFoods() {
    var foods = [];
    // 美团内容在iframe里，但content script如果注入到了内容frame就能直接读
    var cards = document.querySelectorAll('[class*=product-card]');
    cards.forEach(function(card) {
      var nameInput = card.querySelector('[class*=title] input');
      var nameH3 = card.querySelector('h3[class*=title]');
      var priceEl = card.querySelector('[class*=price-val]');
      var origPriceEl = card.querySelector('[class*=origin-price]');
      var salesEl = card.querySelector('[class*=sell-count]');
      var tagsEls = card.querySelectorAll('[class*=tag-group] li');

      var name = '';
      if (nameInput) name = nameInput.value || '';
      if (!name && nameH3) name = nameH3.getAttribute('title') || nameH3.textContent.trim();

      var tags = [];
      tagsEls.forEach(function(t) { tags.push(t.textContent.trim()); });

      var salesText = salesEl ? salesEl.textContent.trim() : '';
      var salesMatch = salesText.match(/\u6708\u552e\s*(\d+)/);
      var stockMatch = salesText.match(/\u5e93\u5b58\s*(\S+)/);

      foods.push({
        name: name,
        price: priceEl ? priceEl.textContent.trim().replace(/[^\d.]/g, '') : '',
        origPrice: origPriceEl ? origPriceEl.textContent.trim().replace(/[^\d.]/g, '') : '',
        monthlySales: salesMatch ? salesMatch[1] : '',
        stock: stockMatch ? stockMatch[1] : '',
        tags: tags
      });
    });
    return foods;
  }

  // ========== 饿了么菜品读取 ==========
  function readElemeFoods() {
    var foods = [];
    var rows = document.querySelectorAll('[class*=tableRowWithBorderContainer]');
    rows.forEach(function(row) {
      var nameEl = row.querySelector('[class*=goodsComNameDisplay] span');
      var priceEl = row.querySelector('[class*=price]');
      var salesEl = row.querySelector('[class*=goodsSales]');
      var stockEl = row.querySelector('[class*=stock]');

      var priceText = priceEl ? priceEl.textContent.trim() : '';
      var priceMatch = priceText.match(/[\d.]+/);

      var salesText = salesEl ? salesEl.textContent.trim() : '';
      var salesMatch = salesText.match(/\d+/);

      var stockText = stockEl ? stockEl.textContent.trim() : '';
      var stockMatch = stockText.match(/[\d\u65e0\u9650]+/);

      foods.push({
        name: nameEl ? nameEl.textContent.trim() : '',
        price: priceMatch ? priceMatch[0] : '',
        monthlySales: salesMatch ? salesMatch[0] : '',
        stock: stockMatch ? stockMatch[0] : '',
        tags: []
      });
    });
    return foods;
  }

  // ========== 读当前页面所有可见菜品 ==========
  function readVisibleFoods() {
    var platform = getPlatform();
    if (platform === 'meituan') return readMeituanFoods();
    if (platform === 'eleme') return readElemeFoods();
    return [];
  }

  // ========== 消息处理 ==========
  chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
    if (msg.type !== 'OPS_READ_DOM') return false;

    var action = msg.action || 'snapshot';
    var result = { platform: getPlatform(), url: location.href };

    if (action === 'snapshot' || action === 'before' || action === 'after') {
      result.shopName = readShopName();
      result.foods = readVisibleFoods();
      result.readAt = new Date().toISOString();
    }

    if (action === 'shopName') {
      result.shopName = readShopName();
    }

    sendResponse(result);
    return false;  // 同步响应
  });

  console.log('[OpsReader] content script loaded on', getPlatform(), location.href.substring(0, 60));
})();
