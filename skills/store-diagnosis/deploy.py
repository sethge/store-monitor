#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析报告 → 上传腾讯云COS → 返回公网链接
同时保存JSON数据到本地（积累店铺数据库）
用法: python3 deploy.py --data /tmp/competitor_data.json
输出: 公网链接
"""
import argparse, json, os, sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
TEMPLATE = SCRIPT_DIR / "web" / "index.html"
DATA_DIR = SCRIPT_DIR.parent.parent / "memory" / "diagnosis"

# 腾讯云 COS 配置
COS_BUCKET = "11-store-report-1255918156"
COS_REGION = "ap-shanghai"


def _load_cos_keys():
    """从内置配置或环境变量获取腾讯云密钥"""
    import re, base64
    # 复用 gemini_ocr.py 里的配置
    gemini_ocr = SCRIPT_DIR / "gemini_ocr.py"
    if gemini_ocr.exists():
        content = gemini_ocr.read_text()
        m = re.search(r'_DEFAULT_CFG\s*=\s*"([^"]+)"', content)
        if m:
            cfg = json.loads(base64.b64decode(m.group(1)).decode())
            return cfg.get('tencent_secret_id'), cfg.get('tencent_secret_key')
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        cfg = json.load(open(config_path))
        return cfg.get('tencent_secret_id'), cfg.get('tencent_secret_key')
    return os.environ.get('TENCENT_SECRET_ID'), os.environ.get('TENCENT_SECRET_KEY')


def upload_to_cos(html_content, filename):
    """上传HTML到腾讯云COS（纯requests，不依赖SDK）"""
    import hashlib, hmac, time
    import requests

    sid, skey = _load_cos_keys()
    if not sid or not skey:
        return None

    from urllib.parse import quote
    key = f"reports/{filename}"
    encoded_key = quote(key, safe='/')
    host = f"{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com"
    url = f"https://{host}/{encoded_key}"

    # 腾讯云签名 v5（uri必须用编码后的，和实际请求一致）
    now = int(time.time())
    sign_time = f"{now - 60};{now + 3600}"
    http_method = "put"
    http_uri = f"/{encoded_key}"

    # 签名
    sign_key = hmac.new(skey.encode(), sign_time.encode(), hashlib.sha1).hexdigest()
    http_params = ""
    http_headers = f"content-type={requests.utils.quote('text/html; charset=utf-8', safe='')}&host={requests.utils.quote(host, safe='')}"
    sha1_params = hashlib.sha1(http_params.encode()).hexdigest()
    sha1_headers = hashlib.sha1(http_headers.encode()).hexdigest()
    format_str = "{}\n{}\n{}\n{}\n".format(http_method, http_uri, http_params, http_headers)
    string_to_sign = "sha1\n{}\n{}\n".format(sign_time, hashlib.sha1(format_str.encode()).hexdigest())
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()

    auth = (f"q-sign-algorithm=sha1&q-ak={sid}&q-sign-time={sign_time}"
            f"&q-key-time={sign_time}&q-header-list=content-type;host"
            f"&q-url-param-list=&q-signature={signature}")

    # 绕过代理上传
    session = requests.Session()
    session.trust_env = False
    resp = session.put(url, data=html_content.encode('utf-8'), headers={
        'Host': host,
        'Content-Type': 'text/html; charset=utf-8',
        'Authorization': auth,
    }, timeout=30)

    if resp.status_code in (200, 204):
        # 返回静态网站域名（浏览器直接渲染），上传用的是普通API域名
        website_host = f"{COS_BUCKET}.cos-website.{COS_REGION}.myqcloud.com"
        return f"https://{website_host}/{encoded_key}"
    else:
        print(f"  上传失败: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return None


def save_local(competitors, filename):
    """保存JSON数据到本地（积累店铺数据库）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_file = DATA_DIR / filename
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(competitors, f, ensure_ascii=False, indent=2)
    return str(data_file)


def main():
    parser = argparse.ArgumentParser(description='生成竞对分析报告')
    parser.add_argument('--data', required=True, help='竞对JSON数据（文件路径或内联JSON）')
    args = parser.parse_args()

    if os.path.exists(args.data):
        with open(args.data, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.loads(args.data)

    competitors = data if isinstance(data, list) else data.get('competitors', data.get('竞对', [data]))
    if not competitors:
        print("错误: 无竞对数据", file=sys.stderr)
        sys.exit(1)

    # 读模板 + 嵌入数据
    template_html = TEMPLATE.read_text(encoding='utf-8')
    json_str = json.dumps(competitors, ensure_ascii=False, indent=2)
    embedded_html = template_html.replace(
        'const COMPETITORS = loadData();',
        f'const COMPETITORS = {json_str};'
    )

    # CDN 换国内源（jsdelivr国内不稳定）
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net', 'https://unpkg.com'
    )

    # 文件名（纯ASCII，避免中文URL在微信/浏览器里出问题）
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    import hashlib
    shop_names = [c.get('店铺名称', '竞对') for c in competitors[:3]]
    name_str = '+'.join(shop_names)[:30]
    name_hash = hashlib.md5(name_str.encode()).hexdigest()[:8]
    filename = f"report_{name_hash}_{ts}.html"

    # 1. 保存本地数据（中文名方便辨认）
    local_filename = "{}_{}.json".format(name_str, ts)
    local_path = save_local(competitors, local_filename)
    print(f"  数据已保存: {local_path}", file=sys.stderr)

    # 2. 上传 COS
    print(f"  上传报告...", file=sys.stderr)
    url = upload_to_cos(embedded_html, filename)

    if url:
        print(url)
        print(f"  ✅ 报告已上传", file=sys.stderr)
    else:
        # COS 失败，保存到桌面兜底
        desktop_path = os.path.expanduser(f"~/Desktop/竞对分析_{filename}")
        with open(desktop_path, 'w', encoding='utf-8') as f:
            f.write(embedded_html)
        print(desktop_path)
        print(f"  ⚠ 上传失败，报告已保存到桌面", file=sys.stderr)


if __name__ == '__main__':
    main()
