#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析报告 → 上传COS在线访问 + 运营下载Excel时自动回传数据
用法: python3 deploy.py --data /tmp/competitor_data.json
输出: 在线URL
"""
import argparse, json, os, sys, requests
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
TEMPLATE = SCRIPT_DIR / "web" / "index.html"

# COS配置（从config.json读取）
def _load_cos_config():
    cfg_path = SCRIPT_DIR / "config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return json.load(f)
    return {}

_COS_CFG = _load_cos_config()
COS_BUCKET = _COS_CFG.get('cos_bucket', '')
COS_REGION = _COS_CFG.get('cos_region', '')
COS_SECRET_ID = _COS_CFG.get('tencent_secret_id', '')
COS_SECRET_KEY = _COS_CFG.get('tencent_secret_key', '')
COS_BASE_URL = 'https://{}.cos-website.{}.myqcloud.com'.format(COS_BUCKET, COS_REGION)


def _cos_client():
    from qcloud_cos import CosConfig, CosS3Client
    config = CosConfig(Region=COS_REGION, SecretId=COS_SECRET_ID, SecretKey=COS_SECRET_KEY)
    client = CosS3Client(config)
    # 绕过代理
    session = requests.Session()
    session.trust_env = False
    client._session = session
    return client


def upload_cos(client, key, body, content_type='text/html; charset=utf-8'):
    client.put_object(
        Bucket=COS_BUCKET,
        Key=key,
        Body=body if isinstance(body, bytes) else body.encode('utf-8'),
        ContentType=content_type,
        ContentDisposition='inline',
    )
    return '{}/{}'.format(COS_BASE_URL, key)


def presign_put(client, key, expire=7*86400):
    """生成预签名PUT URL，有效期7天"""
    return client.get_presigned_url(
        Method='PUT',
        Bucket=COS_BUCKET,
        Key=key,
        Expired=expire,
    )


def is_test_data(competitors):
    """过滤测试脏数据：店名乱写、关键字段缺失、数据明显不真实"""
    if not competitors:
        return True
    junk_names = {'测试', 'test', '竞对', 'xxx', '123', 'aaa', '哈哈', '啊啊', '随便'}
    for c in competitors:
        name = c.get('店铺名称', '').strip()
        # 店名太短或明显乱写
        if len(name) < 3 or name.lower() in junk_names:
            return True
        # 店名全是重复字符
        if len(set(name)) <= 1:
            return True
        # 没有任何有效业务数据
        has_data = any(c.get(k) for k in ['店铺评分', '月销', '满减档位', '热销菜'])
        if not has_data:
            return True
    return False


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

    # 文件名
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shop_names = [c.get('店铺名称', '竞对') for c in competitors[:3]]
    name_str = '+'.join(shop_names)[:30]
    report_id = '{}_{}'.format(name_str, ts)

    # COS key
    html_key = 'reports/{}.html'.format(report_id)
    data_key = 'data/{}.json'.format(report_id)

    # 初始化COS
    client = _cos_client()

    # 1. 上传初始数据JSON
    test = is_test_data(competitors)
    if not test:
        upload_cos(client, data_key, json.dumps(competitors, ensure_ascii=False, indent=2), 'application/json')
        print("  数据已上传: {}/{}".format(COS_BASE_URL, data_key), file=sys.stderr)

    # 2. 生成运营编辑后数据的预签名上传URL
    edited_data_key = 'data/{}_edited.json'.format(report_id)
    presign_url = presign_put(client, edited_data_key)

    # 3. 读模板 + 嵌入数据 + 嵌入预签名URL
    template_html = TEMPLATE.read_text(encoding='utf-8')
    json_str = json.dumps(competitors, ensure_ascii=False, indent=2)
    embedded_html = template_html.replace(
        'const COMPETITORS = loadData();',
        'const COMPETITORS = {};'.format(json_str)
    )

    # CDN 换国内源
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net', 'https://unpkg.com'
    )

    # 嵌入自动上传逻辑（在</body>前插入）
    upload_script = '''
<script>
var __UPLOAD_URL__ = "{}";
var __IS_TEST__ = {};
</script>
'''.format(presign_url.replace('"', '\\"'), 'true' if test else 'false')
    embedded_html = embedded_html.replace('</body>', upload_script + '</body>')

    # 4. 上传HTML到COS
    report_url = upload_cos(client, html_key, embedded_html)
    print(report_url)
    print("  ✅ 报告已上传，在线访问", file=sys.stderr)


if __name__ == '__main__':
    main()
