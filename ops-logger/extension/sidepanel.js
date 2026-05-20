/* sidepanel.js — 小q助手 五Tab侧边栏 (巡店/预警/日志/复盘/会话) */

var SERVER_URL = '';

function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function fmtHM(ts) {
  try { var d = new Date(ts); return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0'); }
  catch(e) { return ''; }
}

function fmtDate(ts) {
  if (!ts) return '';
  var d = new Date(ts);
  var now = new Date();
  if (d.toDateString() === now.toDateString()) return '今天';
  var y = new Date(now); y.setDate(y.getDate()-1);
  if (d.toDateString() === y.toDateString()) return '昨天';
  return (d.getMonth()+1) + '月' + d.getDate() + '日';
}

function dateKey(ts) {
  if (!ts) return '';
  return new Date(ts).toISOString().slice(0,10);
}

// ========== Server discovery ==========

async function discoverServer() {
  try {
    var data = await chrome.storage.local.get('ops_server_url');
    if (data.ops_server_url) SERVER_URL = data.ops_server_url;
  } catch(e) {}
  if (!SERVER_URL) SERVER_URL = 'http://127.0.0.1:5500';
}

async function api(path) {
  if (!SERVER_URL) await discoverServer();
  try {
    var res = await fetch(SERVER_URL + path);
    if (res.ok) return await res.json();
  } catch(e) {}
  return null;
}

async function apiPost(path, body) {
  if (!SERVER_URL) await discoverServer();
  try {
    var res = await fetch(SERVER_URL + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (res.ok) return await res.json();
  } catch(e) {}
  return null;
}

// ========== Tab switching ==========

function initTabs() {
  var tabs = document.querySelectorAll('.tab');
  tabs.forEach(function(tab) {
    tab.addEventListener('click', function() {
      tabs.forEach(function(t) { t.classList.remove('active'); });
      tab.classList.add('active');
      document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });
}

// ========== Tab 1: Daily Report (巡店) ==========

async function loadDaily() {
  var el = document.getElementById('tab-daily');
  var data = await api('/api/daily');
  if (!data || !data.stores || data.stores.length === 0) {
    el.innerHTML = '<div class="empty">暂无巡检日报<br><span style="font-size:10px;color:#ccc">agent跑巡检后这里会显示结果</span></div>';
    return;
  }

  var html = '<div class="daily-meta">巡检时间: ' + esc(data.ts) + '</div>';
  for (var i = 0; i < data.stores.length; i++) {
    var store = data.stores[i];
    html += '<div class="store-card"><div class="store-name">' + esc(store.store) + '</div>';
    for (var j = 0; j < store.platforms.length; j++) {
      var p = store.platforms[j];
      html += '<div class="platform-section"><div class="platform-label">' + esc(p.platform) + '</div>';
      var hasIssue = false;
      if (p.bad_review_count > 0) {
        hasIssue = true;
        html += '<div class="issue-line red">差评 ' + p.bad_review_count + '条</div>';
        for (var k = 0; k < p.bad_reviews.length && k < 3; k++) {
          var r = p.bad_reviews[k];
          html += '<div class="review-detail">' + r.stars + '星 "' + esc((r.comment||'').substring(0,40)) + '"</div>';
        }
      }
      if (p.expiring_count > 0) {
        hasIssue = true;
        for (var k = 0; k < p.activities.length; k++) {
          var a = p.activities[k];
          var cls = (a.days_left || 99) <= 1 ? 'red' : 'yellow';
          html += '<div class="issue-line ' + cls + '">' + esc(a.name) + ' ' + a.days_left + '天后到期</div>';
        }
      }
      if (p.promo_balance !== null && p.promo_balance !== undefined) {
        var promoClass = 'green';
        var promoNote = '';
        if (p.promo_daily_spend && p.promo_daily_spend > 0) {
          var daysLeft = p.promo_balance / p.promo_daily_spend;
          if (daysLeft < 1) { promoClass = 'red'; promoNote = ' 今天可能用完'; }
          else if (daysLeft < 3) { promoClass = 'yellow'; promoNote = ' 预计' + daysLeft.toFixed(1) + '天用完'; }
        }
        if (promoClass !== 'green') {
          hasIssue = true;
          html += '<div class="issue-line ' + promoClass + '">推广余额 ¥' + p.promo_balance.toFixed(0) + promoNote + '</div>';
        }
      }
      if (p.has_auth_issue) { hasIssue = true; html += '<div class="issue-line red">授权异常</div>'; }
      if (!hasIssue) html += '<div class="issue-line green">无异常</div>';
      html += '</div>';
    }
    html += '</div>';
  }
  el.innerHTML = html;
}

// ========== Tab 2: Alerts (预警) ==========

async function loadAlerts() {
  var el = document.getElementById('tab-alerts');
  var data = await api('/api/alerts');
  if (!data || data.length === 0) {
    el.innerHTML = '<div class="empty">暂无预警</div>';
    updateBadge('alertBadge', 0);
    return;
  }
  var redCount = data.filter(function(a) { return a.level === 'red'; }).length;
  updateBadge('alertBadge', redCount);
  var html = '';
  for (var i = 0; i < data.length; i++) {
    var a = data[i];
    var pname = a.platform === 'eleme' ? '饿了么' : a.platform === 'meituan' ? '美团' : a.platform || '';
    html += '<div class="alert-item">' +
      '<div class="alert-dot ' + a.level + '"></div>' +
      '<div class="alert-body">' +
        '<div class="alert-msg">' + esc(a.msg) + '</div>' +
        (a.detail ? '<div class="alert-detail">' + esc(a.detail) + '</div>' : '') +
        '<div class="alert-store">' + esc(a.store) + (pname ? ' · ' + pname : '') + '</div>' +
      '</div></div>';
  }
  el.innerHTML = html;
}

// ========== Tab 3: Logs (日志) ==========

var trackingStatusMap = {};

async function loadTrackingStatus() {
  var data = await api('/api/tracking?limit=500');
  trackingStatusMap = {};
  if (data && data.length > 0) {
    for (var i = 0; i < data.length; i++) {
      var t = data[i];
      var prev = trackingStatusMap[t.log_id];
      if (!prev || t.status === 'pending') trackingStatusMap[t.log_id] = t.status;
    }
  }
}

async function loadLogs() {
  var el = document.getElementById('tab-logs');
  var data = await api('/api/logs?limit=50');
  if (!data || data.length === 0) {
    try {
      chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, function(state) {
        if (state && state.recentLogs && state.recentLogs.length > 0) {
          renderLogs(el, state.recentLogs);
        } else {
          el.innerHTML = '<div class="empty">还没有操作记录</div>';
        }
      });
    } catch(e) { el.innerHTML = '<div class="empty">还没有操作记录</div>'; }
    return;
  }
  await loadTrackingStatus();
  renderLogs(el, data);
}

function renderLogs(el, logs) {
  var byDate = {};
  for (var i = 0; i < logs.length; i++) {
    var dk = dateKey(logs[i].timestamp);
    if (!byDate[dk]) byDate[dk] = [];
    byDate[dk].push(logs[i]);
  }
  var html = '';
  var sortedDates = Object.keys(byDate).sort().reverse();
  for (var di = 0; di < sortedDates.length; di++) {
    var dk = sortedDates[di];
    var dayLogs = byDate[dk];
    html += '<div class="log-date">' + fmtDate(dayLogs[0].timestamp) + '</div>';
    for (var li = 0; li < dayLogs.length; li++) {
      var l = dayLogs[li];
      var sm = l.change_summary || l.action_detail || l.action_type || '';
      var pname = l.platform === 'eleme' ? '饿了么' : l.platform === 'meituan' ? '美团' : '';
      var shopStr = (l.shop_name || '') + (pname ? ' · ' + pname : '');
      var tagCls = actionTagClass(l.action_type);

      var logId = l.id;
      var tStatus = logId ? trackingStatusMap[logId] : null;
      var toggleHtml = '';
      if (logId && tStatus) {
        var isOn = tStatus !== 'disabled';
        toggleHtml = '<div class="toggle-wrap">' +
          '<button class="toggle-switch ' + (isOn ? 'on' : '') + '" data-logid="' + logId + '" data-enabled="' + (isOn ? '1' : '0') + '">' +
            '<span class="toggle-text on-text">复盘</span><span class="toggle-text off-text">关</span><span class="toggle-knob"></span>' +
          '</button></div>';
      }

      html += '<div class="log-item">' +
        '<div class="log-time">' + fmtHM(l.timestamp) + '</div>' +
        '<div class="log-body">' +
          '<div class="log-summary"><span class="tag ' + tagCls + '">' + esc(l.action_type || '操作') + '</span>' + esc(sm) + '</div>' +
          (shopStr ? '<div class="log-meta">' + esc(shopStr) + '</div>' : '') +
        '</div>' + toggleHtml + '</div>';
    }
  }
  el.innerHTML = html;

  el.querySelectorAll('.toggle-switch').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var logId = parseInt(btn.dataset.logid);
      var isOn = btn.dataset.enabled === '1';
      btn.classList.toggle('on');
      btn.dataset.enabled = isOn ? '0' : '1';
      toggleTracking(logId, !isOn);
    });
  });
}

function actionTagClass(t) {
  if (!t) return 'tag-gray';
  if (t.indexOf('下架') >= 0 || t.indexOf('删除') >= 0 || t.indexOf('关闭') >= 0) return 'tag-red';
  if (t.indexOf('上架') >= 0 || t.indexOf('新建') >= 0 || t.indexOf('创建') >= 0) return 'tag-green';
  if (t.indexOf('改价') >= 0 || t.indexOf('修改') >= 0 || t.indexOf('调整') >= 0 || t.indexOf('改') >= 0) return 'tag-yellow';
  if (t.indexOf('推广') >= 0) return 'tag-blue';
  return 'tag-gray';
}

// ========== Tab 4: Tracking (复盘) ==========

async function loadTracking() {
  var el = document.getElementById('tab-tracking');
  var allData = await api('/api/tracking?limit=200');
  var allItems = (allData || []).filter(function(t) { return t.status !== 'disabled'; });
  if (allItems.length === 0) {
    el.innerHTML = '<div class="empty">暂无复盘任务<br><span style="font-size:10px;color:#ccc">操作后台后自动创建T+3/T+7复盘</span></div>';
    updateBadge('trackBadge', 0);
    return;
  }

  var byLog = {}, logOrder = [];
  for (var i = 0; i < allItems.length; i++) {
    var t = allItems[i];
    var lid = t.log_id;
    if (!byLog[lid]) { byLog[lid] = { items: [], summary: '', shop: '', action: '' }; logOrder.push(lid); }
    byLog[lid].items.push(t);
    if (!byLog[lid].summary) byLog[lid].summary = t.change_summary || ((t.item_name || '') + ' ' + (t.action_type || t.log_action_type || ''));
    if (!byLog[lid].shop) byLog[lid].shop = t.shop_name || '';
    if (!byLog[lid].action) byLog[lid].action = t.action_type || t.log_action_type || '';
  }

  var today = new Date().toISOString().slice(0, 10);
  var dueCount = 0, html = '';

  for (var oi = 0; oi < logOrder.length; oi++) {
    var lid = logOrder[oi];
    var group = byLog[lid];
    var hasDue = group.items.some(function(x) { return x.status === 'pending' && x.check_date <= today; });
    if (hasDue) dueCount++;
    var tagCls = actionTagClass(group.action);
    var cardClass = hasDue ? 'review-card due' : 'review-card';
    var card = '<div class="' + cardClass + '">' +
      '<div class="review-title"><span class="tag ' + tagCls + '">' + esc(group.action) + '</span> ' + esc(group.summary) + '</div>' +
      '<div class="review-shop">' + esc(group.shop) + '</div><div class="review-timeline">';

    group.items.sort(function(a, b) { return (a.check_date || '').localeCompare(b.check_date || ''); });
    for (var ci = 0; ci < group.items.length; ci++) {
      var cp = group.items[ci];
      var cpLabel = cp.check_type === '3day' ? 'T+3' : cp.check_type === '7day' ? 'T+7' : cp.check_type;
      var cpClass = 'review-checkpoint';
      if (cp.status === 'done') cpClass += ' done';
      else if (cp.status === 'pending' && cp.check_date <= today) cpClass += ' due';
      else cpClass += ' active';

      card += '<div class="' + cpClass + '"><div class="cp-label">' + cpLabel + '</div><div class="cp-date">' + (cp.check_date || '') + '</div>';
      if (cp.status === 'done' && cp.metrics_after) card += '<div class="cp-summary">' + esc(cp.metrics_after) + '</div>';
      else if (cp.status === 'pending' && cp.check_date <= today) card += '<div class="cp-status">待生成</div>';
      else if (cp.status === 'pending') card += '<div class="cp-status waiting">等待中</div>';
      card += '</div>';
    }
    card += '</div></div>';
    html += card;
  }

  updateBadge('trackBadge', dueCount);
  el.innerHTML = html || '<div class="empty">暂无复盘任务</div>';
}

function toggleTracking(logId, enable) {
  var path = enable ? '/api/tracking/enable_log/' + logId : '/api/tracking/disable_log/' + logId;
  apiPost(path, {}).then(function() { loadTrackingStatus(); loadTracking(); });
}

// ========== Badge ==========

function updateBadge(elemId, count) {
  var el = document.getElementById(elemId);
  if (!el) return;
  if (count > 0) { el.textContent = count; el.style.display = 'inline-block'; }
  else { el.style.display = 'none'; }
}

// ========== Agent status + Patrol ==========

var agentReady = false;

async function checkAgent() {
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');
  var btn = document.getElementById('patrolBtn');

  var serverAlive = false;
  try { var res = await fetch(SERVER_URL + '/health', { signal: AbortSignal.timeout(3000) }); serverAlive = res.ok; } catch(e) {}
  if (!serverAlive) {
    dot.className = 'agent-dot off'; msg.textContent = '服务未启动'; btn.disabled = true;
    var hint = document.getElementById('startHint'); if (hint) hint.style.display = 'block';
    return;
  }
  var hint2 = document.getElementById('startHint'); if (hint2) hint2.style.display = 'none';

  var data = await api('/api/agent/status');
  if (!data) {
    dot.className = 'agent-dot ok'; msg.textContent = '服务已连接（无巡检）';
    btn.disabled = true; btn.style.display = 'none'; return;
  }
  btn.style.display = ''; agentReady = data.has_run_fast;
  if (data.patrol && data.patrol.state === 'running') {
    dot.className = 'agent-dot busy'; msg.textContent = data.patrol.message || '巡检中...';
    btn.disabled = true; btn.textContent = '巡检中'; setTimeout(checkAgent, 3000); return;
  }
  if (data.patrol && data.patrol.state === 'done') {
    dot.className = 'agent-dot ok'; msg.textContent = '巡检完成';
    btn.disabled = false; btn.textContent = '巡检'; loadDaily(); loadAlerts();
  } else if (data.patrol && data.patrol.state === 'error') {
    dot.className = 'agent-dot off'; msg.textContent = data.patrol.message || '巡检异常';
    btn.disabled = false; btn.textContent = '巡检';
  } else if (data.has_run_fast) {
    dot.className = 'agent-dot ok'; msg.textContent = 'agent就绪';
    btn.disabled = false; btn.textContent = '巡检';
  } else {
    dot.className = 'agent-dot ok'; msg.textContent = '服务已连接';
    btn.disabled = true; btn.style.display = 'none';
  }
}

async function startPatrol() {
  var btn = document.getElementById('patrolBtn');
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');
  var brandsData = await api('/api/patrol/brands');
  var brands = (brandsData && brandsData.brands) || [];
  if (!brands.length) {
    var input = prompt('输入巡检品牌（多个用逗号隔开）\n例如: 禾, 港翠');
    if (!input) return;
    brands = input.split(/[,，]/).map(function(s) { return s.trim(); }).filter(function(s) { return s; });
    if (!brands.length) return;
    await apiPost('/api/patrol/brands', { brands: brands });
  }
  btn.disabled = true; btn.textContent = '启动中...'; dot.className = 'agent-dot busy';
  var result = await apiPost('/api/patrol/start', { brands: brands });
  if (result && result.ok) {
    msg.textContent = result.message || '巡检已启动'; btn.textContent = '巡检中'; setTimeout(checkAgent, 2000);
  } else {
    msg.textContent = (result && result.message) || '启动失败';
    btn.disabled = false; btn.textContent = '巡检'; dot.className = 'agent-dot off';
  }
}

// ========== Version check ==========

async function checkVersion() {
  var manifest = chrome.runtime.getManifest();
  var currentVer = manifest.version;
  var verLabel = document.getElementById('verLabel');
  if (verLabel) verLabel.textContent = 'v' + currentVer;
  var data = await api('/api/extension/version');
  if (data && data.version && data.version !== currentVer) {
    var btn = document.getElementById('upgradeBtn');
    if (btn) {
      btn.style.display = 'inline-block';
      btn.textContent = 'v' + data.version + ' 可更新';
      btn.onclick = function() { btn.textContent = '更新中...'; chrome.runtime.sendMessage({ type: 'OPS_RELOAD' }); };
    }
  }
}

// ========== Settings ==========

async function loadSettings() {
  var data = await api('/api/settings');
  if (!data) {
    try { var stored = await chrome.storage.local.get('ops_settings'); data = stored.ops_settings || {}; } catch(e) { data = {}; }
  }
  if (data.patrol_enabled !== false) document.getElementById('patrolToggle').classList.add('on');
  if (data.alert_enabled !== false) document.getElementById('alertToggle').classList.add('on');
  if (data.patrol_time) document.getElementById('patrolTime').value = data.patrol_time;
  if (data.alert_interval) document.getElementById('alertInterval').value = data.alert_interval;
}

async function saveSettings() {
  var settings = {
    patrol_enabled: document.getElementById('patrolToggle').classList.contains('on'),
    alert_enabled: document.getElementById('alertToggle').classList.contains('on'),
    patrol_time: document.getElementById('patrolTime').value,
    alert_interval: parseInt(document.getElementById('alertInterval').value) || 30,
  };
  try { chrome.storage.local.set({ ops_settings: settings }); } catch(e) {}
  apiPost('/api/settings', settings);
}

function initSettings() {
  document.getElementById('settingsBtn').addEventListener('click', function() {
    document.getElementById('settingsPanel').classList.toggle('open');
  });
  ['patrolToggle', 'alertToggle'].forEach(function(id) {
    document.getElementById(id).addEventListener('click', function() { this.classList.toggle('on'); saveSettings(); });
  });
  ['patrolTime', 'alertInterval'].forEach(function(id) {
    document.getElementById(id).addEventListener('change', function() { saveSettings(); });
  });
  loadSettings();
}

// ========== Tab 5: Chat (会话) ==========

var chatHistory = [];
var isThinking = false;

function addChatMsg(role, content, extra) {
  var area = document.getElementById('chatArea');
  var welcome = document.getElementById('chatWelcome');
  if (welcome) welcome.style.display = 'none';

  var div = document.createElement('div');
  div.className = 'msg ' + role;
  if (role === 'bot' && extra) {
    div.innerHTML = formatChatMsg(content) + '<div class="tool-call">' + esc(extra) + '</div>';
  } else {
    div.innerHTML = formatChatMsg(content);
  }
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function formatChatMsg(text) {
  if (!text) return '';
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:12px;">$1</code>');
}

function showThinking() {
  var area = document.getElementById('chatArea');
  var div = document.createElement('div');
  div.className = 'thinking-indicator'; div.id = 'thinking';
  div.innerHTML = '<span></span><span></span><span></span>';
  area.appendChild(div); area.scrollTop = area.scrollHeight;
}
function hideThinking() { var el = document.getElementById('thinking'); if (el) el.remove(); }

function sendQuick(text) {
  document.getElementById('chatInput').value = text;
  sendMsg();
}

async function sendMsg() {
  var input = document.getElementById('chatInput');
  var text = input.value.trim();
  if (!text || isThinking) return;
  input.value = ''; input.style.height = 'auto';
  addChatMsg('user', text);

  var opData = await chrome.storage.local.get('ops_operator');
  var operator = opData.ops_operator || '';
  chatHistory.push({ role: 'user', content: text });

  isThinking = true;
  document.getElementById('sendBtn').disabled = true;
  showThinking();

  try {
    if (!SERVER_URL) await discoverServer();
    var res = await fetch(SERVER_URL + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, operator: operator, history: chatHistory.slice(-20) })
    });
    hideThinking();
    if (!res.ok) { addChatMsg('error', '服务出错: ' + res.status); }
    else {
      var data = await res.json();
      var reply = data.reply || '(没有回复)';
      var toolInfo = data.tools_used ? data.tools_used.join(' → ') : '';
      chatHistory.push({ role: 'assistant', content: reply });
      addChatMsg('bot', reply, toolInfo);
    }
  } catch(e) {
    hideThinking();
    addChatMsg('error', '无法连接服务: ' + e.message);
  }
  isThinking = false;
  document.getElementById('sendBtn').disabled = false;
}

// Auto-resize chat input
document.getElementById('chatInput').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

// ========== Init ==========

async function init() {
  chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, async function(state) {
    if (chrome.runtime.lastError || !state) { setTimeout(init, 300); return; }
    if (!state.operator) {
      document.getElementById('setup').style.display = '';
      document.getElementById('main').classList.remove('show');
      return;
    }
    document.getElementById('setup').style.display = 'none';

    document.getElementById('main').classList.add('show');
    document.getElementById('infoLine').textContent = state.operator;

    await discoverServer();
    checkVersion();
    checkAgent();
    loadDaily();
    loadAlerts();
    loadLogs();
    loadTracking();
  });
}

document.addEventListener('DOMContentLoaded', function() {
  initTabs();
  initSettings();
  init();

  var _pendingName = '';
  var _operatorsData = null;

  async function loadOperatorsData() {
    if (_operatorsData) return _operatorsData;
    try { var resp = await fetch(chrome.runtime.getURL('operators.json')); _operatorsData = await resp.json(); } catch(e) { _operatorsData = {}; }
    return _operatorsData;
  }

  document.getElementById('okBtn').addEventListener('click', async function() {
    var name = document.getElementById('nameInput').value.trim();
    if (!name) return;
    var resultEl = document.getElementById('setupResult');
    var confirmBtn = document.getElementById('confirmBtn');
    resultEl.innerHTML = '<div style="color:#999;text-align:center">查询中...</div>';
    confirmBtn.style.display = 'none';

    var ops = await loadOperatorsData();
    var brands = ops[name];
    if (!brands) {
      var allNames = Object.keys(ops);
      var similar = allNames.filter(function(n) { return n.indexOf(name) >= 0 || name.indexOf(n) >= 0; });
      var html = '<div style="color:#e65100;text-align:center">没有找到「' + esc(name) + '」</div>';
      if (similar.length > 0) html += '<div style="color:#999;text-align:center;margin-top:6px;font-size:11px">你是不是：' + similar.map(function(s){return esc(s)}).join('、') + '</div>';
      else if (allNames.length > 0) html += '<div style="color:#999;text-align:center;margin-top:6px;font-size:11px">现有运营：' + allNames.join('、') + '</div>';
      resultEl.innerHTML = html;
      return;
    }

    _pendingName = name;
    var brandNames = Object.keys(brands);
    var totalShops = 0;
    brandNames.forEach(function(b) { totalShops += brands[b].length; });
    var html = '<div style="color:#2e7d32;font-weight:600;margin-bottom:6px">' + esc(name) + ' — ' + brandNames.length + '个品牌 ' + totalShops + '家店</div>';
    for (var i = 0; i < brandNames.length; i++) {
      var bname = brandNames[i];
      var shops = brands[bname];
      html += '<div style="font-weight:600;margin-top:6px">' + esc(bname) + ' <span style="color:#999;font-weight:400">(' + shops.length + '家)</span></div>';
      for (var j = 0; j < shops.length; j++) {
        var s = shops[j];
        var ptag = s.p === 'meituan' ? '<span style="color:#cc6600">美团</span>' : '<span style="color:#0066cc">饿了么</span>';
        html += '<div style="padding-left:8px;color:#666">' + esc(s.shop) + ' ' + ptag + '</div>';
      }
    }
    resultEl.innerHTML = html;
    confirmBtn.style.display = 'block';
  });

  document.getElementById('confirmBtn').addEventListener('click', function() {
    if (!_pendingName) return;
    chrome.runtime.sendMessage({ type: 'OPS_SET_OPERATOR', name: _pendingName }, function() {
      if (!chrome.runtime.lastError) init();
    });
  });

  document.getElementById('nameInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('okBtn').click();
  });

  document.getElementById('patrolBtn').addEventListener('click', startPatrol);

  setInterval(function() { loadAlerts(); loadTracking(); checkAgent(); }, 30000);
});
