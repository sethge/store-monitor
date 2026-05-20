/* popup.js — 小q助手 四Tab面板 */

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

// ========== Tab 1: Daily Report ==========

async function loadDaily() {
  var el = document.getElementById('tab-daily');
  var data = await api('/api/daily');
  if (!data || !data.stores || data.stores.length === 0) {
    el.innerHTML = '<div class="empty">暂无巡检日报<br><span style="font-size:10px;color:#ccc">agent跑巡检后这里会显示结果</span></div>';
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
        html += '<div class="issue-line red">未授权 · ' + esc(authPlatforms) + '</div>';
      } else {
        for (var j = 0; j < store.platforms.length; j++) {
          var p = store.platforms[j];
          html += '<div class="platform-section">';
          var pTag = p.platform === '美团' ? 'tag-meituan' : p.platform === '饿了么' ? 'tag-eleme' : 'tag-gray';
          html += '<span class="tag ' + pTag + '">' + esc(p.platform) + '</span>';

          if (p.has_auth_issue) {
            html += '<span class="issue-inline red">未授权</span>';
            html += '</div>';
            continue;
          }

          var issues = [];

          if (p.bad_review_count > 0) {
            var revHtml = '<span class="issue-inline red">差评' + p.bad_review_count + '条</span>';
            for (var k = 0; k < p.bad_reviews.length && k < 2; k++) {
              var r = p.bad_reviews[k];
              revHtml += '<div class="review-detail">' + r.stars + '星 "' + esc((r.comment||'').substring(0,35)) + '"</div>';
            }
            issues.push(revHtml);
          }

          if (p.expiring_count > 0) {
            for (var k = 0; k < p.activities.length; k++) {
              var a = p.activities[k];
              var cls = (a.days_left || 99) <= 1 ? 'red' : 'yellow';
              issues.push('<span class="issue-inline ' + cls + '">' + esc(a.name) + ' ' + a.days_left + '天到期</span>');
            }
          }

          if (p.promo_balance !== null && p.promo_balance !== undefined) {
            if (p.promo_daily_spend && p.promo_daily_spend > 0) {
              var daysLeft = p.promo_balance / p.promo_daily_spend;
              if (daysLeft < 1) {
                issues.push('<span class="issue-inline red">推广余额¥' + p.promo_balance.toFixed(0) + ' 今天可能用完</span>');
              } else if (daysLeft < 3) {
                issues.push('<span class="issue-inline yellow">推广余额¥' + p.promo_balance.toFixed(0) + ' ' + daysLeft.toFixed(1) + '天</span>');
              }
            }
          }

          if (p.notice_count > 0) {
            var noticeHtml = '<span class="issue-inline blue">' + p.notice_count + '条通知</span>';
            for (var k = 0; k < (p.notices || []).length && k < 2; k++) {
              noticeHtml += '<div class="review-detail">' + esc(p.notices[k].title) + '</div>';
            }
            issues.push(noticeHtml);
          }

          if ((p.errors || []).length > 0) {
            for (var k = 0; k < p.errors.length; k++) {
              issues.push('<span class="issue-inline yellow">' + esc(p.errors[k]) + '</span>');
            }
          }

          if (issues.length === 0) {
            html += '<span class="issue-inline green">正常</span>';
          } else {
            html += issues.join('');
          }

          html += '</div>';
        }
      }
      html += '</div>';
    }
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

  // 分离授权失败和正常预警
  var authAlerts = data.filter(function(a) { return a.type === 'auth'; });
  var normalAlerts = data.filter(function(a) { return a.type !== 'auth'; });

  // 按店铺分组
  var byStore = {};
  var storeOrder = [];
  for (var i = 0; i < normalAlerts.length; i++) {
    var a = normalAlerts[i];
    var key = a.store || '未知';
    if (!byStore[key]) { byStore[key] = []; storeOrder.push(key); }
    byStore[key].push(a);
  }

  // 巡检时间（取第一条的ts）
  var patrolTs = data[0] && data[0].ts ? data[0].ts : '';
  var html = '';
  if (patrolTs) {
    html += '<div class="daily-meta">预警来源: ' + esc(patrolTs) + ' 巡检</div>';
  }

  // 授权失败的店
  for (var ai = 0; ai < authAlerts.length; ai++) {
    var aa = authAlerts[ai];
    var pname = aa.platform === 'eleme' ? '饿了么' : aa.platform === 'meituan' ? '美团' : aa.platform || '';
    html += '<div class="store-card" style="border-left:3px solid #e65100">' +
      '<div class="store-name" style="color:#e65100">' + esc(aa.store) + '</div>' +
      '<div class="issue-line red">未授权 · ' + esc(pname) + '</div>' +
    '</div>';
  }

  // 正常预警按店铺分组
  for (var si = 0; si < storeOrder.length; si++) {
    var storeName = storeOrder[si];
    var alerts = byStore[storeName];
    html += '<div class="store-card"><div class="store-name">' + esc(storeName) + '</div>';
    for (var j = 0; j < alerts.length; j++) {
      var a = alerts[j];
      var pname = a.platform === 'eleme' ? '饿了么' : a.platform === 'meituan' ? '美团' : a.platform || '';
      var timeStr = a.ts ? fmtHM(a.ts) : '';
      html += '<div class="alert-item" style="margin:2px 0;padding:4px 0;box-shadow:none">' +
        '<div class="alert-dot ' + a.level + '"></div>' +
        '<div class="alert-body">' +
          '<div class="alert-msg">' + esc(a.msg) + (pname ? ' <span style="color:#999;font-weight:400;font-size:10px">' + esc(pname) + '</span>' : '') + '</div>' +
          (a.detail ? '<div class="alert-detail">' + esc(a.detail) + '</div>' : '') +
          (timeStr ? '<div style="font-size:9px;color:#bbb;margin-top:1px">' + timeStr + '</div>' : '') +
        '</div>' +
      '</div>';
    }
    html += '</div>';
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
  // 只显示属于该运营名下店铺的日志
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

  // Bind toggle switches — optimistic UI
  el.querySelectorAll('.toggle-switch').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var logId = parseInt(btn.dataset.logid);
      var isOn = btn.dataset.enabled === '1';
      // Instant toggle
      btn.classList.toggle('on');
      btn.dataset.enabled = isOn ? '0' : '1';
      // Fire and forget
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

  // 按运营过滤，只显示自己的复盘
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

  // Bind close buttons
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
    // 显示巡检概览：品牌数+问题数+定时状态
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
    // 登录过期时显示更友好的提示
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
  var btn = document.getElementById('settingsBtn');
  var panel = document.getElementById('settingsPanel');

  btn.addEventListener('click', function() {
    panel.classList.toggle('open');
  });

  // Toggle switches
  ['patrolToggle', 'alertToggle'].forEach(function(id) {
    document.getElementById(id).addEventListener('click', function() {
      this.classList.toggle('on');
      saveSettings();
    });
  });

  // Time/interval inputs
  ['patrolTime', 'alertInterval'].forEach(function(id) {
    document.getElementById(id).addEventListener('change', function() {
      saveSettings();
    });
  });

  loadSettings();
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
      document.getElementById('infoLine').textContent = state.operator + ' — ' + brandNames.length + '个品牌';
    } catch(e) {
      document.getElementById('infoLine').textContent = state.operator;
    }

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
    if (this.dataset.action === 'stop') {
      stopPatrol();
    } else {
      startPatrol();
    }
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
