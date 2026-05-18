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
      if (logId && tStatus) {
        if (tStatus === 'disabled') {
          trackBtn = '<button class="track-toggle off" onclick="toggleTracking(' + logId + ', true)">关闭复盘</button>';
        } else {
          trackBtn = '<button class="track-toggle on" onclick="toggleTracking(' + logId + ', false)">复盘</button>';
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

  // Only show items that are not disabled (i.e. 复盘 is on)
  var allData = await api('/api/tracking?limit=200');
  var allItems = (allData || []).filter(function(t) { return t.status !== 'disabled'; });

  if (allItems.length === 0) {
    el.innerHTML = '<div class="empty">暂无复盘任务<br><span style="font-size:10px;color:#ccc">操作后台后自动创建T+3/T+7复盘</span></div>';
    updateBadge('trackBadge', 0);
    return;
  }

  // Group by log_id
  var byLog = {};
  var logOrder = [];
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
  var dueCount = 0;
  var html = '';

  for (var oi = 0; oi < logOrder.length; oi++) {
    var lid = logOrder[oi];
    var group = byLog[lid];
    var hasDue = group.items.some(function(x) { return x.status === 'pending' && x.check_date <= today; });
    if (hasDue) dueCount++;

    var tagCls = actionTagClass(group.action);
    var cardClass = hasDue ? 'review-card due' : 'review-card';

    var card = '<div class="' + cardClass + '">' +
      '<div class="review-title">' +
        '<span class="tag ' + tagCls + '">' + esc(group.action) + '</span> ' +
        esc(group.summary) +
      '</div>' +
      '<div class="review-shop">' + esc(group.shop) + '</div>' +
      '<div class="review-timeline">';

    // Sort by check_date
    group.items.sort(function(a, b) { return (a.check_date || '').localeCompare(b.check_date || ''); });

    for (var ci = 0; ci < group.items.length; ci++) {
      var cp = group.items[ci];
      var cpLabel = cp.check_type === '3day' ? 'T+3' : cp.check_type === '7day' ? 'T+7' : cp.check_type;
      var cpClass = 'review-checkpoint';

      if (cp.status === 'done') {
        cpClass += ' done';
      } else if (cp.status === 'pending' && cp.check_date <= today) {
        cpClass += ' due';
      } else {
        cpClass += ' active';
      }

      card += '<div class="' + cpClass + '">' +
        '<div class="cp-label">' + cpLabel + '</div>' +
        '<div class="cp-date">' + (cp.check_date || '') + '</div>';

      if (cp.status === 'done' && cp.metrics_after) {
        // 已生成摘要
        card += '<div class="cp-summary">' + esc(cp.metrics_after) + '</div>';
      } else if (cp.status === 'pending' && cp.check_date <= today) {
        // 到期了，等待生成
        card += '<div class="cp-status">待生成</div>' +
          '<button class="cp-close-btn" onclick="closeCheckpoint(' + cp.id + ')">关闭</button>';
      } else if (cp.status === 'pending') {
        // 未到期
        card += '<div class="cp-status waiting">等待中</div>' +
          '<button class="cp-close-btn" onclick="closeCheckpoint(' + cp.id + ')">关闭</button>';
      } else if (cp.status === 'closed') {
        card += '<div class="cp-status closed">已关闭</div>';
      }

      card += '</div>';
    }

    card += '</div></div>';
    html += card;
  }

  updateBadge('trackBadge', dueCount);
  if (!html) html = '<div class="empty">暂无复盘任务</div>';
  el.innerHTML = html;
}

async function closeCheckpoint(tid) {
  await apiPost('/api/tracking/' + tid + '/disable', {});
  loadTracking();
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
window.closeCheckpoint = closeCheckpoint;
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
        btn.textContent = '更新中...';
        chrome.runtime.sendMessage({ type: 'OPS_RELOAD' });
      };
    }
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
    checkVersion();
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
