/* popup.js — 小q助手 五Tab面板 (settings removed, split into daily/alerts footers) */

var SERVER_URL = 'http://127.0.0.1:5500';
var MY_SHOPS = []; // 当前运营名下的店铺名列表
var _dismissedAlerts = {}; // 已dismiss的预警key -> timestamp
var _currentOperator = ''; // cached operator name

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
      // 切到预警Tab时不自动清红点，由用户点"知道了"逐条清
    });
  });
}

// ========== Settings footer HTML generators ==========

function buildServerStatusHtml(containerId) {
  return '<div class="server-status" id="' + containerId + '"></div>';
}

async function refreshServerStatus(containerId) {
  var el = document.getElementById(containerId);
  if (!el) return;
  var serverOk = false;
  try {
    var res = await fetch(SERVER_URL + '/health', { signal: AbortSignal.timeout(2000) });
    serverOk = res.ok;
  } catch(e) {}

  if (serverOk) {
    el.innerHTML = '<span style="color:#2e7d32">● 服务运行中</span>';
  } else {
    el.innerHTML = '<span style="color:#c62828">● 服务未启动</span> <button class="restart-server-btn" style="margin-left:6px;background:#e94560;color:#fff;border:none;border-radius:4px;padding:2px 10px;font-size:10px;cursor:pointer">启动服务</button>';
    var btn = el.querySelector('.restart-server-btn');
    if (btn) {
      btn.addEventListener('click', function() {
        btn.textContent = '启动中...';
        btn.disabled = true;
        fetch(SERVER_URL + '/health').catch(function(){});
        setTimeout(function() { refreshServerStatus(containerId); }, 5000);
      });
    }
  }
}

function buildPatrolSettingsFooter() {
  return '<div class="settings-footer" id="dailySettingsFooter">' +
    '<div class="setting-row">' +
      '<span class="setting-label">定时巡检</span>' +
      '<input class="setting-input" id="patrolTime" type="time" value="10:00" />' +
      '<button class="toggle-switch" id="patrolToggle" style="width:42px;height:20px">' +
        '<span class="toggle-text on-text" style="font-size:8px;left:4px">开</span>' +
        '<span class="toggle-text off-text" style="font-size:8px;right:4px">关</span>' +
        '<span class="toggle-knob" style="width:16px;height:16px"></span>' +
      '</button>' +
    '</div>' +
    buildServerStatusHtml('dailyServerStatus') +
  '</div>';
}

function buildAlertSettingsFooter() {
  return '<div class="settings-footer" id="alertsSettingsFooter">' +
    '<div class="setting-row">' +
      '<span class="setting-label">实时预警</span>' +
      '<input class="setting-input" id="alertInterval" type="number" value="30" min="5" max="120" />' +
      '<span class="setting-unit">分钟</span>' +
      '<button class="toggle-switch" id="alertToggle" style="width:42px;height:20px">' +
        '<span class="toggle-text on-text" style="font-size:8px;left:4px">开</span>' +
        '<span class="toggle-text off-text" style="font-size:8px;right:4px">关</span>' +
        '<span class="toggle-knob" style="width:16px;height:16px"></span>' +
      '</button>' +
    '</div>' +
    buildServerStatusHtml('alertsServerStatus') +
  '</div>';
}

// ========== Tab 1: Daily Report (clean briefing style) ==========

async function loadDaily() {
  var el = document.getElementById('tab-daily');
  var data = await api('/api/daily');
  if (!data || !data.stores || data.stores.length === 0) {
    el.innerHTML = '<div class="empty">暂无巡检日报<br><span style="font-size:10px;color:#ccc">agent跑巡检后这里会显示结果</span></div>' + buildPatrolSettingsFooter();
    initDailySettingsFooter();
    return;
  }

  var html = '<div class="daily-meta">巡检时间: ' + esc(data.ts) +
    (data.brands ? ' · ' + data.brands + '个品牌' : '') +
    (data.duration ? ' · ' + data.duration + '秒' : '') + '</div>';

  // 用品牌分组渲染（品牌→门店→平台）
  var groups = data.brands_grouped || [];
  // 回退：没有brands_grouped时用旧的stores平铺
  if (groups.length === 0 && data.stores.length > 0) {
    groups = [{ brand: '', stores: data.stores }];
  }

  for (var gi = 0; gi < groups.length; gi++) {
    var group = groups[gi];
    if (group.brand) {
      html += '<div class="brand-header">' + esc(group.brand) +
        ' <span class="brand-count">' + group.stores.length + '家店</span></div>';
    }

    for (var si = 0; si < group.stores.length; si++) {
      var store = group.stores[si];
      // 判断是否全部授权失败
      var allAuth = store.platforms.every(function(p) { return p.has_auth_issue; });

      html += '<div class="store-card' + (allAuth ? ' auth-fail' : '') + '">';
      html += '<div class="store-name-line">' + esc(store.store) + '</div>';

      if (allAuth) {
        var authPlatforms = store.platforms.map(function(p){return p.platform}).join('、');
        html += '<div class="daily-issue-item" style="color:#c62828">\uD83D\uDD34 未授权 · ' + esc(authPlatforms) + '</div>';
      } else {
        for (var j = 0; j < store.platforms.length; j++) {
          var p = store.platforms[j];
          html += '<div class="platform-section">';
          // Clean: plain text platform name in parentheses
          html += '<span style="font-size:11px;color:#999">(' + esc(p.platform) + ')</span>';

          if (p.has_auth_issue) {
            html += '<span class="daily-issue-item" style="color:#c62828"> \uD83D\uDD34 未授权</span>';
            html += '</div>';
            continue;
          }

          var issues = [];

          if (p.bad_review_count > 0) {
            var revHtml = '<div class="daily-issue-item">\uD83D\uDD34 差评' + p.bad_review_count + '条</div>';
            for (var k = 0; k < p.bad_reviews.length && k < 2; k++) {
              var r = p.bad_reviews[k];
              revHtml += '<div class="review-detail">' + r.stars + '星 "' + esc((r.comment||'').substring(0,35)) + '"</div>';
            }
            issues.push(revHtml);
          }

          if (p.expiring_count > 0) {
            for (var k = 0; k < p.activities.length; k++) {
              var a = p.activities[k];
              var prefix = (a.days_left || 99) <= 1 ? '\uD83D\uDD34' : '\uD83D\uDFE1';
              issues.push('<div class="daily-issue-item">' + prefix + ' ' + esc(a.name) + ' ' + a.days_left + '天到期</div>');
            }
          }

          if (p.promo_balance !== null && p.promo_balance !== undefined) {
            if (p.promo_daily_spend && p.promo_daily_spend > 0) {
              var daysLeft = p.promo_balance / p.promo_daily_spend;
              if (daysLeft < 1) {
                issues.push('<div class="daily-issue-item">\uD83D\uDD34 推广余额\u00A5' + p.promo_balance.toFixed(0) + ' 今天可能用完</div>');
              } else if (daysLeft < 3) {
                issues.push('<div class="daily-issue-item">\uD83D\uDFE1 推广余额\u00A5' + p.promo_balance.toFixed(0) + ' ' + daysLeft.toFixed(1) + '天</div>');
              }
            }
          }

          if (p.notice_count > 0) {
            var noticeHtml = '<div class="daily-issue-item">\u00B7 ' + p.notice_count + '条通知</div>';
            for (var k = 0; k < (p.notices || []).length && k < 2; k++) {
              noticeHtml += '<div class="review-detail">' + esc(p.notices[k].title) + '</div>';
            }
            issues.push(noticeHtml);
          }

          if ((p.errors || []).length > 0) {
            for (var k = 0; k < p.errors.length; k++) {
              issues.push('<div class="daily-issue-item">\uD83D\uDFE1 ' + esc(p.errors[k]) + '</div>');
            }
          }

          if (issues.length === 0) {
            html += '<span class="daily-normal">\u2713 正常</span>';
          } else {
            html += '<div class="daily-issue-list">' + issues.join('') + '</div>';
          }

          html += '</div>';
        }
      }
      html += '</div>';
    }
  }

  // Append patrol settings footer
  html += buildPatrolSettingsFooter();
  el.innerHTML = html;
  initDailySettingsFooter();
}

function initDailySettingsFooter() {
  var toggle = document.getElementById('patrolToggle');
  var timeInput = document.getElementById('patrolTime');
  if (toggle) {
    toggle.addEventListener('click', function() {
      this.classList.toggle('on');
      saveSettings();
    });
  }
  if (timeInput) {
    timeInput.addEventListener('change', function() {
      saveSettings();
    });
  }
  // Load saved settings into these elements
  loadSettingsIntoElements();
  refreshServerStatus('dailyServerStatus');
}

// ========== Tab 2: Alerts ==========

async function loadAlerts() {
  var el = document.getElementById('tab-alerts');
  var data = await api('/api/alerts');
  if (!data || data.length === 0) {
    el.innerHTML = '<div class="empty">暂无预警</div>' + buildAlertSettingsFooter();
    updateBadge('alertBadge', 0);
    initAlertSettingsFooter();
    return;
  }

  // 过滤掉已dismiss的预警 (Change 4: stable key without detail)
  var dismissed = _dismissedAlerts || {};
  data = data.filter(function(a) {
    var key = (a.store||'') + '|' + (a.type||'') + '|' + (a.msg||'');
    return !dismissed[key];
  });

  var redCount = data.filter(function(a) { return a.level === 'red'; }).length;
  updateBadge('alertBadge', data.length);

  if (data.length === 0) {
    el.innerHTML = '<div class="empty">暂无预警</div>' + buildAlertSettingsFooter();
    initAlertSettingsFooter();
    return;
  }

  // 分离授权失败和正常预警
  var authAlerts = data.filter(function(a) { return a.type === 'auth'; });
  var normalAlerts = data.filter(function(a) { return a.type !== 'auth'; });

  // 巡检来源时间
  var patrolTs = data[0] && data[0].patrol_ts ? data[0].patrol_ts : '';
  var html = '';
  if (patrolTs) {
    html += '<div class="daily-meta">数据来源: ' + esc(patrolTs) + ' 巡检</div>';
  }

  // 授权失败的店
  for (var ai = 0; ai < authAlerts.length; ai++) {
    var aa = authAlerts[ai];
    var pname = aa.platform === 'eleme' ? '饿了么' : aa.platform === 'meituan' ? '美团' : aa.platform || '';
    // Change 4: stable key (store|type|msg)
    var akey = (aa.store||'') + '|' + (aa.type||'') + '|' + (aa.msg||'');
    html += '<div class="store-card alert-dismissable" data-alert-key="' + esc(akey) + '" style="border-left:3px solid #e65100;position:relative">' +
      '<div class="store-name" style="color:#e65100">' + esc(aa.store) + '</div>' +
      '<div class="issue-line red">未授权 · ' + esc(pname) + '</div>' +
      '<button class="dismiss-btn">知道了</button>' +
    '</div>';
  }

  // 正常预警按时间线+店铺分组
  var byDate = {};
  var dateOrder = [];
  for (var i = 0; i < normalAlerts.length; i++) {
    var a = normalAlerts[i];
    var eventDate = (a.event_time || '').slice(0, 10) || '未知';
    if (!byDate[eventDate]) { byDate[eventDate] = []; dateOrder.push(eventDate); }
    byDate[eventDate].push(a);
  }
  dateOrder.sort(function(a, b) { return b.localeCompare(a); });

  for (var di = 0; di < dateOrder.length; di++) {
    var date = dateOrder[di];
    var dayAlerts = byDate[date];
    html += '<div class="section-title">' + (date === '未知' ? '' : fmtDate(date + 'T00:00')) + '</div>';

    var byStore = {};
    var storeOrder = [];
    for (var i = 0; i < dayAlerts.length; i++) {
      var a = dayAlerts[i];
      var key = a.store || '未知';
      if (!byStore[key]) { byStore[key] = []; storeOrder.push(key); }
      byStore[key].push(a);
    }

    for (var si = 0; si < storeOrder.length; si++) {
      var storeName = storeOrder[si];
      var alerts = byStore[storeName];
      html += '<div class="store-card"><div class="store-name">' + esc(storeName) + '</div>';
      for (var j = 0; j < alerts.length; j++) {
        var a = alerts[j];
        var pname = a.platform === 'eleme' ? '饿了么' : a.platform === 'meituan' ? '美团' : a.platform || '';
        // Change 4: stable key (store|type|msg) — no detail
        var akey = (a.store||'') + '|' + (a.type||'') + '|' + (a.msg||'');
        html += '<div class="alert-row alert-dismissable" data-alert-key="' + esc(akey) + '">' +
          '<div class="alert-dot ' + a.level + '"></div>' +
          '<div class="alert-body">' +
            '<div class="alert-msg">' + esc(a.msg) + (pname ? ' <span style="color:#999;font-weight:400;font-size:10px">' + esc(pname) + '</span>' : '') + '</div>' +
            (a.detail ? '<div class="alert-detail">' + esc(a.detail) + '</div>' : '') +
          '</div>' +
          '<button class="dismiss-btn">知道了</button>' +
        '</div>';
      }
      html += '</div>';
    }
  }

  // Append alert settings footer
  html += buildAlertSettingsFooter();
  el.innerHTML = html;
  initAlertSettingsFooter();

  // 绑定"知道了"按钮 (Change 4: store timestamp instead of true)
  el.querySelectorAll('.alert-dismissable').forEach(function(item) {
    item.querySelector('.dismiss-btn').addEventListener('click', function(e) {
      e.stopPropagation();
      var key = item.dataset.alertKey;
      _dismissedAlerts[key] = Date.now(); // timestamp for 24h expiry
      try { chrome.storage.local.set({ dismissed_alerts: _dismissedAlerts }); } catch(e) {}
      item.style.transition = 'opacity 0.3s';
      item.style.opacity = '0';
      setTimeout(function() {
        item.remove();
        // 更新红点
        var remaining = el.querySelectorAll('.alert-dismissable').length;
        updateBadge('alertBadge', remaining);
        if (remaining === 0) {
          // Re-render to show empty + footer
          el.innerHTML = '<div class="empty">暂无预警</div>' + buildAlertSettingsFooter();
          initAlertSettingsFooter();
        }
      }, 300);
    });
  });
}

function initAlertSettingsFooter() {
  var toggle = document.getElementById('alertToggle');
  var intervalInput = document.getElementById('alertInterval');
  if (toggle) {
    toggle.addEventListener('click', function() {
      this.classList.toggle('on');
      saveSettings();
    });
  }
  if (intervalInput) {
    intervalInput.addEventListener('change', function() {
      saveSettings();
    });
  }
  loadSettingsIntoElements();
  refreshServerStatus('alertsServerStatus');
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
  if (MY_SHOPS.length > 0) {
    logs = logs.filter(function(l) {
      if (!l.shop_name) return false;
      return MY_SHOPS.some(function(s) { return l.shop_name.indexOf(s) >= 0 || s.indexOf(l.shop_name) >= 0; });
    });
  }
  if (logs.length === 0) {
    el.innerHTML = '<div class="empty">还没有操作记录</div>';
    return;
  }
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
            '<span class="toggle-text on-text">复盘</span>' +
            '<span class="toggle-text off-text">关</span>' +
            '<span class="toggle-knob"></span>' +
          '</button>' +
          '</div>';
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
        toggleHtml +
      '</div>';
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

// ========== Tab 4: Tracking ==========

async function loadTracking() {
  var el = document.getElementById('tab-tracking');

  var opData = await chrome.storage.local.get('ops_operator');
  var opName = opData.ops_operator || '';
  var trackUrl = '/api/tracking?limit=200' + (opName ? '&operator=' + encodeURIComponent(opName) : '');
  var allData = await api(trackUrl);
  var allItems = (allData || []).filter(function(t) { return t.status !== 'disabled'; });

  if (allItems.length === 0) {
    el.innerHTML = '<div class="empty">暂无复盘任务<br><span style="font-size:10px;color:#ccc">操作后台后自动创建T+3/T+7复盘</span></div>';
    updateBadge('trackBadge', 0);
    return;
  }

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
        card += '<div class="cp-summary">' + esc(cp.metrics_after) + '</div>';
      } else if (cp.status === 'pending' && cp.check_date <= today) {
        card += '<div class="cp-status">待生成</div>';
      } else if (cp.status === 'pending') {
        card += '<div class="cp-status waiting">等待中</div>';
      }

      card += '</div>';
    }

    card += '</div></div>';
    html += card;
  }

  updateBadge('trackBadge', dueCount);
  if (!html) html = '<div class="empty">暂无复盘任务</div>';
  el.innerHTML = html;

  el.querySelectorAll('.cp-close-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var tid = parseInt(btn.dataset.tid);
      closeCheckpoint(tid);
    });
  });
}

async function closeCheckpoint(tid) {
  await apiPost('/api/tracking/' + tid + '/disable', {});
  loadTracking();
}

function toggleTracking(logId, enable) {
  var path = enable ? '/api/tracking/enable_log/' + logId : '/api/tracking/disable_log/' + logId;
  apiPost(path, {}).then(function() {
    loadTrackingStatus();
    loadTracking();
  });
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

async function checkAgent() {
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');
  var btn = document.getElementById('patrolBtn');

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

  var data = await api('/api/agent/status');
  if (!data) {
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
    msg.textContent = data.patrol.message || '巡检中...';
    btn.disabled = false;
    btn.textContent = '停止';
    btn.dataset.action = 'stop';
    setTimeout(checkAgent, 3000);
    return;
  }
  btn.dataset.action = 'start';

  if (data.patrol && data.patrol.state === 'done') {
    dot.className = 'agent-dot ok';
    var doneMsg = '巡检完成';
    if (data.patrol.summary) doneMsg = data.patrol.summary;
    if (data.scheduled) doneMsg += ' · 每天' + data.scheduled + '自动巡检';
    msg.textContent = doneMsg;
    btn.disabled = false;
    btn.textContent = '巡检';
    loadDaily();
    loadAlerts();
  } else if (data.patrol && data.patrol.state === 'error') {
    dot.className = 'agent-dot off';
    var errMsg = data.patrol.message || '巡检异常';
    if (errMsg.indexOf('登录') >= 0 || errMsg.indexOf('悟空') >= 0) {
      msg.textContent = '登录过期，请在Chrome中重新登录悟空';
      msg.style.color = '#c62828';
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

async function startPatrol() {
  var btn = document.getElementById('patrolBtn');
  var dot = document.getElementById('agentDot');
  var msg = document.getElementById('agentMsg');

  var opData = await chrome.storage.local.get('ops_operator');
  var operator = opData.ops_operator || '';
  if (!operator) { msg.textContent = '请先登录'; return; }

  btn.disabled = true;
  btn.textContent = '启动中...';
  dot.className = 'agent-dot busy';
  msg.style.color = '';

  await apiPost('/api/headless/refresh', {});

  var result = await apiPost('/api/patrol/start', { operator: operator });
  if (result && result.ok) {
    msg.textContent = '已开启巡检，完成后自动开启每日巡检和预警';
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

async function stopPatrol() {
  var btn = document.getElementById('patrolBtn');
  var msg = document.getElementById('agentMsg');
  btn.disabled = true;
  btn.textContent = '停止中...';
  var result = await apiPost('/api/patrol/stop', {});
  if (result && result.ok) {
    msg.textContent = '巡检已停止';
    btn.textContent = '巡检';
    btn.disabled = false;
    btn.dataset.action = 'start';
    document.getElementById('agentDot').className = 'agent-dot off';
  } else {
    btn.disabled = false;
    btn.textContent = '停止';
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

// ========== Settings (now distributed across tab footers) ==========

var _settingsLoaded = false;
var _cachedSettings = {};

async function loadSettingsFromServer() {
  if (_settingsLoaded) return _cachedSettings;
  var data = await api('/api/settings');
  if (!data) {
    try {
      var stored = await chrome.storage.local.get('ops_settings');
      data = stored.ops_settings || {};
    } catch(e) { data = {}; }
  }
  _cachedSettings = data;
  _settingsLoaded = true;
  return data;
}

async function loadSettingsIntoElements() {
  var data = await loadSettingsFromServer();
  var patrolToggle = document.getElementById('patrolToggle');
  var alertToggle = document.getElementById('alertToggle');
  var patrolTime = document.getElementById('patrolTime');
  var alertInterval = document.getElementById('alertInterval');

  if (patrolToggle && data.patrol_enabled === true) patrolToggle.classList.add('on');
  if (alertToggle && data.alert_enabled === true) alertToggle.classList.add('on');
  if (patrolTime && data.patrol_time) patrolTime.value = data.patrol_time;
  if (alertInterval && data.alert_interval) alertInterval.value = data.alert_interval;
}

async function saveSettings() {
  var patrolToggle = document.getElementById('patrolToggle');
  var alertToggle = document.getElementById('alertToggle');
  var patrolTime = document.getElementById('patrolTime');
  var alertInterval = document.getElementById('alertInterval');

  var settings = {
    patrol_enabled: patrolToggle ? patrolToggle.classList.contains('on') : (_cachedSettings.patrol_enabled || false),
    alert_enabled: alertToggle ? alertToggle.classList.contains('on') : (_cachedSettings.alert_enabled || false),
    patrol_time: patrolTime ? patrolTime.value : (_cachedSettings.patrol_time || '10:00'),
    alert_interval: alertInterval ? parseInt(alertInterval.value) || 30 : (_cachedSettings.alert_interval || 30),
  };
  _cachedSettings = settings;
  try { chrome.storage.local.set({ ops_settings: settings }); } catch(e) {}
  apiPost('/api/settings', settings);
}

function initSettings() {
  // Settings elements are now created dynamically inside tab content.
  // This function is called on DOMContentLoaded but the elements don't exist yet.
  // The actual binding happens in initDailySettingsFooter() and initAlertSettingsFooter()
  // after loadDaily() and loadAlerts() render them.
}

// ========== Chat history persistence ==========

var _chatStorageKey = '';

async function loadChatHistory() {
  if (!_currentOperator) return [];
  _chatStorageKey = 'chat_history_' + _currentOperator;
  try {
    var stored = await chrome.storage.local.get(_chatStorageKey);
    var msgs = stored[_chatStorageKey] || [];
    // Limit to last 50
    if (msgs.length > 50) msgs = msgs.slice(-50);
    return msgs;
  } catch(e) { return []; }
}

function saveChatHistory(messages) {
  if (!_chatStorageKey) return;
  // Keep last 50
  var toSave = messages.slice(-50);
  try {
    var obj = {};
    obj[_chatStorageKey] = toSave;
    chrome.storage.local.set(obj);
  } catch(e) {}
}

function syncChatToServer(messages) {
  if (!_currentOperator) return;
  // Fire and forget
  apiPost('/api/chat/save', {
    operator: _currentOperator,
    messages: messages.slice(-50)
  });
}

function renderChatHistory(messages) {
  if (!messages || messages.length === 0) return;
  var area = document.getElementById('chatArea');
  var welcome = document.getElementById('chatWelcome');
  if (welcome) welcome.style.display = 'none';

  for (var i = 0; i < messages.length; i++) {
    var m = messages[i];
    var role = m.role === 'user' ? 'user' : m.role === 'assistant' ? 'bot' : 'bot';
    var div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.innerHTML = esc(m.content).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
    area.appendChild(div);
  }
  area.scrollTop = area.scrollHeight;
}

// ========== Init ==========

async function init() {
  // 加载dismissed预警 (Change 4: filter expired > 24h)
  try {
    var stored = await chrome.storage.local.get('dismissed_alerts');
    _dismissedAlerts = stored.dismissed_alerts || {};
  } catch(e) { _dismissedAlerts = {}; }

  // Clean expired dismissals (> 24h)
  var now = Date.now();
  Object.keys(_dismissedAlerts).forEach(function(k) {
    // Handle legacy boolean values: treat as expired
    if (typeof _dismissedAlerts[k] !== 'number') {
      delete _dismissedAlerts[k];
    } else if (now - _dismissedAlerts[k] > 86400000) {
      delete _dismissedAlerts[k];
    }
  });
  try { chrome.storage.local.set({ dismissed_alerts: _dismissedAlerts }); } catch(e) {}

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

    _currentOperator = state.operator;

    document.getElementById('setup').style.display = 'none';
    document.getElementById('main').style.display = 'flex';

    // 加载运营的店铺列表
    await discoverServer();
    try {
      var resp = await fetch(chrome.runtime.getURL('operators.json'));
      var opsData = await resp.json();
      var brands = opsData[state.operator] || {};
      var brandNames = Object.keys(brands);
      var shopCount = 0;
      MY_SHOPS = [];
      brandNames.forEach(function(b) {
        brands[b].forEach(function(s) {
          shopCount++;
          if (s.shop) MY_SHOPS.push(s.shop);
        });
      });
      document.getElementById('infoLine').textContent = state.operator + ' \u2014 ' + brandNames.length + '个品牌';
    } catch(e) {
      document.getElementById('infoLine').textContent = state.operator;
    }

    checkVersion();
    checkAgent();
    loadDaily();
    loadAlerts();
    loadLogs();
    loadTracking();

    // Load and render chat history (Change 2)
    var savedChat = await loadChatHistory();
    if (savedChat.length > 0) {
      chatHistory = savedChat;
      renderChatHistory(savedChat);
    }
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

    var html = '<div style="color:#2e7d32;font-weight:600;margin-bottom:6px">' + esc(name) + ' \u2014 ' + brandNames.length + '个品牌 ' + totalShops + '家店</div>';
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
        apiPost('/api/settings', { operator: _pendingName });
        init();
      }
    });
  });

  document.getElementById('nameInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('okBtn').click();
  });

  document.getElementById('patrolBtn').addEventListener('click', function() {
    if (this.dataset.action === 'stop') {
      stopPatrol();
    } else {
      startPatrol();
    }
  });

  // Chat: 绑定发送按钮和回车键（MV3不支持inline事件）
  document.getElementById('sendBtn').addEventListener('click', function() {
    sendMsg();
  });
  document.getElementById('chatInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendMsg();
  });
  // Quick buttons
  document.querySelectorAll('.quick-btn[data-quick]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      sendQuick(btn.dataset.quick);
    });
  });

  // Refresh every 30s
  setInterval(function() {
    loadAlerts();
    loadTracking();
    checkAgent();
  }, 30000);
});

// ========== Tab 5: Chat (会话) ==========

var chatHistory = [];
var chatThinking = false;

function addChatMsg(role, text, toolInfo) {
  var area = document.getElementById('chatArea');
  var welcome = document.getElementById('chatWelcome');
  if (welcome) welcome.style.display = 'none';

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

  chatHistory.push({ role: 'user', content: text, ts: Date.now() });
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
      chatHistory.push({ role: 'assistant', content: reply, ts: Date.now() });
      addChatMsg('bot', reply, data.tools_used ? data.tools_used.join(' \u2192 ') : '');

      // Change 2: persist chat history after each exchange
      saveChatHistory(chatHistory);
      syncChatToServer(chatHistory);
    }
  } catch(e) {
    addChatMsg('err', '连接失败: ' + e.message);
  }
  chatThinking = false;
  document.getElementById('sendBtn').disabled = false;
}
