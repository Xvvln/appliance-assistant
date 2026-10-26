"""Register the demo shop with stock Open WebUI APIs; no upstream source changes."""
import json
from pathlib import Path
import shutil
import importlib.util

from build_product_materials import main as build_materials
from configure_models import configure

import requests

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:3000'
TOOL_ID = 'jiadian_demo_shop'


def main() -> None:
    build_materials()
    session = requests.Session()
    session.trust_env = False
    response = session.post(BASE + '/api/v1/auths/signin', json={'email': '', 'password': ''})
    response.raise_for_status()
    session.headers['Authorization'] = 'Bearer ' + response.json()['token']
    response = session.get(BASE + '/api/v1/configs/tool_servers')
    response.raise_for_status()
    servers = response.json()
    for connection in servers.get('TOOL_SERVER_CONNECTIONS', []):
        if connection.get('info', {}).get('id') == 'washer-cloud-rag':
            connection['spec'] = (ROOT / 'cloud-rag-openapi.json').read_text()
    response = session.post(BASE + '/api/v1/configs/tool_servers', json=servers)
    response.raise_for_status()
    data_dir = ROOT / 'data/webui/commerce'
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'demo-catalog.json', data_dir / 'catalog.json')
    shutil.copyfile(ROOT / 'tools/address_dialog.js', data_dir / 'address_dialog.js')
    shutil.copyfile(ROOT / 'tools/service_dialog.js', data_dir / 'service_dialog.js')
    shutil.copyfile(ROOT / 'product-catalog.json', data_dir / 'product-catalog.json')
    shutil.copyfile(ROOT / 'tools/product_cards.html', data_dir / 'product_cards.html')
    # Reuse the stock static-file mount; no extra web server or upstream patches.
    package = Path(importlib.util.find_spec('open_webui').origin).parent
    shutil.copytree(ROOT / 'assets', package / 'static/jiadian', dirs_exist_ok=True)
    existing = session.get(BASE + '/api/v1/tools/id/' + TOOL_ID)
    if existing.status_code not in (200, 401, 404):
        existing.raise_for_status()
    form = {'id': TOOL_ID, 'name': '家电商城',
            'content': (ROOT / 'tools/demo_shop.py').read_text(),
            'meta': {'description': '选购下单、选择售后家电、报修表单与跨对话工单查询；无需支付。'},
            'access_grants': []}
    endpoint = '/api/v1/tools/id/' + TOOL_ID + '/update' if existing.status_code == 200 else '/api/v1/tools/create'
    response = session.post(BASE + endpoint, json=form)
    response.raise_for_status()
    response = session.post(BASE + '/api/v1/tools/id/' + TOOL_ID + '/valves/update',
                            json={'DATA_DIR': str(data_dir)})
    response.raise_for_status()
    model_id = 'gemini-3.8-flash'
    response = session.get(BASE + '/api/v1/models/model', params={'id': model_id})
    response.raise_for_status()
    model = response.json()
    model['params']['system'] = (ROOT / 'assistant-instructions.txt').read_text()
    model['params']['function_calling'] = 'native'
    ids = model['meta'].setdefault('toolIds', [])
    if TOOL_ID not in ids:
        ids.append(TOOL_ID)
    model['meta']['description'] = '家电管家 · 选购、订购与售后连续服务'
    model['meta']['suggestion_prompts'] = [
        {'content': '我想买洗衣机，预算4000元以内，需要烘干，请用产品卡片展示适合的型号。'},
        {'content': '我想买1.5匹空调，预算3000元以内，请展示合适的产品。'},
        {'content': '我想买400升以上的冰箱，请帮我比较可选型号。'},
        {'content': '我买的家电出问题了，请打开家电选择窗口。'},
        {'content': '查询我的售后记录和报修进度。'},
        {'content': '打开收货地址管理，我想添加或选择地址。'},
    ]
    response = session.post(BASE + '/api/v1/models/model/update', params={'id': model_id}, json=model)
    response.raise_for_status()
    configure(session)
    response = session.get(BASE + '/api/v1/tools/id/' + TOOL_ID)
    response.raise_for_status()
    print(json.dumps({'tool': TOOL_ID, 'registered_methods': [s['name'] for s in response.json()['specs']],
                      'model': model_id, 'tool_ids': ids}, ensure_ascii=False))


if __name__ == '__main__':
    main()
