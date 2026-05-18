/* popup.js — 小q助手 四Tab面板 */

var SERVER_URL = '';

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

// ========== Tab 1: Daily Report ==========

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

      if (!hasIssue) {
        html += '<div class="issue-line green">无异常</div>';
      }

      html += '</div>';
    }
    html += '</div>';
  }

  el.innerHTML = html;
}

// ========== Tab 2: Alerts ==========

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
      '</div>' +
    '</div>';
  }
  el.innerHTML = html;
}

// ========== Tab 3: Logs ==========

var trackingStatusMap = {}; // log_id -> 'pending'|'disabled'|'done'|null

async function loadTrackingStatus() {
  var data = await api('/api/tracking?limit=500');
  trackingStatusMap = {};
  if (data && data.length > 0) {
    for (var i = 0; i < data.length; i++) {
      var t = data[i];
      var prev = trackingStatusMap[t.log_id];
      // If any tracking for this log is pending, mark as pending
      if (!prev || t.status === 'pending') {
        trackingStatusMap[t.log_id] = t.status;
      }
    }
  }
}

async function loadLogs() {
  var el = document.getElementById('tab-logs');
  var data = await api('/api/logs?limit=50');

  if (!data || data.length === 0) {
    // Fallback to local storage
    try {
      chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, function(state) {
        if (state && state.recentLogs && state.recentLogs.length > 0) {
          renderLogs(el, state.recentLogs);
        } else {
          el.innerHTML = '<div class="empty">还没有操作记录</div>';
        }
      });
    } catch(e) {
      el.innerHTML = '<div class="empty">还没有操作记录</div>';
    }
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
      var trackBtn = '';
      if (logId) {
        if (tStatus === 'pending') {
          trackBtn = '<button class="track-toggle on" onclick="toggleTracking(' + logId + ', false)">追踪中</button>';
        } else if (tStatus === 'disabled') {
          trackBtn = '<button class="track-toggle off" onclick="toggleTracking(' + logId + ', true)">已关闭</button>';
        } else if (tStatus === 'done' || tStatus === 'effective' || tStatus === 'ineffective' || tStatus === 'observe') {
          trackBtn = '<span class="track-toggle done">已完成</span>';
        } else {
          // No tracking exists (e.g. skipped action types)
          trackBtn = '';
        }
      }

      html += '<div class="log-item">' +
        '<div class="log-time">' + fmtHM(l.timestamp) + '</div>' +
        '<div class="log-body">' +
          '<div class="log-summary">' +
            '<span class="tag ' + tagCls + '">' + esc(l.action_type || '操作') + '</span>' +
            esc(sm) +
          '</div>' +
          (shopStr ? '<div class="log-meta">' + esc(shopStr) + '</div>' : '') +
        '</div>' +
        trackBtn +
      '</div>';
    }
  }
  el.innerHTML = html;
}

function actionTagClass(t) {
  if (!t) return 'tag-gray';
  if (t.indexOf('下架') >= 0 || t.indexOf('删除') >= 0 || t.indexOf('关闭') >= 0) return 'tag-red';
  if (t.indexOf('上架') >= 0 || t.indexOf('新建') >= 0 || t.indexOf('创建') >= 0) return 'tag-green';
  if (t.indexOf('改价') >= 0 || t.indexOf('修改') >= 0 || t.indexOf('调整') >= 0 || t.indexOf('改') >= 0) return 'tag-yellow';
  if (t.indexOf('推广') >= 0) return 'tag-blue';
  return 'tag-gray';
}

// ========== Tab 4: Tracking ==========

async function loadTracking() {
  var el = document.getElementById('tab-tracking');

  var dueData = await api('/api/tracking/due');
  var allData = await api('/api/tracking?limit=30');

  var dueItems = dueData || [];
  var allItems = allData || [];

  updateBadge('trackBadge', dueItems.length);

  if (dueItems.length === 0 && allItems.length === 0) {
    el.innerHTML = '<div class="empty">暂无追踪任务<br><span style="font-size:10px;color:#ccc">操作后台后自动创建T+3/T+7追踪</span></div>';
    return;
  }

  var html = '';

  // Due items
  if (dueItems.length > 0) {
    html += '<div class="track-section-title">待查看 (' + dueItems.length + ')</div>';
    for (var i = 0; i < dueItems.length; i++) {
      var d = dueItems[i];
      var tagCls = actionTagClass(d.action_type || d.log_action_type);
      html += '<div class="track-card">' +
        '<div class="track-header">' +
          '<span class="tag ' + tagCls + '">' + esc(d.action_type || d.log_action_type || '') + '</span> ' +
          esc(d.change_summary || '') +
        '</div>' +
        '<div class="track-meta">' +
          esc(d.shop_name || '') + ' · ' + (d.check_type || '') + ' · 到期 ' + (d.check_date || '') +
        '</div>' +
        '<div class="track-actions">' +
          '<button class="track-btn effective" onclick="doFeedback(' + d.id + ',\'effective\')">有效</button>' +
          '<button class="track-btn ineffective" onclick="doFeedback(' + d.id + ',\'ineffective\')">无效</button>' +
          '<button class="track-btn observe" onclick="doFeedback(' + d.id + ',\'observe\')">再观察</button>' +
        '</div>' +
      '</div>';
    }
  }

  // Pending (not yet due)
  var pending = allItems.filter(function(t) { return t.status === 'pending' && !isDue(t.check_date); });
  if (pending.length > 0) {
    html += '<div class="track-section-title">进行中 (' + pending.length + ')</div>';
    for (var i = 0; i < pending.length && i < 10; i++) {
      var t = pending[i];
      var tagCls = actionTagClass(t.action_type);
      html += '<div class="track-card">' +
        '<div class="track-header">' +
          '<span class="tag ' + tagCls + '">' + esc(t.action_type || '') + '</span> ' +
          esc(t.change_summary || '') +
        '</div>' +
        '<div class="track-meta">' +
          esc(t.shop_name || '') + ' · ' + (t.check_type || '') + ' · ' + (t.check_date || '') +
        '</div>' +
      '</div>';
    }
  }

  // History (done/effective/ineffective)
  var done = allItems.filter(function(t) { return t.status !== 'pending'; });
  if (done.length > 0) {
    html += '<div class="track-section-title">历史</div>';
    for (var i = 0; i < done.length && i < 10; i++) {
      var t = done[i];
      var icon = t.status === 'effective' ? '有效' : t.status === 'ineffective' ? '无效' : t.status === 'observe' ? '观察中' : t.status;
      html += '<div class="track-history">' + icon + ' · ' + esc(t.action_type || '') + ' ' + esc(t.change_summary || '') + '</div>';
    }
  }

  if (!html) html = '<div class="empty">暂无追踪任务</div>';
  el.innerHTML = html;
}

function isDue(checkDate) {
  if (!checkDate) return false;
  return checkDate <= new Date().toISOString().slice(0, 10);
}

async function doFeedback(id, feedback) {
  await apiPost('/api/tracking/feedback', { id: id, feedback: feedback });
  loadTracking();
  loadAlerts();
}

async function toggleTracking(logId, enable) {
  if (enable) {
    await apiPost('/api/tracking/enable_log/' + logId, {});
  } else {
    await apiPost('/api/tracking/disable_log/' + logId, {});
  }
  await loadTrackingStatus();
  var el = document.getElementById('tab-logs');
  var data = await api('/api/logs?limit=50');
  if (data && data.length > 0) renderLogs(el, data);
  loadTracking();
}

// Make functions accessible from onclick
window.doFeedback = doFeedback;
window.toggleTracking = toggleTracking;

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

// ========== Init ==========

async function init() {
  chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, async function(state) {
    if (chrome.runtime.lastError || !state) {
      setTimeout(init, 300);
      return;
    }
    if (!state.operator) {
      document.getElementById('setup').style.display = 'block';
      document.getElementById('main').style.display = 'none';
      return;
    }

    document.getElementById('setup').style.display = 'none';
    document.getElementById('main').style.display = 'block';
    document.getElementById('infoLine').textContent = state.operator;

    await discoverServer();
    loadDaily();
    loadAlerts();
    loadLogs();
    loadTracking();
  });
}

document.addEventListener('DOMContentLoaded', function() {
  initTabs();
  init();

  document.getElementById('okBtn').addEventListener('click', function() {
    var name = document.getElementById('nameInput').value.trim();
    if (!name) return;
    chrome.runtime.sendMessage({ type: 'OPS_SET_OPERATOR', name: name }, function() {
      if (!chrome.runtime.lastError) init();
    });
  });

  document.getElementById('nameInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('okBtn').click();
  });

  // Refresh every 30s
  setInterval(function() {
    loadAlerts();
    loadTracking();
  }, 30000);
});
