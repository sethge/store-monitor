/* popup.js — 小q助手 三Tab面板 */

var SERVER_URL = 'http://127.0.0.1:5500';
var MY_SHOPS = []; // 当前运营名下的店铺名列表

function esc(s) { return (s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

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
  // v4.0.1: 直连本地，不读storage缓存
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

// ========== Tab 1: 巡店/预警 ==========

async function loadDaily() {
  var el = document.getElementById('dailySection');
  var data = await api('/api/daily');
  if (!data || !data.stores || data.stores.length === 0) {
    el.innerHTML = '';
    return;
  }

  var html = '<div class="section-title">巡检结果</div>';
  html += '<div class="daily-meta">巡检时间: ' + esc(data.ts) + '</div>';

  for (var i = 0; i < data.stores.length; i++) {
    var store = data.stores[i];
    html += '<div class="store-card"><div class="store-name">' + esc(store.store) + '</div>';

    for (var j = 0; j < store.platforms.length; j++) {
      var p = store.platforms[j];
      html += '<div class="platform-section">';
      html += '<div class="platform-label">' + esc(p.platform) + '</div>';

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

      if (p.has_auth_issue) {
        hasIssue = true;
        html += '<div class="issue-line red">授权异常</div>';
      }

      if (p.notice_count > 0) {
        hasIssue = true;
        html += '<div class="issue-line blue">' + p.notice_count + '条通知</div>';
        for (var k = 0; k < (p.notices || []).length && k < 3; k++) {
          var n = p.notices[k];
          html += '<div class="review-detail">' + esc(n.title) + '</div>';
        }
      }

      if ((p.errors || []).length > 0) {
        hasIssue = true;
        for (var k = 0; k < p.errors.length; k++) {
          html += '<div class="issue-line yellow">' + esc(p.errors[k]) + '</div>';
        }
      }

      if (!hasIssue) {
        html += '<div class="issue-line green">正常</div>';
      }

      html += '</div>';
    }
    html += '</div>';
  }

  el.innerHTML = html;
}

async function loadAlerts() {
  var el = document.getElementById('alertsSection');
  var data = await api('/api/alerts');
  if (!data || data.length === 0) {
    el.innerHTML = '';
    updateBadge('alertBadge', 0);
    // 如果巡检也没数据，显示空状态
    var dailyEl = document.getElementById('dailySection');
    if (!dailyEl.innerHTML) {
      dailyEl.innerHTML = '<div class="empty">暂无巡检和预警<br><span style="font-size:10px;color:#ccc">agent跑巡检后这里会显示结果</span></div>';
    }
    return;
  }

  var redCount = data.filter(function(a) { return a.level === 'red'; }).length;
  updateBadge('alertBadge', redCount);

  var html = '<div class="section-title">预警</div>';
  for (var i = 0; i < data.length; i++) {
    var a = data[i];
    var pname = a.platform === 'eleme' ? '饿了么' : a.platform === 'meituan' ? '美团' : a.platform || '';
    html += '<div class="alert-item">' +
      '<div class="alert-dot ' + a.level + '"></div>' +
      '<div class="alert-body">' +
        '<div class="alert-msg">' + esc(a.msg) + '</div>' +
        (a.detail ? '<div class="alert-detail">' + esc(a.detail) + '</div>' : '') +
        '<div class="alert-store">' + esc(a.store) + (pname ? ' · ' + pname : '') + '</div>' +
      '</div>' +
    '</div>';
  }
  el.innerHTML = html;
}

// ========== Tab 2: 调整/复盘 ==========

var trackingStatusMap = {};
var trackingByLogId = {};

function actionTagClass(t) {
  if (!t) return 'tag-gray';
  if (t.indexOf('下架') >= 0 || t.indexOf('删除') >= 0 || t.indexOf('关闭') >= 0) return 'tag-red';
  if (t.indexOf('上架') >= 0 || t.indexOf('新建') >= 0 || t.indexOf('创建') >= 0) return 'tag-green';
  if (t.indexOf('改价') >= 0 || t.indexOf('修改') >= 0 || t.indexOf('调整') >= 0 || t.indexOf('改') >= 0) return 'tag-yellow';
  if (t.indexOf('推广') >= 0) return 'tag-blue';
  return 'tag-gray';
}

async function loadChanges() {
  var el = document.getElementById('changesSection');

  // 并行拉日志和追踪数据
  var logsData = await api('/api/logs?limit=50');
  var trackData = await api('/api/tracking?limit=200');
  var logs = logsData || [];
  var trackItems = (trackData || []).filter(function(t) { return t.status !== 'disabled'; });

  // 按运营店铺过滤日志
  if (MY_SHOPS.length > 0) {
    logs = logs.filter(function(l) {
      if (!l.shop_name) return false;
      return MY_SHOPS.some(function(s) { return l.shop_name.indexOf(s) >= 0 || s.indexOf(l.shop_name) >= 0; });
    });
  }

  // 构建tracking map: log_id -> { status, items[] }
  trackingStatusMap = {};
  trackingByLogId = {};
  for (var i = 0; i < trackItems.length; i++) {
    var t = trackItems[i];
    var prev = trackingStatusMap[t.log_id];
    if (!prev || t.status === 'pending') trackingStatusMap[t.log_id] = t.status;
    if (!trackingByLogId[t.log_id]) trackingByLogId[t.log_id] = [];
    trackingByLogId[t.log_id].push(t);
  }

  if (logs.length === 0) {
    el.innerHTML = '<div class="empty">还没有操作记录<br><span style="font-size:10px;color:#ccc">在后台操作后这里会自动记录</span></div>';
    updateBadge('trackBadge', 0);
    return;
  }

  // 按日期+门店分组
  var byDate = {};
  for (var i = 0; i < logs.length; i++) {
    var dk = dateKey(logs[i].timestamp);
    if (!byDate[dk]) byDate[dk] = [];
    byDate[dk].push(logs[i]);
  }

  var today = new Date().toISOString().slice(0, 10);
  var yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  var dueCount = 0;
  var html = '';

  var sortedDates = Object.keys(byDate).sort().reverse();
  for (var di = 0; di < sortedDates.length; di++) {
    var dk = sortedDates[di];
    var dayLogs = byDate[dk];

    // 日期标题 + 状态图标
    var dateIcon = '';
    if (dk === today) dateIcon = '&#9998; '; // 编辑
    else if (dk === yesterday) dateIcon = '&#9203; '; // 沙漏
    else dateIcon = '&#128202; '; // 图表

    html += '<div class="log-date">' + dateIcon + fmtDate(dayLogs[0].timestamp) + '</div>';

    // 按门店分组
    var byShop = {};
    var shopOrder = [];
    for (var li = 0; li < dayLogs.length; li++) {
      var shopKey = dayLogs[li].shop_name || '未知门店';
      if (!byShop[shopKey]) { byShop[shopKey] = []; shopOrder.push(shopKey); }
      byShop[shopKey].push(dayLogs[li]);
    }

    for (var si = 0; si < shopOrder.length; si++) {
      var shopName = shopOrder[si];
      var shopLogs = byShop[shopName];

      html += '<div class="store-card">';
      html += '<div class="store-name" style="font-size:13px">' + esc(shopName) + '</div>';

      for (var li = 0; li < shopLogs.length; li++) {
        var l = shopLogs[li];
        var sm = l.change_summary || l.action_detail || l.action_type || '';
        var tagCls = actionTagClass(l.action_type);
        var logId = l.id;
        var tStatus = logId ? trackingStatusMap[logId] : null;

        // 追踪开关（今天的才显示）
        var toggleHtml = '';
        if (dk === today && logId && tStatus) {
          var isOn = tStatus !== 'disabled';
          toggleHtml = '<div class="toggle-wrap">' +
            '<button class="toggle-switch ' + (isOn ? 'on' : '') + '" data-logid="' + logId + '" data-enabled="' + (isOn ? '1' : '0') + '">' +
              '<span class="toggle-text on-text">追踪</span>' +
              '<span class="toggle-text off-text">关</span>' +
              '<span class="toggle-knob"></span>' +
            '</button></div>';
        }

        html += '<div class="log-item">' +
          '<div class="log-time">' + fmtHM(l.timestamp) + '</div>' +
          '<div class="log-body">' +
            '<div class="log-summary"><span class="tag ' + tagCls + '">' + esc(l.action_type || '操作') + '</span>' + esc(sm) + '</div>' +
          '</div>' + toggleHtml + '</div>';

        // 3天+的条目显示T+3/T+7追踪状态
        if (dk < yesterday && logId && trackingByLogId[logId]) {
          var tItems = trackingByLogId[logId];
          tItems.sort(function(a, b) { return (a.check_date || '').localeCompare(b.check_date || ''); });
          var hasDue = tItems.some(function(x) { return x.status === 'pending' && x.check_date <= today; });
          if (hasDue) dueCount++;

          html += '<div class="review-timeline" style="margin:4px 0 6px 42px">';
          for (var ci = 0; ci < tItems.length; ci++) {
            var cp = tItems[ci];
            var cpLabel = cp.check_type === '3day' ? 'T+3' : cp.check_type === '7day' ? 'T+7' : cp.check_type;
            var cpClass = 'review-checkpoint';
            if (cp.status === 'done') cpClass += ' done';
            else if (cp.status === 'pending' && cp.check_date <= today) cpClass += ' due';
            else cpClass += ' active';

            html += '<div class="' + cpClass + '">' +
              '<div class="cp-label">' + cpLabel + '</div>' +
              '<div class="cp-date">' + (cp.check_date || '') + '</div>';
            if (cp.status === 'done' && cp.metrics_after) html += '<div class="cp-summary">' + esc(cp.metrics_after) + '</div>';
            else if (cp.status === 'pending' && cp.check_date <= today) html += '<div class="cp-status">待复盘</div>';
            else if (cp.status === 'pending') html += '<div class="cp-status waiting">等待中</div>';
            html += '</div>';
          }
          html += '</div>';
        }
      }
      html += '</div>';
    }
  }

  updateBadge('trackBadge', dueCount);
  el.innerHTML = html;

  // 绑定追踪开关
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

function toggleTracking(logId, enable) {
  var path = enable ? '/api/tracking/enable_log/' + logId : '/api/tracking/disable_log/' + logId;
  apiPost(path, {}).then(function() { loadChanges(); });
}


// ========== Badge ==========

function updateBadge(elemId, count) {
  var el = document.getElementById(elemId);
  if (!el) return;
  if (count > 0) {
    el.textContent = count;
    el.style.display = 'inline-block';
  } else {
    el.style.display = 'none';
  }
}

// ========== Agent status + Patrol ==========

var agentReady = false;

async function showPatrolDebug() {
  var el = document.getElementById('patrolDebug');
  if (!el) return;
  try {
    var data = await api('/api/patrol/debug');
    if (!data || !data.log || data.log.length === 0) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    // 只显示最近8条
    var recent = data.log.slice(-8);
    el.innerHTML = recent.map(function(e) {
      var icon = e.ok ? '<span style="color:#4caf50">✓</span>' : '<span style="color:#c62828">✗</span>';
      return icon + ' <span style="color:#888">' + e.t + '</span> [' + e.phase + '] ' + e.msg;
    }).join('<br>');
    el.scrollTop = el.scrollHeight;
  } catch(e) { el.style.display = 'none'; }
}

function hidePatrolDebug() {
  var el = document.getElementById('patrolDebug');
  if (el) el.style.display = 'none';
}

async function checkAgent() {
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');
  var btn = document.getElementById('patrolBtn');

  // Step 1: Check if server.py is running at all
  var serverAlive = false;
  try {
    var res = await fetch(SERVER_URL + '/api/logs?limit=1');
    serverAlive = res.ok;
  } catch(e) {}

  if (!serverAlive) {
    dot.className = 'agent-dot off';
    msg.textContent = '服务未启动';
    btn.disabled = true;
    btn.textContent = '巡检';
    var hint = document.getElementById('startHint');
    if (hint) hint.style.display = 'block';
    return;
  }
  var hint2 = document.getElementById('startHint');
  if (hint2) hint2.style.display = 'none';

  // Step 2: Server is running, check agent status
  var data = await api('/api/agent/status');
  if (!data) {
    // server.py is running but no /api/agent/status endpoint — older server version
    dot.className = 'agent-dot ok';
    msg.textContent = '服务已连接（无巡检）';
    btn.disabled = true;
    btn.style.display = 'none';
    return;
  }

  btn.style.display = '';
  agentReady = data.has_run_fast;

  if (data.patrol && data.patrol.state === 'running') {
    dot.className = 'agent-dot busy';
    msg.textContent = data.patrol.last_step || data.patrol.message || '巡检中...';
    btn.disabled = false;
    btn.textContent = '停止';
    btn.onclick = stopPatrol;
    // 显示debug日志
    showPatrolDebug();
    setTimeout(checkAgent, 3000);
    return;
  } else {
    btn.onclick = startPatrol;
    hidePatrolDebug();
  }

  if (data.patrol && data.patrol.state === 'done') {
    dot.className = 'agent-dot ok';
    msg.textContent = '巡检完成';
    btn.disabled = false;
    btn.textContent = '巡检';
    loadDaily();
    loadAlerts();
  } else if (data.patrol && data.patrol.state === 'error') {
    dot.className = 'agent-dot off';
    var errMsg = data.patrol.message || '巡检异常';
    // 登录过期时显示更友好的提示
    if (errMsg.indexOf('登录') >= 0 || errMsg.indexOf('悟空') >= 0) {
      msg.textContent = '登录过期，请在Chrome中重新登录悟空';
      msg.style.color = '#c62828';
    } else if (errMsg.indexOf('超时') >= 0) {
      msg.textContent = errMsg;
      msg.style.color = '#e65100';
    } else {
      msg.textContent = errMsg;
      msg.style.color = '';
    }
    btn.disabled = false;
    btn.textContent = '重试';
  } else if (data.has_run_fast) {
    dot.className = 'agent-dot ok';
    msg.textContent = 'agent就绪';
    btn.disabled = false;
    btn.textContent = '巡检';
  } else {
    dot.className = 'agent-dot ok';
    msg.textContent = '服务已连接';
    btn.disabled = true;
    btn.style.display = 'none';
  }
}

async function stopPatrol() {
  var btn = document.getElementById('patrolBtn');
  var msg = document.getElementById('agentMsg');
  btn.disabled = true;
  btn.textContent = '停止中...';
  var result = await apiPost('/api/patrol/stop', {});
  if (result && result.ok) {
    msg.textContent = '巡检已停止';
  } else {
    msg.textContent = (result && result.message) || '停止失败';
  }
  btn.onclick = startPatrol;
  setTimeout(checkAgent, 1000);
}

async function startPatrol() {
  var btn = document.getElementById('patrolBtn');
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');

  // 根据登录运营自动查品牌
  var opData = await chrome.storage.local.get('ops_operator');
  var operator = opData.ops_operator || '';
  if (!operator) { msg.textContent = '请先登录'; return; }

  btn.disabled = true;
  btn.textContent = '启动中...';
  dot.className = 'agent-dot busy';
  msg.style.color = '';

  // 先刷新headless登录态（从Chrome同步cookies）
  await apiPost('/api/headless/refresh', {});

  var result = await apiPost('/api/patrol/start', { operator: operator });
  if (result && result.ok) {
    msg.textContent = result.message || '巡检已启动';
    btn.textContent = '巡检中';
    setTimeout(checkAgent, 2000);
  } else if (result && result.error === 'no_brands') {
    msg.textContent = '请先设置品牌';
    btn.disabled = false;
    btn.textContent = '巡检';
    dot.className = 'agent-dot off';
  } else {
    msg.textContent = (result && result.message) || '启动失败';
    btn.disabled = false;
    btn.textContent = '巡检';
    dot.className = 'agent-dot off';
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
      btn.onclick = function() {
        btn.textContent = '下载中...';
        window.open(SERVER_URL + '/api/extension/download', '_blank');
        setTimeout(function() { btn.textContent = 'v' + data.version + ' 可更新'; }, 2000);
      };
    }
  }
}

// ========== Settings ==========

async function loadSettings() {
  var data = await api('/api/settings');
  if (!data) {
    // Use defaults from chrome.storage
    try {
      var stored = await chrome.storage.local.get('ops_settings');
      data = stored.ops_settings || {};
    } catch(e) { data = {}; }
  }
  var patrolToggle = document.getElementById('patrolToggle');
  var alertToggle = document.getElementById('alertToggle');
  var patrolTime = document.getElementById('patrolTime');
  var alertInterval = document.getElementById('alertInterval');

  if (data.patrol_enabled === true) patrolToggle.classList.add('on');
  if (data.alert_enabled === true) alertToggle.classList.add('on');
  if (data.patrol_time) patrolTime.value = data.patrol_time;
  if (data.alert_interval) alertInterval.value = data.alert_interval;
}

async function saveSettings() {
  var settings = {
    patrol_enabled: document.getElementById('patrolToggle').classList.contains('on'),
    alert_enabled: document.getElementById('alertToggle').classList.contains('on'),
    patrol_time: document.getElementById('patrolTime').value,
    alert_interval: parseInt(document.getElementById('alertInterval').value) || 30,
  };
  // Save to chrome.storage as fallback
  try { chrome.storage.local.set({ ops_settings: settings }); } catch(e) {}
  // Save to server if available
  apiPost('/api/settings', settings);
}

function initSettings() {
  // Mini toggle switches in agent bar
  ['patrolToggle', 'alertToggle'].forEach(function(id) {
    document.getElementById(id).addEventListener('click', function() {
      this.classList.toggle('on');
      saveSettings();
    });
  });

  loadSettings();
}

// ========== Init ==========

async function init() {
  // 直接从storage读，不依赖background service worker（可能休眠）
  var data = await chrome.storage.local.get(['ops_operator']);
  var operator = data.ops_operator || '';

  if (!operator) {
    document.getElementById('setup').style.display = 'block';
    document.getElementById('main').style.display = 'none';
    return;
  }

  document.getElementById('setup').style.display = 'none';
  document.getElementById('main').style.display = 'flex';

  // 立即检查agent状态（不等其他加载完）
  checkAgent();

  // 加载运营的店铺列表
  await discoverServer();
  try {
    var resp = await fetch(chrome.runtime.getURL('operators.json'));
    var opsData = await resp.json();
    var brands = opsData[operator] || {};
    var brandNames = Object.keys(brands);
    MY_SHOPS = [];
    brandNames.forEach(function(b) {
      (brands[b] || []).forEach(function(s) {
        if (s.shop) MY_SHOPS.push(s.shop);
      });
    });
    document.getElementById('infoLine').textContent = operator + ' — ' + brandNames.length + '个品牌';
  } catch(e) {
    document.getElementById('infoLine').textContent = operator;
  }

  checkVersion();
  loadDaily();
  loadAlerts();
  loadChanges();

  // 顺便唤醒background service worker
  chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, function() {
    if (chrome.runtime.lastError) {} // 忽略错误
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
    try {
      var resp = await fetch(chrome.runtime.getURL('operators.json'));
      _operatorsData = await resp.json();
    } catch(e) { _operatorsData = {}; }
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
      if (similar.length > 0) {
        html += '<div style="color:#999;text-align:center;margin-top:6px;font-size:11px">你是不是：' + similar.map(function(s){return esc(s)}).join('、') + '</div>';
      } else if (allNames.length > 0) {
        html += '<div style="color:#999;text-align:center;margin-top:6px;font-size:11px">现有运营：' + allNames.join('、') + '</div>';
      }
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
      if (!chrome.runtime.lastError) {
        // 同步运营名到server config.json，让定时调度器能读到
        apiPost('/api/settings', { operator: _pendingName });
        init();
      }
    });
  });

  document.getElementById('nameInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('okBtn').click();
  });

  document.getElementById('patrolBtn').addEventListener('click', function() {
    startPatrol();
  });

  // Refresh every 30s
  setInterval(function() {
    loadAlerts();
    loadChanges();
    checkAgent();
  }, 30000);
});

// ========== Tab 5: Chat (会话) ==========

var chatHistory = [];
var chatThinking = false;

function addChatMsg(role, text, toolInfo) {
  var area = document.getElementById('chatArea');
  var welcome = document.getElementById('quickBtns');
  if (welcome && welcome.parentElement) welcome.parentElement.style.display = 'none';

  var div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  if (role === 'bot' && toolInfo) {
    div.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>') + '<div class="tool-info">' + esc(toolInfo) + '</div>';
  } else if (role === 'err') {
    div.textContent = text;
  } else {
    div.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
  }
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function sendQuick(text) {
  document.getElementById('chatInput').value = text;
  sendMsg();
}

async function sendMsg() {
  var input = document.getElementById('chatInput');
  var text = input.value.trim();
  if (!text || chatThinking) return;
  input.value = '';
  addChatMsg('user', text);

  chatHistory.push({ role: 'user', content: text });
  chatThinking = true;
  document.getElementById('sendBtn').disabled = true;

  try {
    var opData = await chrome.storage.local.get('ops_operator');
    var res = await fetch(SERVER_URL + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, operator: opData.ops_operator || '', history: chatHistory.slice(-20) })
    });
    if (!res.ok) { addChatMsg('err', '服务出错: ' + res.status); }
    else {
      var data = await res.json();
      var reply = data.reply || '(没有回复)';
      chatHistory.push({ role: 'assistant', content: reply });
      addChatMsg('bot', reply, data.tools_used ? data.tools_used.join(' → ') : '');
    }
  } catch(e) {
    addChatMsg('err', '连接失败: ' + e.message);
  }
  chatThinking = false;
  document.getElementById('sendBtn').disabled = false;
}
