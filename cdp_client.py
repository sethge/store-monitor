"""
原生 CDP 客户端 — 替代 playwright 的 connect_over_cdp
直接用 websocket 跟 Chrome DevTools Protocol 通信，不受版本限制。

用法:
    from cdp_client import CDPBrowser

    async with CDPBrowser(port=9222) as browser:
        pages = await browser.pages()
        page = pages[0]
        await page.goto("https://example.com")
        title = await page.evaluate("document.title")
"""
import asyncio
import json
import os
import subprocess
from urllib.request import urlopen


class CDPPage:
    """单个页面的 CDP 操作"""

    def __init__(self, ws_url, page_id, page_url, page_title):
        self.ws_url = ws_url
        self.id = page_id
        self.url = page_url
        self.title = page_title
        self._ws = None
        self._msg_id = 0
        self._responses = {}
        self._events = asyncio.Queue()
        self._listener_task = None

    async def connect(self):
        import websockets
        # 清掉代理
        saved = {}
        for k in list(os.environ.keys()):
            if 'proxy' in k.lower() and k not in ('NO_PROXY', 'no_proxy'):
                saved[k] = os.environ.pop(k)
        os.environ['NO_PROXY'] = '*'

        self._ws = await websockets.connect(self.ws_url, open_timeout=10, max_size=50 * 1024 * 1024)
        self._listener_task = asyncio.create_task(self._listen())

        # 恢复
        os.environ.update(saved)

    async def _listen(self):
        try:
            async for msg in self._ws:
                data = json.loads(msg)
                if 'id' in data:
                    self._responses[data['id']] = data
                else:
                    await self._events.put(data)
        except Exception:
            pass

    async def send(self, method, params=None):
        self._msg_id += 1
        msg_id = self._msg_id
        payload = {'id': msg_id, 'method': method}
        if params:
            payload['params'] = params
        await self._ws.send(json.dumps(payload))

        # 等待响应
        for _ in range(300):  # 30秒超时
            if msg_id in self._responses:
                resp = self._responses.pop(msg_id)
                if 'error' in resp:
                    raise RuntimeError(f"CDP错误: {resp['error']}")
                return resp.get('result', {})
            await asyncio.sleep(0.1)
        raise TimeoutError(f"CDP命令超时: {method}")

    async def goto(self, url, wait_until='load', timeout=30):
        """导航到URL"""
        await self.send('Page.enable')
        await self.send('Page.navigate', {'url': url})
        # 等页面加载
        for _ in range(timeout * 10):
            try:
                event = self._events.get_nowait()
                if event.get('method') == 'Page.loadEventFired':
                    break
            except asyncio.QueueEmpty:
                pass
            await asyncio.sleep(0.1)

    async def evaluate(self, expression):
        """执行 JavaScript"""
        result = await self.send('Runtime.evaluate', {
            'expression': expression,
            'returnByValue': True,
        })
        value = result.get('result', {}).get('value')
        return value

    async def query_selector(self, selector):
        """查询 DOM 元素"""
        result = await self.evaluate(f"document.querySelector('{selector}') ? true : false")
        return result

    async def click(self, selector):
        """点击元素"""
        await self.evaluate(f"document.querySelector('{selector}').click()")

    async def wait_for_selector(self, selector, timeout=30):
        """等待元素出现"""
        for _ in range(timeout * 10):
            exists = await self.query_selector(selector)
            if exists:
                return True
            await asyncio.sleep(0.1)
        raise TimeoutError(f"等待元素超时: {selector}")

    async def content(self):
        """获取页面 HTML"""
        return await self.evaluate("document.documentElement.outerHTML")

    async def wait_for_load_state(self, state='load', timeout=30):
        """等待页面加载完成"""
        for _ in range(timeout * 10):
            ready = await self.evaluate("document.readyState")
            if ready == 'complete' or (state == 'domcontentloaded' and ready in ('interactive', 'complete')):
                return
            await asyncio.sleep(0.1)

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self._ws:
            await self._ws.close()


class CDPBrowser:
    """浏览器级 CDP 操作"""

    def __init__(self, port=9222):
        self.port = port
        self._pages = []

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        for p in self._pages:
            await p.close()

    async def connect(self):
        """连接到 Chrome 调试端口"""
        r = subprocess.run(
            ['curl', '--noproxy', 'localhost', '-s', f'http://localhost:{self.port}/json'],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            raise RuntimeError(f"Chrome调试端口 {self.port} 未响应")
        self._targets = json.loads(r.stdout)

    async def pages(self):
        """获取所有页面"""
        result = []
        for t in self._targets:
            if t.get('type') == 'page' and 'webSocketDebuggerUrl' in t:
                page = CDPPage(
                    ws_url=t['webSocketDebuggerUrl'],
                    page_id=t.get('id'),
                    page_url=t.get('url', ''),
                    page_title=t.get('title', ''),
                )
                await page.connect()
                result.append(page)
        self._pages = result
        return result

    async def new_page(self, url='about:blank'):
        """新建页面"""
        r = subprocess.run(
            ['curl', '--noproxy', 'localhost', '-s',
             f'http://localhost:{self.port}/json/new?{url}'],
            capture_output=True, text=True, timeout=5
        )
        target = json.loads(r.stdout)
        page = CDPPage(
            ws_url=target['webSocketDebuggerUrl'],
            page_id=target.get('id'),
            page_url=target.get('url', ''),
            page_title=target.get('title', ''),
        )
        await page.connect()
        self._pages.append(page)
        return page
