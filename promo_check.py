"""推广余额检查模块"""
import asyncio
import re
import statistics


def parse_promo_data(text):
    """从推广页面DOM文本解析余额和消费记录"""
    # 余额
    balance = 0.0
    m = re.search(r'账户余额\s*\n?\s*([\d.]+)\s*元', text)
    if not m:
        m = re.search(r'账户资金\s*\n?\s*([\d.]+)\s*元?', text)
    if m:
        balance = float(m.group(1))

    # 消费记录 — 匹配负数金额（消费行可能跨多行）
    # 美团格式: 一行里有"消费"和"-100.00"
    # 饿了么格式: "推广消费\n推广消费\n\t-0.20"跨行
    spends = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        m2 = re.search(r'^[\t\s]*-(\d+\.\d+)', line.strip())
        if m2:
            # 检查前几行有没有"消费"
            context = '\n'.join(lines[max(0,i-3):i+1])
            if '消费' in context:
                spends.append(float(m2.group(1)))

    return balance, spends[:5]


def check_promo(balance, recent5):
    """检查余额是否不足1天消费，返回 (需要提醒, 余额, 日消费中位数)"""
    if not recent5:
        return False, balance, 0
    median = statistics.median(recent5)
    if median <= 0:
        return False, balance, 0
    need_alert = balance / median < 1
    return need_alert, balance, median


async def scrape_mt_promo(page):
    """在美团推广页抓余额和消费记录"""
    await page.goto("https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc",
                     wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 等推广iframe加载完
    for _ in range(5):
        for f in page.frames:
            if 'ad' in f.url and 'waimaieapp' in f.url:
                text = await f.evaluate("() => document.body.innerText")
                if '我的账户' in text or '消费记录' in text:
                    # 点"消费记录"叶子节点
                    await f.evaluate("""() => {
                        document.querySelectorAll('*').forEach(el => {
                            if (el.textContent?.trim() === '消费记录' && el.children.length === 0 && el.offsetParent) {
                                el.click();
                            }
                        });
                    }""")
                    await asyncio.sleep(3)
                    text2 = await f.evaluate("() => document.body.innerText")
                    return parse_promo_data(text2)
        await asyncio.sleep(2)

    return 0, []


async def scrape_ele_promo(page):
    """在饿了么推广页抓余额和消费记录"""
    m = re.search(r'/shop/(\d+)/', page.url)
    shop_id = m.group(1) if m else ""

    await page.goto(f"https://melody.shop.ele.me/app/shop/{shop_id}/vas#app.shop.vas",
                     wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 在包含"消费记录"的frame里点击
    for f in page.frames:
        try:
            text = await f.evaluate("() => document.body.innerText")
            if '消费记录' not in text:
                continue
            # 点"消费记录"叶子节点
            await f.evaluate("""() => {
                document.querySelectorAll('*').forEach(el => {
                    if (el.textContent?.trim() === '消费记录' && el.children.length === 0 && el.offsetParent) {
                        el.click();
                    }
                });
            }""")
            await asyncio.sleep(3)
            text2 = await f.evaluate("() => document.body.innerText")
            if '消费' in text2 and '-' in text2:
                return parse_promo_data(text2)
        except:
            pass

    return 0, []
