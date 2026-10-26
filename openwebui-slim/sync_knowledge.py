"""Publish knowledge/*.md to the existing Google Search store; Google handles RAG."""
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from markdown_it import MarkdownIt
import requests

ROOT = Path(__file__).resolve().parent
PROJECT = os.environ['GOOGLE_CLOUD_PROJECT']
BUCKET = os.environ['RAG_BUCKET']
PROXY = 'http://127.0.0.1:7897'
API = 'https://discoveryengine.googleapis.com/v1/'
STORE = json.loads((ROOT / 'cloud-rag.json').read_text())['name']


def main() -> None:
    env = os.environ | {
        'HTTP_PROXY': PROXY, 'HTTPS_PROXY': PROXY,
        'CLOUDSDK_PROXY_TYPE': 'http', 'CLOUDSDK_PROXY_ADDRESS': '127.0.0.1',
        'CLOUDSDK_PROXY_PORT': '7897',
    }
    token = subprocess.check_output([
        '/opt/homebrew/bin/gcloud', '--project=' + PROJECT,
        'auth', 'print-access-token',
    ], env=env, text=True).strip()
    session = requests.Session()
    session.trust_env = False
    session.proxies = {'http': PROXY, 'https': PROXY}
    session.headers['Authorization'] = 'Bearer ' + token
    renderer = MarkdownIt('commonmark', {'html': False, 'linkify': False})
    documents = []
    files = [Path(value).resolve() for value in sys.argv[1:]] if sys.argv[1:] else sorted((ROOT / 'knowledge').glob('*.md'))
    for path in files:
        model, kind = path.stem.rsplit('_', 1)
        document_id = model.lower() + '-' + {'参数': 'spec', '说明书': 'manual'}[kind]
        text = path.read_text()
        fictional = '资料类型：虚构产品资料' in text
        product_url = re.search(r'^(?:产品官网|产品资料)：(.+)$', text, re.M).group(1)
        manual_url = re.search(r'^(?:官方说明书|使用说明)：(.+)$', text, re.M).group(1)
        source = manual_url if kind == '说明书' else product_url
        # Preserve document structure for Google's parser; chunk quality needs verification.
        content = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                   f'<title>{html.escape(path.stem)}</title></head><body>'
                   + renderer.render(text) + '</body></html>')
        object_name = document_id + '.html'
        response = session.post(
            f'https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o',
            params={'uploadType': 'media', 'name': object_name},
            headers={'Content-Type': 'text/html; charset=utf-8'},
            data=content.encode(), timeout=60,
        )
        response.raise_for_status()
        documents.append({
            'id': document_id,
            'structData': {'title': path.stem, 'model': model, 'document_type': kind,
                           'source_url': source, 'product_url': product_url,
                           'manual_url': manual_url, 'fictional': fictional},
            'content': {'mimeType': 'text/html', 'uri': f'gs://{BUCKET}/{object_name}'},
        })
        print('Uploaded', path.name, flush=True)
    response = session.post(API + STORE + '/branches/default_branch/documents:import',
                            json={'inlineSource': {'documents': documents},
                                  'reconciliationMode': 'INCREMENTAL',
                                  'forceRefreshContent': True}, timeout=60)
    response.raise_for_status()
    operation = response.json()
    receipt = ROOT / 'verification/knowledge-sync.json'
    receipt.write_text(json.dumps(operation, ensure_ascii=False, indent=2))
    print('Import operation:', operation['name'], flush=True)
    for _ in range(60):
        if operation.get('done'):
            break
        time.sleep(10)
        response = session.get(API + operation['name'], timeout=40)
        response.raise_for_status()
        operation = response.json()
        receipt.write_text(json.dumps(operation, ensure_ascii=False, indent=2))
        print('Import progress:', operation.get('metadata', {}), flush=True)
    if operation.get('error'):
        raise RuntimeError(operation['error'])
    if not operation.get('done'):
        raise TimeoutError(f'Import still running; operation saved in {receipt}')
    print('Import completed; verify search results before treating indexing as ready.')


if __name__ == '__main__':
    main()
