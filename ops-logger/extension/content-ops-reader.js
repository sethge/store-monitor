/**
 * Content Script (ISOLATED world) - v3 主动快照模式
 *
 * 设计思路（秘书原理）：
 *   秘书一直盯着屏幕，记住当前页面的样子。
 *   运营改了什么，秘书立刻知道"从什么变成什么"。
 *
 * 工作方式：
 *   1. 每3秒拍一次页面快照（表单值+列表数据）
 *   2. 记住"基线快照"（进入页面时的状态）和"上一次快照"
 *   3. API触发时，background来问diff → 返回精确的变化列表
 *
 * 覆盖场景：
 *   - 菜品改价/改名/上下架/删除（列表项变化）
 *   - CPC出价/预算修改（表单字段变化）
 *   - 活动创建/修改（表单字段变化）
 *   - 创建类操作（基线空→提交时有值）
 */

(function() {
  'use strict';

  var SNAPSHOT_INTERVAL = 3000;

  var _baselineUrl = '';
  var _baselineSnapshot = null;
  var _prevSnapshot = null;
  var _currSnapshot = null;

  // ========== 平台检测 ==========
  function getPlatform() {
    var host = location.hostname;
    if (host.indexOf('meituan') !== -1) return 'meituan';
    if (host.indexOf('ele.me') !== -1) return 'eleme';
    return 'unknown';
  }

  // ========== 页面类型检测 ==========
  function detectPageType() {
    var url = location.href.toLowerCase();
    var title = document.title || '';

    if (url.indexOf('food') !== -1 || url.indexOf('dish') !== -1 || url.indexOf('menu') !== -1 || url.indexOf('product') !== -1 || url.indexOf('goods') !== -1)
      return '菜品管理';
    if (url.indexOf('cpc') !== -1 || url.indexOf('promote') !== -1 || url.indexOf('bid') !== -1 || url.indexOf('advert') !== -1 || url.indexOf('tuiguang') !== -1)
      return '推广管理';
    if (url.indexOf('activity') !== -1 || url.indexOf('discount') !== -1 || url.indexOf('coupon') !== -1 || url.indexOf('fullreduce') !== -1 || url.indexOf('manjian') !== -1)
      return '活动管理';
    if (url.indexOf('comment') !== -1 || url.indexOf('review') !== -1 || url.indexOf('evaluate') !== -1 || url.indexOf('reply') !== -1)
      return '评价管理';
    if (url.indexOf('order') !== -1)
      return '订单管理';
    if (url.indexOf('shop') !== -1 || url.indexOf('store') !== -1 || url.indexOf('setting') !== -1 || url.indexOf('config') !== -1)
      return '店铺设置';
    if (url.indexOf('delivery') !== -1 || url.indexOf('peisong') !== -1 || url.indexOf('logistics') !== -1)
      return '配送设置';

    return '';
  }

  // ========== 店名读取 ==========
  function readShopName() {
    var platform = getPlatform();

    if (platform === 'meituan') {
      var el = document.querySelector('[class*=current-poi] [class*=txt_]');
      if (el) {
        var t = el.textContent.trim();
        if (t.length > 1 && t.length < 60) return t;
      }
      el = document.querySelector('[class*=txt_]');
      if (el) {
        var t2 = el.textContent.trim();
        if (t2.length > 1 && t2.length < 60 && t2.indexOf('\u5546\u5bb6') === -1) return t2;
      }
    }

    if (platform === 'eleme') {
      var el2 = document.querySelector('[class*=shopSwitcher]');
      if (el2) {
        var t3 = el2.textContent.trim();
        if (t3.length > 1 && t3.length < 60) return t3;
      }
    }

    var parts = document.title.split(/\s*[-\u2013\u2014|]\s*/);
    if (parts.length >= 2) {
      for (var i = parts.length - 1; i >= 0; i--) {
        var p = parts[i].trim();
        var bad = ['\u6dd8\u5b9d\u95ea\u8d2d\u5546\u5bb6\u7248','\u997f\u4e86\u4e48\u5546\u5bb6\u7248','\u7f8e\u56e2\u5916\u5356\u5546\u5bb6\u7248','\u5546\u5bb6\u7248','\u997f\u4e86\u4e48','\u7f8e\u56e2','melody',''];
        if (p.length > 1 && p.length < 40 && bad.indexOf(p) === -1) return p;
      }
    }

    return '';
  }

  // ========== 元素可见性 ==========
  function isVisible(el) {
    if (!el || !el.offsetParent && el.tagName !== 'BODY') return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  // ========== 字段标签提取 ==========
  function getFieldLabel(el) {
    // aria-label
    var al = el.getAttribute('aria-label');
    if (al && al.length < 30) return al.trim();
    // 关联label
    if (el.id) {
      var lbl = document.querySelector('label[for="' + el.id + '"]');
      if (lbl) { var lt = lbl.textContent.trim(); if (lt.length > 0 && lt.length < 30) return lt; }
    }
    // 父级label
    var parentLabel = el.closest('label');
    if (parentLabel) {
      var txt = '';
      for (var n = 0; n < parentLabel.childNodes.length; n++) {
        var node = parentLabel.childNodes[n];
        if (node.nodeType === 3) txt += node.textContent.trim();
      }
      if (txt.length > 0 && txt.length < 30) return txt;
    }
    // 前面的兄弟文字
    var prev = el.previousElementSibling;
    if (prev && prev.tagName !== 'INPUT' && prev.tagName !== 'SELECT') {
      var pt = prev.textContent.trim();
      if (pt.length > 0 && pt.length < 30) return pt;
    }
    // 父级中的第一段文字（表单项：label + input 在同一个div里）
    var parent = el.parentElement;
    if (parent) {
      for (var c = 0; c < parent.childNodes.length; c++) {
        var ch = parent.childNodes[c];
        if (ch === el) break;
        if (ch.nodeType === 3 && ch.textContent.trim()) return ch.textContent.trim().substring(0, 30);
        if (ch.nodeType === 1 && ch.tagName !== 'INPUT' && ch.tagName !== 'SELECT' && ch.tagName !== 'TEXTAREA') {
          var ct = ch.textContent.trim();
          if (ct.length > 0 && ct.length < 30) return ct;
        }
      }
    }
    // placeholder
    if (el.placeholder && el.placeholder.length < 30) return el.placeholder;
    // name
    if (el.name) return el.name;
    return null;
  }

  // ========== 表单字段读取 ==========
  function readFormFields() {
    var fields = {};

    // Input fields
    var inputs = document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file])');
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      if (!isVisible(el)) continue;
      var label = getFieldLabel(el);
      if (!label) continue;
      if (el.type === 'checkbox' || el.type === 'radio') {
        fields[label] = el.checked ? '\u5f00\u542f' : '\u5173\u95ed';
      } else {
        fields[label] = el.value || '';
      }
    }

    // Select fields
    var selects = document.querySelectorAll('select');
    for (var s = 0; s < selects.length; s++) {
      var sel = selects[s];
      if (!isVisible(sel)) continue;
      var slabel = getFieldLabel(sel);
      if (!slabel) continue;
      var opt = sel.options[sel.selectedIndex];
      fields[slabel] = opt ? opt.text.trim() : '';
    }

    // Textarea fields
    var tas = document.querySelectorAll('textarea');
    for (var t = 0; t < tas.length; t++) {
      var ta = tas[t];
      if (!isVisible(ta)) continue;
      var tlabel = getFieldLabel(ta);
      if (!tlabel) continue;
      fields[tlabel] = ta.value || '';
    }

    // Toggle/Switch controls
    var toggles = document.querySelectorAll('[class*=switch], [class*=toggle], [role=switch]');
    for (var g = 0; g < toggles.length; g++) {
      var tg = toggles[g];
      if (!isVisible(tg)) continue;
      var tgLabel = tg.getAttribute('aria-label') || '';
      if (!tgLabel) {
        var tgParent = tg.parentElement;
        if (tgParent) {
          for (var cn = 0; cn < tgParent.childNodes.length; cn++) {
            var cnode = tgParent.childNodes[cn];
            if (cnode === tg) break;
            var cnText = (cnode.textContent || '').trim();
            if (cnText.length > 0 && cnText.length < 20) { tgLabel = cnText; break; }
          }
        }
      }
      if (!tgLabel) continue;
      var isOn = tg.classList.contains('checked') || tg.classList.contains('on') ||
                 tg.classList.contains('is-checked') || tg.getAttribute('aria-checked') === 'true';
      fields[tgLabel] = isOn ? '\u5f00\u542f' : '\u5173\u95ed';
    }

    return fields;
  }

  // ========== 美团菜品列表读取 ==========
  function readMeituanItems() {
    var items = [];
    var cards = document.querySelectorAll('[class*=product-card]');
    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      var nameInput = card.querySelector('[class*=title] input');
      var nameH3 = card.querySelector('h3[class*=title]');
      var priceEl = card.querySelector('[class*=price-val]');
      var salesEl = card.querySelector('[class*=sell-count]');

      var name = '';
      if (nameInput) name = nameInput.value || '';
      if (!name && nameH3) name = nameH3.getAttribute('title') || nameH3.textContent.trim();
      if (!name) continue;

      var item = { name: name };
      if (priceEl) item['\u4ef7\u683c'] = priceEl.textContent.trim().replace(/[^\d.]/g, '');

      if (salesEl) {
        var text = salesEl.textContent.trim();
        var sm = text.match(/\u6708\u552e\s*(\d+)/);
        var km = text.match(/\u5e93\u5b58\s*(\S+)/);
        if (sm) item['\u6708\u552e'] = sm[1];
        if (km) item['\u5e93\u5b58'] = km[1];
      }

      // 上下架状态：查找切换按钮/标签
      var shelfEl = card.querySelector('[class*=status], [class*=shelf], [class*=switch]');
      if (shelfEl) {
        var st = shelfEl.textContent.trim();
        if (st.indexOf('\u4e0a\u67b6') !== -1 || st.indexOf('\u5728\u552e') !== -1) item['\u72b6\u6001'] = '\u4e0a\u67b6';
        else if (st.indexOf('\u4e0b\u67b6') !== -1 || st.indexOf('\u505c\u552e') !== -1) item['\u72b6\u6001'] = '\u4e0b\u67b6';
        else if (st) item['\u72b6\u6001'] = st;
      }

      items.push(item);
    }
    return items;
  }

  // ========== 饿了么菜品列表读取 ==========
  function readElemeItems() {
    var items = [];
    var rows = document.querySelectorAll('[class*=tableRowWithBorderContainer]');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var nameEl = row.querySelector('[class*=goodsComNameDisplay] span');
      var priceEl = row.querySelector('[class*=price]');
      var salesEl = row.querySelector('[class*=goodsSales]');
      var stockEl = row.querySelector('[class*=stock]');

      var name = nameEl ? nameEl.textContent.trim() : '';
      if (!name) continue;

      var item = { name: name };
      if (priceEl) item['\u4ef7\u683c'] = priceEl.textContent.trim().replace(/[^\d.]/g, '');
      if (salesEl) item['\u6708\u552e'] = salesEl.textContent.trim().replace(/[^\d]/g, '');
      if (stockEl) item['\u5e93\u5b58'] = stockEl.textContent.trim();

      // 上下架状态
      var shelfEl = row.querySelector('[class*=status], [class*=shelf], [class*=switch]');
      if (shelfEl) {
        var st = shelfEl.textContent.trim();
        if (st.indexOf('\u4e0a\u67b6') !== -1 || st.indexOf('\u5728\u552e') !== -1) item['\u72b6\u6001'] = '\u4e0a\u67b6';
        else if (st.indexOf('\u4e0b\u67b6') !== -1 || st.indexOf('\u505c\u552e') !== -1) item['\u72b6\u6001'] = '\u4e0b\u67b6';
        else if (st) item['\u72b6\u6001'] = st;
      }

      items.push(item);
    }
    return items;
  }

  // ========== 通用列表/表格读取 ==========
  function readGenericItems() {
    var items = [];
    var tables = document.querySelectorAll('table');
    for (var t = 0; t < tables.length; t++) {
      var table = tables[t];
      if (!isVisible(table)) continue;
      var headers = [];
      var ths = table.querySelectorAll('thead th, thead td');
      for (var h = 0; h < ths.length; h++) {
        headers.push(ths[h].textContent.trim());
      }
      if (headers.length < 2) continue;

      var trs = table.querySelectorAll('tbody tr');
      for (var r = 0; r < trs.length; r++) {
        var cells = trs[r].querySelectorAll('td');
        if (cells.length < 2) continue;
        var item = {};
        for (var c = 0; c < cells.length && c < headers.length; c++) {
          var val = cells[c].textContent.trim();
          if (val.length > 0 && val.length < 100) {
            item[headers[c] || ('\u5217' + (c + 1))] = val;
          }
        }
        if (Object.keys(item).length >= 2) {
          item.name = item[headers[0]] || cells[0].textContent.trim();
          items.push(item);
        }
      }
    }
    return items;
  }

  // ========== 读取页面项目 ==========
  function readPageItems() {
    var platform = getPlatform();
    if (platform === 'meituan') return readMeituanItems();
    if (platform === 'eleme') return readElemeItems();
    return readGenericItems();
  }

  // ========== 拍快照 ==========
  function takeSnapshot() {
    return {
      url: location.href,
      platform: getPlatform(),
      shopName: readShopName(),
      pageType: detectPageType(),
      timestamp: new Date().toISOString(),
      items: readPageItems(),
      forms: readFormFields()
    };
  }

  // ========== Diff两个快照 ==========
  function diffSnapshots(prev, curr) {
    if (!prev) return [];
    var changes = [];

    // --- Diff列表项（按name匹配）---
    var prevMap = {};
    var prevItems = prev.items || [];
    for (var i = 0; i < prevItems.length; i++) {
      if (prevItems[i].name) prevMap[prevItems[i].name] = prevItems[i];
    }

    var currItems = curr.items || [];
    var currMap = {};
    for (var j = 0; j < currItems.length; j++) {
      var ci = currItems[j];
      if (!ci.name) continue;
      currMap[ci.name] = ci;
      var old = prevMap[ci.name];
      if (!old) {
        // 新出现的项目（只在已有基线数据时报告，否则是首次加载）
        if (prevItems.length > 0) {
          changes.push({ target: ci.name, field: '\u65b0\u589e', from: '', to: '\u51fa\u73b0\u5728\u5217\u8868' });
        }
        continue;
      }
      // 比较每个字段
      var keys = Object.keys(ci);
      for (var k = 0; k < keys.length; k++) {
        var key = keys[k];
        if (key === 'name') continue;
        var oldVal = String(old[key] || '');
        var newVal = String(ci[key] || '');
        if (oldVal !== newVal && (oldVal || newVal)) {
          changes.push({ target: ci.name, field: key, from: oldVal, to: newVal });
        }
      }
    }

    // 消失的项目
    for (var pn in prevMap) {
      if (!currMap[pn]) {
        changes.push({ target: pn, field: '\u79fb\u9664', from: '\u5728\u5217\u8868', to: '' });
      }
    }

    // --- Diff表单字段 ---
    var allFormKeys = {};
    var prevForms = prev.forms || {};
    var currForms = curr.forms || {};
    var pf, cf;
    for (pf in prevForms) allFormKeys[pf] = true;
    for (cf in currForms) allFormKeys[cf] = true;

    for (var fk in allFormKeys) {
      var oldF = prevForms[fk] || '';
      var newF = currForms[fk] || '';
      if (oldF !== newF) {
        changes.push({ target: '', field: fk, from: oldF, to: newF });
      }
    }

    return changes;
  }

  // ========== 快照循环 ==========
  function tick() {
    var newSnapshot = takeSnapshot();

    // SPA导航检测：URL变了就重置基线
    if (location.href !== _baselineUrl) {
      _baselineUrl = location.href;
      _baselineSnapshot = newSnapshot;
    }

    _prevSnapshot = _currSnapshot;
    _currSnapshot = newSnapshot;
  }

  // 推送到background（只在有变化时）
  function pushIfChanged() {
    if (!_prevSnapshot || !_currSnapshot) return;
    if (_currSnapshot.items.length === 0 && Object.keys(_currSnapshot.forms).length === 0) return;

    // 简单比较：items和forms的JSON是否变化
    var prevStr = JSON.stringify(_prevSnapshot.items) + JSON.stringify(_prevSnapshot.forms);
    var currStr = JSON.stringify(_currSnapshot.items) + JSON.stringify(_currSnapshot.forms);
    if (prevStr === currStr) return;

    try {
      chrome.runtime.sendMessage({
        type: 'OPS_PAGE_STATE',
        current: _currSnapshot,
        previous: _prevSnapshot,
        baseline: _baselineSnapshot
      });
    } catch(e) {}
  }

  // ========== 事件级追踪（填补快照3秒盲区 + 不依赖选择器） ==========

  var _eventChanges = [];   // 事件捕捉到的精确变化
  var _focusValues = {};    // element标识 → focus时的值
  var _eventIdCounter = 0;

  // 给元素生成稳定标识（用于_focusValues的key）
  function elemKey(el) {
    if (!el) return '';
    if (el._opsKey) return el._opsKey;
    el._opsKey = '__ops_' + (++_eventIdCounter);
    return el._opsKey;
  }

  function isFormField(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName;
    if (tag === 'INPUT') {
      var t = (el.type || '').toLowerCase();
      return t !== 'hidden' && t !== 'submit' && t !== 'button' && t !== 'file';
    }
    return tag === 'SELECT' || tag === 'TEXTAREA' ||
           el.getAttribute('contenteditable') === 'true' ||
           el.getAttribute('role') === 'textbox' ||
           el.getAttribute('role') === 'spinbutton';
  }

  function getFieldValue(el) {
    if (!el) return '';
    if (el.tagName === 'SELECT') {
      var opt = el.options[el.selectedIndex];
      return opt ? opt.text.trim() : '';
    }
    if (el.getAttribute('contenteditable') === 'true' || el.getAttribute('role') === 'textbox') {
      return el.textContent.trim();
    }
    if (el.type === 'checkbox' || el.type === 'radio') {
      return el.checked ? '\u5f00\u542f' : '\u5173\u95ed';
    }
    return el.value || '';
  }

  // 从元素往上找所在行的"名字"（菜品名/项目名）
  function getRowContext(el) {
    if (!el) return '';
    var node = el;
    // 往上找到行容器
    for (var depth = 0; depth < 15 && node && node !== document.body; depth++) {
      node = node.parentElement;
      if (!node) break;

      // 美团菜品卡片
      if (node.className && node.className.indexOf('product-card') !== -1) {
        var inp = node.querySelector('[class*=title] input');
        var h3 = node.querySelector('h3[class*=title]');
        if (inp && inp.value) return inp.value;
        if (h3) return h3.getAttribute('title') || h3.textContent.trim();
      }
      // 饿了么菜品行
      if (node.className && node.className.indexOf('tableRowWithBorderContainer') !== -1) {
        var nameEl = node.querySelector('[class*=goodsComNameDisplay] span');
        if (nameEl) return nameEl.textContent.trim();
      }
      // 通用表格行
      if (node.tagName === 'TR') {
        var firstTd = node.querySelector('td');
        if (firstTd) {
          var t = firstTd.textContent.trim();
          if (t.length > 1 && t.length < 40) return t;
        }
      }
      // 带data-name或data-id的容器
      if (node.getAttribute('data-name')) return node.getAttribute('data-name');
      // 通用列表项
      if (node.className && (node.className.indexOf('item') !== -1 || node.className.indexOf('row') !== -1 || node.className.indexOf('card') !== -1)) {
        // 找第一个看起来像名字的文本
        var nameCandidate = node.querySelector('h3, h4, [class*=name], [class*=title], .name, .title');
        if (nameCandidate) {
          var ct = nameCandidate.textContent.trim();
          if (ct.length > 1 && ct.length < 40) return ct;
        }
      }
    }
    return '';
  }

  // 判断是否是操作按钮
  var ACTION_WORDS = ['\u4e0a\u67b6','\u4e0b\u67b6','\u5220\u9664','\u4fdd\u5b58','\u63d0\u4ea4','\u786e\u8ba4','\u53d6\u6d88',
    '\u542f\u7528','\u505c\u7528','\u7f16\u8f91','\u590d\u5236','\u65b0\u5efa','\u6dfb\u52a0','\u53d1\u5e03',
    '\u4e0b\u7ebf','\u4e0a\u7ebf','\u6392\u5e8f','\u79fb\u52a8','\u5e94\u7528','\u66f4\u65b0','\u8bbe\u7f6e',
    '\u5173\u95ed','\u6253\u5f00','\u5f00\u59cb','\u7ed3\u675f','\u64a4\u56de','\u5ba1\u6838','\u901a\u8fc7','\u62d2\u7edd',
    'submit','save','delete','confirm','apply','update','publish','remove','enable','disable'];

  function isActionButton(el) {
    if (!el) return null;
    // 从点击目标往上找button/a
    var node = el;
    for (var d = 0; d < 5 && node; d++) {
      if (node.tagName === 'BUTTON' || node.tagName === 'A' ||
          node.getAttribute('role') === 'button' ||
          (node.className && (node.className.indexOf('btn') !== -1 || node.className.indexOf('button') !== -1))) {
        var text = node.textContent.trim();
        if (text.length > 0 && text.length < 20) {
          var tl = text.toLowerCase();
          for (var i = 0; i < ACTION_WORDS.length; i++) {
            if (tl.indexOf(ACTION_WORDS[i]) !== -1) return { el: node, text: text };
          }
        }
      }
      node = node.parentElement;
    }
    return null;
  }

  // --- 事件监听 ---

  // Focus：记住进入时的值
  document.addEventListener('focusin', function(e) {
    var el = e.target;
    if (isFormField(el)) {
      _focusValues[elemKey(el)] = getFieldValue(el);
    }
  }, true);

  // Change：对比focus时的值，记录变化
  document.addEventListener('change', function(e) {
    var el = e.target;
    if (!isFormField(el)) return;
    var key = elemKey(el);
    var oldVal = _focusValues[key];
    if (oldVal === undefined) oldVal = '';
    var newVal = getFieldValue(el);
    if (oldVal === newVal) return;

    var label = getFieldLabel(el);
    var context = getRowContext(el);
    _eventChanges.push({
      target: context,
      field: label || el.name || el.type || '',
      from: oldVal,
      to: newVal,
      source: 'input',
      ts: Date.now()
    });
    // 更新focus值（连续编辑同一字段时用最新的）
    _focusValues[key] = newVal;
  }, true);

  // Input事件也监听（捕捉实时输入，不等blur）
  var _inputDebounce = {};
  document.addEventListener('input', function(e) {
    var el = e.target;
    if (!isFormField(el)) return;
    var key = elemKey(el);
    // 防抖：同一字段500ms内只记一次
    if (_inputDebounce[key]) clearTimeout(_inputDebounce[key]);
    _inputDebounce[key] = setTimeout(function() {
      var oldVal = _focusValues[key];
      if (oldVal === undefined) oldVal = '';
      var newVal = getFieldValue(el);
      if (oldVal === newVal) return;
      // 检查是否已有change事件记录了同样的变化
      var existing = _eventChanges.filter(function(c) {
        return c.source === 'input' && c.field === (getFieldLabel(el) || el.name) && c.ts > Date.now() - 1000;
      });
      if (existing.length > 0) return; // change事件已记录
      var label = getFieldLabel(el);
      var context = getRowContext(el);
      _eventChanges.push({
        target: context,
        field: label || el.name || '',
        from: oldVal,
        to: newVal,
        source: 'input',
        ts: Date.now()
      });
    }, 500);
  }, true);

  // Click：记录操作按钮点击
  document.addEventListener('click', function(e) {
    var btn = isActionButton(e.target);
    if (!btn) return;
    var context = getRowContext(btn.el);
    _eventChanges.push({
      target: context,
      field: '\u64cd\u4f5c',
      from: '',
      to: btn.text,
      source: 'click',
      ts: Date.now()
    });
  }, true);

  // ========== MutationObserver：监控class变化（开关/状态切换）==========

  var _observerActive = false;
  function startMutationObserver() {
    if (_observerActive) return;
    _observerActive = true;

    // 只观察class和aria属性变化（轻量级）
    var observer = new MutationObserver(function(mutations) {
      for (var m = 0; m < mutations.length; m++) {
        var mut = mutations[m];
        if (mut.type !== 'attributes') continue;
        var el = mut.target;

        // class变化 → 检查是否是开关切换
        if (mut.attributeName === 'class' || mut.attributeName === 'aria-checked') {
          if (!el.className || typeof el.className !== 'string') continue;
          var isSwitch = el.className.indexOf('switch') !== -1 || el.className.indexOf('toggle') !== -1 ||
                         el.getAttribute('role') === 'switch' || el.getAttribute('role') === 'checkbox';
          if (!isSwitch) continue;

          var oldClass = mut.oldValue || '';
          var newClass = el.className || '';
          var wasOn = oldClass.indexOf('checked') !== -1 || oldClass.indexOf(' on') !== -1 || oldClass.indexOf('is-checked') !== -1;
          var isOn = newClass.indexOf('checked') !== -1 || newClass.indexOf(' on') !== -1 || newClass.indexOf('is-checked') !== -1;
          if (wasOn === isOn) continue;

          var label = el.getAttribute('aria-label') || '';
          if (!label) {
            var p = el.parentElement;
            if (p) {
              for (var cn = 0; cn < p.childNodes.length; cn++) {
                var cnode = p.childNodes[cn];
                if (cnode === el) break;
                var cnText = (cnode.textContent || '').trim();
                if (cnText.length > 0 && cnText.length < 20) { label = cnText; break; }
              }
            }
          }
          if (!label) continue;

          var context = getRowContext(el);
          _eventChanges.push({
            target: context,
            field: label,
            from: wasOn ? '\u5f00\u542f' : '\u5173\u95ed',
            to: isOn ? '\u5f00\u542f' : '\u5173\u95ed',
            source: 'mutation',
            ts: Date.now()
          });
        }
      }
    });

    // 观察整个页面的属性变化（只看class和aria-checked）
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['class', 'aria-checked'],
      attributeOldValue: true,
      subtree: true
    });
  }

  // 延迟启动observer（等页面稳定）
  setTimeout(startMutationObserver, 2000);

  // ========== 清理过期事件（保留最近30秒）==========
  function cleanupEvents() {
    var cutoff = Date.now() - 30000;
    _eventChanges = _eventChanges.filter(function(c) { return c.ts > cutoff; });
  }

  // ========== 合并快照diff和事件变化 ==========
  function mergeChanges(snapshotChanges, eventChanges) {
    if (!eventChanges || eventChanges.length === 0) return snapshotChanges;
    if (!snapshotChanges || snapshotChanges.length === 0) return eventChanges.map(function(c) {
      return { target: c.target, field: c.field, from: c.from, to: c.to };
    });

    // 以事件变化为准（更精确），快照变化做补充
    var merged = [];
    var seen = {};

    // 先加事件变化
    for (var i = 0; i < eventChanges.length; i++) {
      var ec = eventChanges[i];
      var key = (ec.target || '') + '|' + (ec.field || '');
      if (!seen[key]) {
        seen[key] = true;
        merged.push({ target: ec.target, field: ec.field, from: ec.from, to: ec.to });
      }
    }

    // 再加快照里有但事件没捕到的变化
    for (var j = 0; j < snapshotChanges.length; j++) {
      var sc = snapshotChanges[j];
      var skey = (sc.target || '') + '|' + (sc.field || '');
      if (!seen[skey]) {
        seen[skey] = true;
        merged.push(sc);
      }
    }

    return merged;
  }

  // ========== 初始化 ==========
  _currSnapshot = takeSnapshot();
  _baselineUrl = location.href;
  _baselineSnapshot = _currSnapshot;

  setInterval(function() {
    tick();
    pushIfChanged();
    cleanupEvents();
  }, SNAPSHOT_INTERVAL);

  // ========== 消息处理 ==========
  chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
    if (msg.type === 'OPS_GET_DIFF') {
      // API触发了，拍一张最新快照
      var freshSnapshot = takeSnapshot();
      var snapshotChanges = diffSnapshots(_prevSnapshot, freshSnapshot);
      var fullSnapshotChanges = diffSnapshots(_baselineSnapshot, freshSnapshot);

      // 取最近10秒的事件变化（API触发前的操作）
      var cutoff = Date.now() - 10000;
      var recentEvents = _eventChanges.filter(function(c) { return c.ts > cutoff; });

      // 合并：事件优先，快照补充
      var recentChanges = mergeChanges(snapshotChanges, recentEvents);
      var fullChanges = mergeChanges(fullSnapshotChanges, recentEvents);

      var hasData = recentChanges.length > 0 || fullChanges.length > 0 ||
                    freshSnapshot.items.length > 0 || Object.keys(freshSnapshot.forms).length > 0;
      if (hasData) {
        sendResponse({
          changes: recentChanges,
          fullChanges: fullChanges,
          shopName: freshSnapshot.shopName,
          pageType: freshSnapshot.pageType,
          platform: freshSnapshot.platform,
          url: location.href,
          snapshot: { items: freshSnapshot.items, forms: freshSnapshot.forms }
        });
      }
      // 消费掉已上报的事件
      _eventChanges = [];
      return false;
    }

    // 向后兼容：OPS_READ_DOM
    if (msg.type === 'OPS_READ_DOM') {
      var result = { platform: getPlatform(), url: location.href };
      result.shopName = readShopName();
      result.foods = readPageItems();
      result.readAt = new Date().toISOString();
      sendResponse(result);
      return false;
    }

    return false;
  });

  console.log('[OpsReader] v3 active snapshot + event tracking on', getPlatform(), location.href.substring(0, 60));
})();
