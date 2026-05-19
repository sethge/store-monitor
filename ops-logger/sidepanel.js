/* sidepanel.js — 小q侧边栏聊天 */

var SERVER_URL = '';
var chatHistory = [];
var isThinking = false;

// ========== Server discovery ==========

async function discoverServer() {
  try {
    var data = await chrome.storage.local.get('ops_server_url');
    if (data.ops_server_url) SERVER_URL = data.ops_server_url;
  } catch(e) {}
  if (!SERVER_URL) SERVER_URL = 'http://127.0.0.1:5500';
}

async function checkServer() {
  if (!SERVER_URL) await discoverServer();
  try {
    var res = await fetch(SERVER_URL + '/health', { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      setStatus('ok', '已连接');
      return true;
    }
  } catch(e) {}
  setStatus('off', '服务未启动');
  return false;
}

function setStatus(state, text) {
  var dot = document.getElementById('statusDot');
  var txt = document.getElementById('statusText');
  dot.className = 'status-dot ' + state;
  txt.textContent = text;
}

// ========== Chat ==========

function addMsg(role, content, extra) {
  var area = document.getElementById('chatArea');
  var welcome = document.getElementById('welcome');
  if (welcome) welcome.style.display = 'none';

  var div = document.createElement('div');
  div.className = 'msg ' + role;

  if (role === 'bot' && extra) {
    div.innerHTML = formatMsg(content) + '<div class="tool-call">' + esc(extra) + '</div>';
  } else {
    div.innerHTML = formatMsg(content);
  }

  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div;
}

function formatMsg(text) {
  if (!text) return '';
  // Basic markdown-like formatting
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:12px;">$1</code>');
}

function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function showThinking() {
  var area = document.getElementById('chatArea');
  var div = document.createElement('div');
  div.className = 'thinking-indicator';
  div.id = 'thinking';
  div.innerHTML = '<span></span><span></span><span></span>';
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function hideThinking() {
  var el = document.getElementById('thinking');
  if (el) el.remove();
}

function sendQuick(text) {
  document.getElementById('input').value = text;
  sendMsg();
}

async function sendMsg() {
  var input = document.getElementById('input');
  var text = input.value.trim();
  if (!text || isThinking) return;

  input.value = '';
  input.style.height = 'auto';
  addMsg('user', text);

  // Get operator name
  var opData = await chrome.storage.local.get('ops_operator');
  var operator = opData.ops_operator || '';

  chatHistory.push({ role: 'user', content: text });

  isThinking = true;
  document.getElementById('sendBtn').disabled = true;
  setStatus('thinking', '思考中...');
  showThinking();

  try {
    if (!SERVER_URL) await discoverServer();
    var res = await fetch(SERVER_URL + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        operator: operator,
        history: chatHistory.slice(-20)  // last 20 messages for context
      })
    });

    hideThinking();

    if (!res.ok) {
      var errText = await res.text();
      addMsg('error', '服务出错: ' + res.status);
      setStatus('off', '出错了');
      isThinking = false;
      document.getElementById('sendBtn').disabled = false;
      return;
    }

    var data = await res.json();
    var reply = data.reply || '(没有回复)';
    var toolInfo = data.tools_used ? data.tools_used.join(' → ') : '';

    chatHistory.push({ role: 'assistant', content: reply });
    addMsg('bot', reply, toolInfo);
    setStatus('ok', '已连接');

  } catch(e) {
    hideThinking();
    addMsg('error', '无法连接服务: ' + e.message);
    setStatus('off', '连接失败');
  }

  isThinking = false;
  document.getElementById('sendBtn').disabled = false;
}

// ========== Auto-resize textarea ==========

document.getElementById('input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

// ========== Init ==========

discoverServer().then(checkServer);
setInterval(checkServer, 30000);
