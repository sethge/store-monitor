#!/bin/bash
# Ops Logger Keep-Alive: server + tunnel + OSS publish
# 由 launchd 管理，开机自启，挂了自动重启

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

LOG="/tmp/ops-logger-keepalive.log"
echo "$(date) [keep-alive] starting..." >> "$LOG"

# 1. 启动 server（如果没在跑）
if ! curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
  lsof -i :5500 -t | xargs kill -9 2>/dev/null
  sleep 1
  /opt/homebrew/bin/python3 "$DIR/server.py" &
  SERVER_PID=$!
  echo "$(date) [keep-alive] server started, PID=$SERVER_PID" >> "$LOG"
  sleep 2
  if ! curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "$(date) [keep-alive] ERROR: server failed to start" >> "$LOG"
    exit 1
  fi
else
  echo "$(date) [keep-alive] server already running" >> "$LOG"
fi

# 2. 启动 tunnel
pkill -f "cloudflared tunnel.*5500" 2>/dev/null
sleep 1
rm -f /tmp/cf_tunnel.log
cloudflared tunnel --url http://127.0.0.1:5500 > /tmp/cf_tunnel.log 2>&1 &
TUNNEL_PID=$!
echo "$(date) [keep-alive] tunnel started, PID=$TUNNEL_PID" >> "$LOG"

# 等 tunnel URL 出现
TUNNEL_URL=""
for i in $(seq 1 30); do
  TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cf_tunnel.log 2>/dev/null | head -1)
  if [ -n "$TUNNEL_URL" ]; then
    break
  fi
  sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
  echo "$(date) [keep-alive] ERROR: tunnel failed to get URL" >> "$LOG"
  exit 1
fi
echo "$(date) [keep-alive] tunnel URL: $TUNNEL_URL" >> "$LOG"

# 3. 发布 URL 到 OSS
/opt/homebrew/bin/python3 -c "
import oss2, json, datetime
import os
import pathlib
_env = dict(l.strip().split('=',1) for l in pathlib.Path(os.path.expanduser('~/Downloads/wp-automation/.env')).read_text().splitlines() if '=' in l and not l.startswith('#'))
ak = os.environ.get('OSS_ACCESS_KEY_ID', _env.get('OSS_ACCESS_KEY', ''))
sk = os.environ.get('OSS_ACCESS_KEY_SECRET', _env.get('OSS_ACCESS_SECRET', ''))
auth = oss2.Auth(ak, sk)
session = oss2.Session()
session.session.trust_env = False
bucket = oss2.Bucket(auth, 'http://oss-cn-hangzhou.aliyuncs.com', 'meihu-video', session=session)
data = json.dumps({'url': '$TUNNEL_URL', 'updated': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')})
bucket.put_object('tools/ops-logger-server.json', data, headers={'Content-Type': 'application/json'})
print('Published to OSS')
" >> "$LOG" 2>&1

echo "$(date) [keep-alive] all good, watching tunnel..." >> "$LOG"

# 4. 守护循环：每60秒检查 tunnel 是否还活着
while true; do
  sleep 60
  if ! kill -0 $TUNNEL_PID 2>/dev/null; then
    echo "$(date) [keep-alive] tunnel died, restarting..." >> "$LOG"
    # tunnel 挂了，重新启动
    rm -f /tmp/cf_tunnel.log
    cloudflared tunnel --url http://127.0.0.1:5500 > /tmp/cf_tunnel.log 2>&1 &
    TUNNEL_PID=$!

    # 等新 URL
    NEW_URL=""
    for i in $(seq 1 30); do
      NEW_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cf_tunnel.log 2>/dev/null | head -1)
      if [ -n "$NEW_URL" ]; then break; fi
      sleep 1
    done

    if [ -n "$NEW_URL" ] && [ "$NEW_URL" != "$TUNNEL_URL" ]; then
      TUNNEL_URL="$NEW_URL"
      echo "$(date) [keep-alive] new tunnel URL: $TUNNEL_URL, publishing..." >> "$LOG"
      /opt/homebrew/bin/python3 -c "
import oss2, json, datetime
import os
import pathlib
_env = dict(l.strip().split('=',1) for l in pathlib.Path(os.path.expanduser('~/Downloads/wp-automation/.env')).read_text().splitlines() if '=' in l and not l.startswith('#'))
ak = os.environ.get('OSS_ACCESS_KEY_ID', _env.get('OSS_ACCESS_KEY', ''))
sk = os.environ.get('OSS_ACCESS_KEY_SECRET', _env.get('OSS_ACCESS_SECRET', ''))
auth = oss2.Auth(ak, sk)
session = oss2.Session()
session.session.trust_env = False
bucket = oss2.Bucket(auth, 'http://oss-cn-hangzhou.aliyuncs.com', 'meihu-video', session=session)
data = json.dumps({'url': '$TUNNEL_URL', 'updated': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')})
bucket.put_object('tools/ops-logger-server.json', data, headers={'Content-Type': 'application/json'})
" >> "$LOG" 2>&1
    fi
  fi

  # 也检查 server
  if ! curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "$(date) [keep-alive] server down, restarting..." >> "$LOG"
    lsof -i :5500 -t | xargs kill -9 2>/dev/null
    sleep 1
    /opt/homebrew/bin/python3 "$DIR/server.py" &
    sleep 2
  fi

  # 检查 Chrome debug 端口
  if ! curl --noproxy localhost -s --max-time 2 http://localhost:9222/json/version > /dev/null 2>&1; then
    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if [ -f "$CHROME" ] && ! pgrep -f "remote-debugging-port=9222" > /dev/null 2>&1; then
      echo "$(date) [keep-alive] Chrome debug port down, restarting..." >> "$LOG"
      pkill -f "Google Chrome" 2>/dev/null
      sleep 2
      "$CHROME" --remote-debugging-port=9222 --no-first-run --no-default-browser-check --proxy-server="direct://" > /dev/null 2>&1 &
      sleep 3
    fi
  fi
done
