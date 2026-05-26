/* popup.js — 小q助手 三Tab面板: 巡店/预警 | 调整/复盘 | 交流/反馈 */

var SERVER_URL = 'http://127.0.0.1:5500';
var MY_SHOPS = []; // 当前运营名下的店铺名列表
var _dismissedAlerts = {}; // 已dismiss的预警key -> timestamp
var _currentOperator = ''; // cached operator name

function esc(s) { return (s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function platformUrl(platform, alertType) {
  if (platform === 'meituan' || platform === '美团') {
    if (alertType === 'bad_review') return 'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw';
    if (alertType === 'notice') return 'https://e.waimai.meituan.com/new_fe/business_gw#/msgbox';
    if (alertType === 'promo') return 'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc';
    return 'https://e.waimai.meituan.com/';
  }
  if (platform === 'eleme' || platform === '饿了么') {
    return 'https://melody.shop.ele.me/';
  }
  return '';
}

function openUrl(url) {
  if (url) chrome.tabs.create({ url: url });
}

// 切cookie后再跳转到对应店铺页面
async function openStoreUrl(url, storeName, platform) {
  if (!url) return;
  if (!storeName) { openUrl(url); return; }
  try {
    var resp = await api('/api/store-cookies?store=' + encodeURIComponent(storeName) + '&platform=' + encodeURIComponent(platform || ''));
    if (resp && resp.cookies && resp.cookies.length > 0) {
      // 确定目标域名
      var domain = '.waimai.meituan.com';
      if (platform === 'eleme' || platform === '饿了么') domain = '.ele.me';
      // 批量设置cookie
      var promises = [];
      for (var i = 0; i < resp.cookies.length; i++) {
        var c = resp.cookies[i];
        var cookieDomain = c.domain || domain;
        var cookieUrl = 'https://' + cookieDomain.replace(/^\./, '');
        promises.push(chrome.cookies.set({
          url: cookieUrl,
          name: c.name,
          value: c.value,
          domain: cookieDomain,
          path: c.path || '/',
          secure: c.secure !== false,
          httpOnly: c.httpOnly || false,
          sameSite: c.sameSite === 'None' ? 'no_restriction' : (c.sameSite === 'Lax' ? 'lax' : 'unspecified')
        }));
      }
      await Promise.all(promises);
    }
  } catch(e) {
    console.warn('[popup] cookie switch failed:', e);
  }
  // 无论cookie切换成功与否都跳转
  chrome.tabs.create({ url: url });
}

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

// ========== Helpers ==========

async function refreshServerStatus(containerId) {
  var el = document.getElementById(containerId);
  if (!el) return;
  var serverOk = false;
  try {
    var res = await fetch(SERVER_URL + '/health', { signal: AbortSignal.timeout(2000) });
    serverOk = res.ok;
  } catch(e) {}
  el.innerHTML = serverOk
    ? '<span style="color:#2e7d32">\u25CF 服务运行中</span>'
    : '<span style="color:#c62828">\u25CF 服务未启动</span>';
}

function buildInfoModule(data, settings, agentStatus) {
  // Line 1: 最近巡检 + 最近预警
  var line1 = '';
  if (data && data._running) {
    line1 = '\u23F3 巡检中 ' + (data._done || 0) + '/' + (data._total || '?') + ' 品牌';
  } else {
    var parts1 = [];
    var patrolTs = (agentStatus && agentStatus.last_patrol) || (data && data.ts) || '';
    var alertTs = (agentStatus && agentStatus.last_alert) || '';
    if (patrolTs) parts1.push('\u5DE1\u5E97 ' + esc(patrolTs));
    if (alertTs) parts1.push('\u9884\u8B66 ' + esc(alertTs));
    line1 = parts1.length > 0 ? parts1.join(' \u00B7 ') : '尚未巡检';
  }

  // Line 2: schedule info
  var parts = [];
  if (settings.patrol_enabled) {
    parts.push('每天' + (settings.patrol_time || '10:00') + '巡店');
  }
  if (settings.alert_enabled) {
    parts.push('每' + (settings.alert_interval || 10) + '分钟预警');
  }
  var line2 = parts.length > 0 ? parts.join(' \u00B7 ') : '定时巡检和预警未开启';

  return '<div class="info-module">' +
    '<div class="info-summary">' +
      '<div class="info-text">' +
        '<div>' + line1 + '</div>' +
        '<div class="schedule">' + line2 + '</div>' +
      '</div>' +
      '<button class="info-toggle" id="infoToggleBtn">\u2699</button>' +
    '</div>' +
    '<div class="info-settings" id="infoSettings" style="display:none">' +
      '<div class="setting-row">' +
        '<span class="setting-label">定时巡检</span>' +
        '<input class="setting-input" id="patrolTime" type="time" value="' + (settings.patrol_time || '10:00') + '" />' +
        '<button class="toggle-switch' + (settings.patrol_enabled ? ' on' : '') + '" id="patrolToggle" style="width:42px;height:20px">' +
          '<span class="toggle-text on-text" style="font-size:8px;left:4px">开</span>' +
          '<span class="toggle-text off-text" style="font-size:8px;right:4px">关</span>' +
          '<span class="toggle-knob" style="width:16px;height:16px"></span>' +
        '</button>' +
      '</div>' +
      '<div class="setting-row">' +
        '<span class="setting-label">实时预警</span>' +
        '<input class="setting-input" id="alertInterval" type="number" value="' + (settings.alert_interval || 10) + '" min="5" max="120" />' +
        '<span class="setting-unit">分钟</span>' +
        '<button class="toggle-switch' + (settings.alert_enabled ? ' on' : '') + '" id="alertToggle" style="width:42px;height:20px">' +
          '<span class="toggle-text on-text" style="font-size:8px;left:4px">开</span>' +
          '<span class="toggle-text off-text" style="font-size:8px;right:4px">关</span>' +
          '<span class="toggle-knob" style="width:16px;height:16px"></span>' +
        '</button>' +
      '</div>' +
      '<div class="server-status" id="infoServerStatus"></div>' +
    '</div>' +
  '</div>';
}

function initInfoModule() {
  var toggleBtn = document.getElementById('infoToggleBtn');
  var settings = document.getElementById('infoSettings');
  if (toggleBtn && settings) {
    toggleBtn.addEventListener('click', function() {
      var open = settings.style.display !== 'none';
      settings.style.display = open ? 'none' : 'block';
      toggleBtn.style.color = open ? '#bbb' : '#e94560';
      // 关闭设置面板时刷新显示（让修改后的时间/间隔立刻生效）
      if (open) loadDaily();
    });
  }
  // Bind setting controls
  ['patrolToggle', 'alertToggle'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', function() { this.classList.toggle('on'); saveSettings(); });
  });
  ['patrolTime', 'alertInterval'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('change', function() { saveSettings(); });
  });
  refreshServerStatus('infoServerStatus');
}

// ========== Tab 1: Merged Patrol + Alerts ==========

async function loadDaily() {
  var el = document.getElementById('tab-daily');

  // Load data in parallel
  var dailyPromise = api('/api/daily');
  var alertsPromise = api('/api/alerts');
  var settingsPromise = loadSettingsFromServer();
  var statusPromise = api('/api/agent/status');
  var data = await dailyPromise;
  var alertsData = await alertsPromise;
  var settings = await settingsPromise;
  var agentStatus = await statusPromise;

  var html = '';

  // === 1. Info module (skip rebuild when settings panel is open) ===
  var _settingsOpen = false;
  var _existingSettings = document.getElementById('infoSettings');
  if (_existingSettings && _existingSettings.style.display !== 'none') {
    _settingsOpen = true;
    // Keep existing info module HTML intact
    var _infoEl = _existingSettings.closest('.info-module');
    if (_infoEl) html += _infoEl.outerHTML;
    else html += buildInfoModule(data, settings, agentStatus);
  } else {
    html += buildInfoModule(data, settings, agentStatus);
  }

  // === 2. Persistent notice bar (auth + error, not dismissable) ===
  var allAlerts = alertsData || [];
  var authAlerts = allAlerts.filter(function(a) { return a.type === 'auth'; });
  var errorAlerts = allAlerts.filter(function(a) { return a.type === 'error'; });
  if (authAlerts.length > 0 || errorAlerts.length > 0) {
    html += '<div class="auth-notice">';
    if (authAlerts.length > 0) {
      html += '<div class="auth-notice-title">\u26A0\uFE0F ' + authAlerts.length + '家店未授权</div>';
      for (var ai = 0; ai < authAlerts.length; ai++) {
        var aa = authAlerts[ai];
        var pname = aa.platform === 'eleme' ? '饿了么' : aa.platform === 'meituan' ? '美团' : aa.platform || '';
        html += '<div class="auth-notice-item">' + esc(aa.store) + ' \u00B7 ' + esc(pname) + '</div>';
      }
    }
    if (errorAlerts.length > 0) {
      html += '<div class="auth-notice-title" style="color:#c62828">\u274C ' + errorAlerts.length + '家店检查出错</div>';
      for (var ei = 0; ei < errorAlerts.length; ei++) {
        var ea = errorAlerts[ei];
        html += '<div class="auth-notice-item" style="color:#b71c1c">' + esc(ea.store) + (ea.msg ? ' \u00B7 ' + esc(ea.msg) : '') + '</div>';
      }
    }
    html += '</div>';
  }

  // === 3. Alerts section (un-dismissed, excluding auth & error) ===
  var dismissed = _dismissedAlerts || {};
  var activeAlerts = allAlerts.filter(function(a) {
    if (a.type === 'auth' || a.type === 'error') return false;
    var key = (a.store||'') + '|' + (a.type||'') + '|' + (a.msg||'');
    return !dismissed[key];
  });
  updateBadge('alertBadge', activeAlerts.length);

  if (activeAlerts.length > 0) {
    html += '<div class="alert-section-title">\uD83D\uDD14 预警 ' + activeAlerts.length + '条</div>';

    // 预警按店铺分组
    var normalAlerts = activeAlerts;
    var byStore = {};
    var storeOrder = [];
    for (var i = 0; i < normalAlerts.length; i++) {
      var a = normalAlerts[i];
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
        var akey = (a.store||'') + '|' + (a.type||'') + '|' + (a.msg||'');
        var aUrl = platformUrl(a.platform, a.type);
        html += '<div class="alert-row alert-dismissable" data-alert-key="' + esc(akey) + '"' +
          (aUrl ? ' data-url="' + esc(aUrl) + '" data-store="' + esc(a.store||'') + '" data-platform="' + esc(a.platform||'') + '" style="cursor:pointer"' : '') + '>' +
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

  // === 3. Patrol results ===
  if (data && data.stores && data.stores.length > 0) {
    if (activeAlerts.length > 0) {
      html += '<div class="section-title" style="margin-top:6px">巡检详情</div>';
    }

    var groups = data.brands_grouped || [];
    if (groups.length === 0 && data.stores.length > 0) {
      groups = [{ brand: '', stores: data.stores }];
    }

    // Helper: shorten store name by removing brand prefix
    function shortName(storeName, brandName) {
      if (!brandName) return storeName;
      // Remove brand prefix patterns: "品牌·店名" or "品牌（店名）"
      var bn = brandName.split('（')[0].split('(')[0];
      var sn = storeName;
      // Try removing "品牌·" prefix
      if (sn.indexOf(bn) === 0) {
        sn = sn.substring(bn.length);
        sn = sn.replace(/^[·\-\s]+/, '');
      }
      // Try removing "品牌(" prefix for eleme-style names
      if (!sn) sn = storeName;
      return sn || storeName;
    }

    // Helper: build compact platform status for one platform
    function platformStatus(p, storeName) {
      var pPlat = p.platform === '美团' ? 'meituan' : 'eleme';
      var pCls = p.platform === '美团' ? 'p-mt' : 'p-ele';
      var pUrl = platformUrl(pPlat);
      var pTag = '<span class="' + pCls + ' p-link" data-url="' + esc(pUrl) + '" data-store="' + esc(storeName||'') + '" data-platform="' + esc(pPlat) + '" style="cursor:pointer">' + (p.platform === '美团' ? '美' : '饿') + '</span>';
      if (p.has_auth_issue) return pTag + '<span class="ps-bad">未授权</span>';
      var parts = [];
      if (p.bad_review_count > 0) parts.push('<span class="ps-bad">' + p.bad_review_count + '差评</span>');
      if (p.expiring_count > 0) parts.push('<span class="ps-warn">' + p.expiring_count + '到期</span>');
      if (p.promo_balance !== null && p.promo_balance !== undefined && p.promo_daily_spend > 0) {
        var dl = p.promo_balance / p.promo_daily_spend;
        if (dl < 3) parts.push('<span class="ps-warn">推广' + dl.toFixed(0) + '天</span>');
      }
      if ((p.errors || []).length > 0) parts.push('<span class="ps-warn">出错</span>');
      if (p.notice_count > 0) parts.push('<span class="ps-info">' + p.notice_count + '通知</span>');
      if (parts.length === 0) return pTag + '<span class="ps-ok">\u2713</span>';
      return pTag + parts.join(' ');
    }

    for (var gi = 0; gi < groups.length; gi++) {
      var group = groups[gi];
      if (group.brand === '其他') continue;  // skip orphans
      var brandName = group.brand || '';

      // Count issues in this brand
      var brandIssueCount = 0;
      for (var si = 0; si < group.stores.length; si++) {
        var st = group.stores[si];
        for (var pi = 0; pi < st.platforms.length; pi++) {
          var pp = st.platforms[pi];
          if (pp.has_auth_issue || pp.bad_review_count > 0 || pp.expiring_count > 0 || (pp.errors||[]).length > 0 ||
              (pp.promo_balance !== null && pp.promo_daily_spend > 0 && pp.promo_balance / pp.promo_daily_spend < 3)) {
            brandIssueCount++;
          }
        }
      }

      // Brand header (short brand name, no parenthetical)
      var brandShort = brandName.split('（')[0].split('(')[0];
      var brandClass = brandIssueCount > 0 ? 'brand-card has-issues' : 'brand-card';
      html += '<div class="' + brandClass + '">';
      html += '<div class="brand-header-line">';
      html += '<span class="brand-name">' + esc(brandShort) + '</span>';
      if (brandIssueCount === 0) {
        html += '<span class="brand-ok">\u2713 正常</span>';
      }
      html += '</div>';

      // Only show store details if there are issues (or <=2 stores)
      if (brandIssueCount > 0 || group.stores.length <= 2) {
        for (var si = 0; si < group.stores.length; si++) {
          var store = group.stores[si];
          var sn = shortName(store.store, brandName);
          html += '<div class="store-line">';
          html += '<span class="store-short-name">' + esc(sn) + '</span>';
          html += '<span class="store-platforms">';
          for (var j = 0; j < store.platforms.length; j++) {
            html += platformStatus(store.platforms[j], store.store);
            if (j < store.platforms.length - 1) html += ' ';
          }
          html += '</span></div>';

          // Expand details for issues (bad reviews, activities, notices)
          for (var j = 0; j < store.platforms.length; j++) {
            var p = store.platforms[j];
            if (p.bad_review_count > 0 && p.bad_reviews && p.bad_reviews.length > 0) {
              for (var k = 0; k < p.bad_reviews.length && k < 2; k++) {
                var r = p.bad_reviews[k];
                html += '<div class="store-detail">' + r.stars + '\u2606 "' + esc((r.comment||'').substring(0,40)) + '"</div>';
              }
            }
            if (p.expiring_count > 0 && p.activities) {
              for (var k = 0; k < p.activities.length; k++) {
                var a = p.activities[k];
                html += '<div class="store-detail">' + esc(a.name) + ' ' + a.days_left + '\u5929\u5230\u671F</div>';
              }
            }
            if (p.notice_count > 0 && p.notices && p.notices.length > 0) {
              for (var k = 0; k < p.notices.length && k < 3; k++) {
                var n = p.notices[k];
                html += '<div class="store-detail">' + esc((n.title||'').substring(0,40)) + '</div>';
              }
            }
          }
        }
      }
      html += '</div>';
    }
  } else if (activeAlerts.length === 0) {
    html += '<div class="empty">暂无巡检日报<br><span style="font-size:10px;color:#ccc">点击上方「巡检」按钮开始</span></div>';
  }

  el.innerHTML = html;
  initInfoModule();

  // Bind dismiss buttons
  el.querySelectorAll('.alert-dismissable').forEach(function(item) {
    var dismissBtn = item.querySelector('.dismiss-btn');
    if (dismissBtn) {
      dismissBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        var key = item.dataset.alertKey;
        _dismissedAlerts[key] = Date.now();
        try { chrome.storage.local.set({ dismissed_alerts: _dismissedAlerts }); } catch(e) {}
        item.style.transition = 'opacity 0.3s';
        item.style.opacity = '0';
        setTimeout(function() {
          item.remove();
          var remaining = el.querySelectorAll('.alert-dismissable').length;
          updateBadge('alertBadge', remaining);
        }, 300);
      });
    }
    // Click to open platform page (先切cookie到对应店铺)
    if (item.dataset.url) {
      item.addEventListener('click', function(e) {
        if (e.target.classList.contains('dismiss-btn')) return;
        openStoreUrl(item.dataset.url, item.dataset.store, item.dataset.platform);
      });
    }
  });

  // Bind platform tag clicks in patrol results (切cookie后跳转)
  el.querySelectorAll('.p-link').forEach(function(link) {
    link.addEventListener('click', function() {
      openStoreUrl(link.dataset.url, link.dataset.store, link.dataset.platform);
    });
  });
}

// ========== Tab 2: 调整/复盘 (Timeline) ==========

async function loadChanges() {
  var el = document.getElementById('tab-changes');

  var opData = await chrome.storage.local.get('ops_operator');
  var opName = opData.ops_operator || '';

  // Load logs + tracking in parallel
  var logsPromise = api('/api/logs?limit=50' + (opName ? '&operator=' + encodeURIComponent(opName) : ''));
  var trackUrl = '/api/tracking?limit=200' + (opName ? '&operator=' + encodeURIComponent(opName) : '');
  var trackPromise = api(trackUrl);
  var logs = await logsPromise;
  var trackData = await trackPromise;

  // Logs are already filtered by operator on the server side

  // Build tracking map: log_id -> { status, items[] }
  var trackMap = {};
  if (trackData) {
    for (var i = 0; i < trackData.length; i++) {
      var t = trackData[i];
      if (t.status === 'disabled') continue;
      if (!trackMap[t.log_id]) trackMap[t.log_id] = { items: [], bestStatus: 'pending' };
      trackMap[t.log_id].items.push(t);
      if (t.status === 'done') trackMap[t.log_id].bestStatus = 'done';
    }
  }

  if (!logs || logs.length === 0) {
    el.innerHTML = '<div class="timeline-empty">还没有操作记录<br><span style="font-size:10px;color:#ccc">在后台做调整后自动记录</span></div>';
    updateBadge('trackBadge', 0);
    return;
  }

  // Group by date -> store
  var byDate = {};
  var dateOrder = [];
  for (var i = 0; i < logs.length; i++) {
    var dk = dateKey(logs[i].timestamp);
    if (!byDate[dk]) { byDate[dk] = {}; dateOrder.push(dk); }
    var store = logs[i].shop_name || '未知店铺';
    if (!byDate[dk][store]) byDate[dk][store] = [];
    byDate[dk][store].push(logs[i]);
  }
  dateOrder.sort().reverse();

  var today = new Date().toISOString().slice(0, 10);
  var yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  var dueCount = 0;
  var html = '';

  for (var di = 0; di < dateOrder.length; di++) {
    var dk = dateOrder[di];
    var dayStores = byDate[dk];
    var changeCount = 0;
    Object.keys(dayStores).forEach(function(s) { changeCount += dayStores[s].length; });

    // Date header with status
    var daysDiff = Math.floor((new Date(today) - new Date(dk)) / 86400000);
    var statusIcon, statusText;
    if (daysDiff === 0) {
      statusIcon = '\u270F\uFE0F'; statusText = changeCount + '条调整已记录';
    } else if (daysDiff <= 2) {
      statusIcon = '\u23F3'; statusText = '数据收集中 T+' + daysDiff;
    } else {
      // Check if any tracking results are ready
      var hasResults = false;
      Object.keys(dayStores).forEach(function(s) {
        dayStores[s].forEach(function(l) {
          var tr = trackMap[l.id];
          if (tr && tr.bestStatus === 'done') hasResults = true;
          if (tr) {
            tr.items.forEach(function(item) {
              if (item.status === 'pending' && item.check_date <= today) dueCount++;
            });
          }
        });
      });
      if (hasResults) {
        statusIcon = '\uD83D\uDCCA'; statusText = '结果已出';
      } else {
        statusIcon = '\uD83D\uDCCA'; statusText = 'T+' + daysDiff + ' 待复盘';
      }
    }

    html += '<div class="timeline-date-header">' +
      '<span class="status-icon">' + statusIcon + '</span> ' +
      fmtDate(dk + 'T00:00:00') +
      ' <span class="status-text">' + statusText + '</span>' +
    '</div>';

    // Store groups
    var stores = Object.keys(dayStores);
    for (var si = 0; si < stores.length; si++) {
      var storeName = stores[si];
      var storeLogs = dayStores[storeName];

      html += '<div class="timeline-store-group">';
      html += '<div class="timeline-store-name">' + esc(storeName) + '</div>';

      for (var li = 0; li < storeLogs.length; li++) {
        var l = storeLogs[li];
        var sm = l.change_summary || l.action_detail || l.action_type || '';
        var pname = l.platform === 'eleme' ? '饿了么' : l.platform === 'meituan' ? '美团' : '';
        var tagCls = actionTagClass(l.action_type);

        html += '<div class="timeline-change">';
        html += '<div class="change-time">' + fmtHM(l.timestamp) + '</div>';
        html += '<div class="change-body">';
        html += '<div class="change-summary"><span class="tag ' + tagCls + '">' + esc(l.action_type || '操作') + '</span> ' + esc(sm) + '</div>';
        if (pname) html += '<div class="change-meta">' + esc(pname) + '</div>';

        // Show tracking result if available
        var tr = trackMap[l.id];
        if (tr) {
          for (var ti = 0; ti < tr.items.length; ti++) {
            var cp = tr.items[ti];
            var cpLabel = cp.check_type === '3day' ? 'T+3' : cp.check_type === '7day' ? 'T+7' : cp.check_type;
            if (cp.status === 'done' && cp.metrics_after) {
              html += '<div class="timeline-result">' + cpLabel + ': ' + esc(cp.metrics_after) + '</div>';
            } else if (cp.status === 'pending' && cp.check_date <= today) {
              html += '<div class="timeline-result due">' + cpLabel + ' (' + esc(cp.check_date) + ') 待复盘</div>';
            } else if (cp.status === 'pending') {
              html += '<div class="timeline-result waiting">' + cpLabel + ' ' + esc(cp.check_date) + ' 收集中</div>';
            }
          }
        }

        html += '</div>'; // change-body

        // Toggle for today's changes (追踪/关)
        if (daysDiff <= 1 && l.id) {
          var isTrackOn = tr ? true : false;
          // 检查是否被disabled了
          var disabledTr = trackData && trackData.find(function(t) { return t.log_id == l.id && t.status === 'disabled'; });
          if (tr || disabledTr) {
            html += '<div class="toggle-wrap">' +
              '<button class="toggle-switch' + (isTrackOn ? ' on' : '') + '" data-logid="' + l.id + '" data-enabled="' + (isTrackOn ? '1' : '0') + '">' +
                '<span class="toggle-text on-text">追踪</span>' +
                '<span class="toggle-text off-text">关</span>' +
                '<span class="toggle-knob"></span>' +
              '</button></div>';
          }
        }

        html += '</div>'; // timeline-change
      }

      // "展开聊聊" button for dates with results
      if (daysDiff >= 3) {
        html += '<button class="timeline-expand-btn" data-store="' + esc(storeName) + '" data-date="' + dk + '">展开聊聊</button>';
      }

      html += '</div>'; // timeline-store-group
    }
  }

  updateBadge('trackBadge', dueCount);
  el.innerHTML = html;

  // Bind toggle switches
  el.querySelectorAll('.toggle-switch').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var logId = parseInt(btn.dataset.logid);
      var isOn = btn.dataset.enabled === '1';
      btn.classList.toggle('on');
      btn.dataset.enabled = isOn ? '0' : '1';
      toggleTracking(logId, !isOn);
    });
  });

  // Bind "展开聊聊" buttons
  el.querySelectorAll('.timeline-expand-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var store = btn.dataset.store;
      var date = btn.dataset.date;
      // Switch to chat tab and send a question
      document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
      document.querySelector('[data-tab="chat"]').classList.add('active');
      document.getElementById('tab-chat').classList.add('active');
      document.getElementById('chatInput').value = store + ' ' + date + ' 的调整效果怎么样?';
      document.getElementById('chatInput').focus();
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

// ========== Tracking helpers ==========

async function closeCheckpoint(tid) {
  await apiPost('/api/tracking/' + tid + '/disable', {});
  loadChanges();
}

function toggleTracking(logId, enable) {
  var path = enable ? '/api/tracking/enable_log/' + logId : '/api/tracking/disable_log/' + logId;
  apiPost(path, {}).then(function() {
    loadChanges();
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
    // 巡检中实时刷新结果（巡一家出一家）
    loadDaily();
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
    var errText = (result && result.message) || '启动失败';
    msg.textContent = errText;
    msg.style.color = errText.indexOf('悟空') >= 0 ? '#c62828' : '';
    btn.disabled = false;
    btn.textContent = '重试';
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
        btn.textContent = '下载中...';
        chrome.tabs.create({ url: SERVER_URL + '/api/extension/download' });
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
  // Settings are now rendered directly in buildInfoModule with correct values
  // This function is kept for compatibility but no longer needed
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
    alert_interval: alertInterval ? parseInt(alertInterval.value) || 30 : (_cachedSettings.alert_interval || 10),
  };
  _cachedSettings = settings;
  try { chrome.storage.local.set({ ops_settings: settings }); } catch(e) {}
  apiPost('/api/settings', settings);
}

function initSettings() {
  // Settings are now integrated in the info module, initialized in initInfoModule()
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

// ========== Cold Start ==========

async function runColdStart(operatorName) {
  var setupDiv = document.getElementById('setup');
  var resultEl = document.getElementById('setupResult');
  var confirmBtn = document.getElementById('confirmBtn');
  confirmBtn.style.display = 'none';

  function step(num, text, status) {
    var colors = { ok: '#2e7d32', fail: '#c62828', wait: '#e65100', info: '#1565c0' };
    var icons = { ok: '\u2705', fail: '\u274C', wait: '\u23F3', info: '\u2139\uFE0F' };
    return '<div style="padding:4px 0;color:' + (colors[status]||'#333') + '">' + (icons[status]||'') + ' 第' + num + '步: ' + text + '</div>';
  }

  var html = '<div style="font-weight:600;margin-bottom:8px">' + esc(operatorName) + ' \u2014 \u521D\u59CB\u5316\u4E2D...</div>';

  // Step 1: 检查服务
  html += step(1, '\u68C0\u67E5\u670D\u52A1\u8FDE\u63A5...', 'wait');
  resultEl.innerHTML = html;

  await discoverServer();
  var serverOk = false;
  try {
    var res = await fetch(SERVER_URL + '/api/logs?limit=1');
    serverOk = res.ok;
  } catch(e) {}

  if (!serverOk) {
    html = html.replace('\u23F3 \u7B2C1\u6B65: \u68C0\u67E5\u670D\u52A1\u8FDE\u63A5...', '\u274C \u7B2C1\u6B65: \u670D\u52A1\u672A\u542F\u52A8\uFF0C\u8BF7\u8054\u7CFB\u7BA1\u7406\u5458');
    html += '<div style="color:#999;font-size:11px;margin-top:8px">\u670D\u52A1\u542F\u52A8\u540E\u91CD\u65B0\u6253\u5F00\u63D2\u4EF6\u5373\u53EF</div>';
    resultEl.innerHTML = html;
    return;
  }
  html = html.replace('\u23F3 \u7B2C1\u6B65: \u68C0\u67E5\u670D\u52A1\u8FDE\u63A5...', '\u2705 \u7B2C1\u6B65: \u670D\u52A1\u5DF2\u8FDE\u63A5');

  // Step 2: 检查debug Chrome + Goku插件
  html += step(2, '\u68C0\u67E5\u60A7\u7A7A\u63D2\u4EF6\u767B\u5F55...', 'wait');
  resultEl.innerHTML = html;

  var statusData = null;
  try {
    var sres = await fetch(SERVER_URL + '/api/agent/status');
    if (sres.ok) statusData = await sres.json();
  } catch(e) {}

  if (!statusData || !statusData.has_run_fast) {
    // 尝试自动启动debug Chrome
    try { await fetch(SERVER_URL + '/api/headless/refresh', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' }); } catch(e) {}
    html = html.replace('\u23F3 \u7B2C2\u6B65: \u68C0\u67E5\u60A7\u7A7A\u63D2\u4EF6\u767B\u5F55...', '\u2139\uFE0F \u7B2C2\u6B65: \u8BF7\u5728Chrome\u4E2D\u767B\u5F55\u60A7\u7A7A\u63D2\u4EF6\uFF0C\u767B\u5F55\u540E\u70B9\u201C\u5DF2\u767B\u5F55\u201D');
    html += '<button id="gokuDoneBtn" class="btn" style="margin-top:8px;background:#1565c0">\u5DF2\u767B\u5F55\u60A7\u7A7A</button>';
    resultEl.innerHTML = html;

    document.getElementById('gokuDoneBtn').addEventListener('click', async function() {
      this.disabled = true;
      this.textContent = '\u68C0\u67E5\u4E2D...';
      // 直接进入主界面，checkAgent会持续检测
      init();
    });
    return;
  }

  html = html.replace('\u23F3 \u7B2C2\u6B65: \u68C0\u67E5\u60A7\u7A7A\u63D2\u4EF6\u767B\u5F55...', '\u2705 \u7B2C2\u6B65: \u60A7\u7A7A\u63D2\u4EF6\u5DF2\u5C31\u7EEA');

  // Step 3: 一切就绪
  html += step(3, '\u4E00\u5207\u5C31\u7EEA\uFF0C\u70B9\u201C\u5DE1\u5E97\u201D\u5F00\u59CB\u5DE5\u4F5C', 'ok');
  resultEl.innerHTML = html;
  setTimeout(function() { init(); }, 1500);
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

  // 直接从storage读，不依赖background service worker（可能休眠）
  var data = await chrome.storage.local.get(['ops_operator']);
  var operator = data.ops_operator || '';

  if (!operator) {
    document.getElementById('setup').style.display = 'block';
    document.getElementById('main').style.display = 'none';
    return;
  }

  _currentOperator = operator;

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
    var storeCount = 0;
    brandNames.forEach(function(b) {
      var stores = brands[b] || [];
      storeCount += stores.length;
      stores.forEach(function(st) {
        (st.platforms || []).forEach(function(p) {
          if (p.shop) MY_SHOPS.push(p.shop);
        });
      });
    });
    document.getElementById('infoLine').textContent = operator + ' \u2014 ' + brandNames.length + '个品牌 ' + storeCount + '家店';
  } catch(e) {
    document.getElementById('infoLine').textContent = operator;
  }

  checkVersion();
  loadDaily();
  loadChanges();

  // 监听background推送日志成功，实时刷新操作记录
  chrome.runtime.onMessage.addListener(function(msg) {
    if (msg.type === 'OPS_LOGS_PUSHED') {
      loadChanges();
    }
  });

  // Load and render chat history
  var savedChat = await loadChatHistory();
  if (savedChat.length > 0) {
    chatHistory = savedChat;
    renderChatHistory(savedChat);
  }

  // 顺便唤醒background service worker
  chrome.runtime.sendMessage({ type: 'OPS_GET_STATE' }, function() {
    if (chrome.runtime.lastError) {}
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
    var totalStores = 0;
    brandNames.forEach(function(b) { totalStores += (brands[b] || []).length; });

    var html = '<div style="color:#2e7d32;font-weight:600;margin-bottom:6px">' + esc(name) + ' \u2014 ' + brandNames.length + '个品牌 ' + totalStores + '家店</div>';
    for (var i = 0; i < brandNames.length; i++) {
      var bname = brandNames[i];
      var stores = brands[bname] || [];
      html += '<div style="font-weight:600;margin-top:6px">' + esc(bname) + ' <span style="color:#999;font-weight:400">(' + stores.length + '家店)</span></div>';
      for (var j = 0; j < stores.length; j++) {
        var st = stores[j];
        var platforms = (st.platforms || []).map(function(p) {
          return p.p === 'meituan' ? '<span style="color:#cc6600">美团</span>' : '<span style="color:#0066cc">饿了么</span>';
        }).join(' ');
        html += '<div style="padding-left:8px;color:#666">' + esc(st.store) + ' ' + platforms + '</div>';
      }
    }
    resultEl.innerHTML = html;
    confirmBtn.style.display = 'block';
  });

  document.getElementById('confirmBtn').addEventListener('click', function() {
    if (!_pendingName) return;
    chrome.runtime.sendMessage({ type: 'OPS_SET_OPERATOR', name: _pendingName }, function() {
      if (!chrome.runtime.lastError) {
        chrome.storage.local.set({ ops_operator: _pendingName });
        apiPost('/api/settings', { operator: _pendingName });
        runColdStart(_pendingName);
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
    if (e.key === 'Enter' && !e.isComposing) sendMsg();
  });
  // Quick buttons
  document.querySelectorAll('.quick-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var text = btn.dataset.quick;
      if (text) sendQuick(text);
    });
  });

  // Refresh every 30s
  setInterval(function() {
    loadDaily();
    loadChanges();
    checkAgent();
  }, 30000);
});

// ========== Tab 5: Chat (会话) ==========

var chatHistory = [];
var chatThinking = false;

function addChatMsg(role, text, toolInfo) {
  var area = document.getElementById('chatArea');

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
