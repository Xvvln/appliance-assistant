"""Small shared adapters: existing model gateway, shop and saved activity state."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from openai import AsyncOpenAI, APIError
from tools.demo_shop import Tools

ROOT = Path(__file__).resolve().parents[1]
STATE_DB = ROOT / 'data/webui/assistant.sqlite3'


def get_shop() -> Tools:
    shop = Tools()
    shop.valves.DATA_DIR = str(ROOT / 'data/webui/commerce')
    return shop


def _db():
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE_DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS sessions ('
               'id TEXT NOT NULL, user_id TEXT NOT NULL, kind TEXT NOT NULL, '
               'updated_at TEXT NOT NULL, payload TEXT NOT NULL, '
               'PRIMARY KEY(user_id,kind,id))')
    return db


def save_session(user_id: str, kind: str, state: dict) -> dict:
    now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    state = dict(state)
    state.setdefault('id', uuid4().hex)
    state.setdefault('created_at', now)
    state['updated_at'] = now
    with closing(_db()) as db, db:
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?) '
                   'ON CONFLICT(user_id,kind,id) DO UPDATE SET '
                   'updated_at=excluded.updated_at,payload=excluded.payload',
                   (state['id'], user_id, kind, now, json.dumps(state, ensure_ascii=False)))
    return state


def load_session(user_id: str, kind: str, session_id: str) -> dict | None:
    with closing(_db()) as db:
        row = db.execute('SELECT payload FROM sessions WHERE user_id=? AND kind=? AND id=?',
                         (user_id, kind, session_id)).fetchone()
    return json.loads(row['payload']) if row else None


def list_sessions(user_id: str, kind: str) -> list[dict]:
    with closing(_db()) as db:
        rows = db.execute('SELECT payload FROM sessions WHERE user_id=? AND kind=? '
                          'ORDER BY updated_at DESC LIMIT 30', (user_id, kind)).fetchall()
    return [json.loads(row['payload']) for row in rows]


def setting(name: str, default: str = '') -> str:
    if name in os.environ:
        return os.environ[name]
    # Standalone checks use the same existing configuration as services.py.
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith(name + '='):
            return line.split('=', 1)[1]
    return default


async def model_json(system: str, user_text: str, images: list[str] | None = None) -> dict:
    content = [{'type': 'text', 'text': user_text}]
    content.extend({'type': 'image_url', 'image_url': {'url': image}} for image in (images or []))
    # Reuse LiteLLM's existing text fallback chain and Gemini vision route.
    # Only this loopback hop bypasses the proxy; upstream routing uses port 7897.
    async with AsyncOpenAI(base_url='http://127.0.0.1:4001/v1',
                           api_key=setting('LITELLM_MASTER_KEY'), max_retries=0,
                           timeout=180, http_client=httpx.AsyncClient(trust_env=False)) as client:
        try:
            response = await client.chat.completions.create(
                model='gemini-3.8-flash' if images else 'deepseek-text',
                messages=[{'role': 'system', 'content': system + '\n仅输出一个JSON对象，不加代码围栏。'},
                          {'role': 'user', 'content': content if images else user_text}],
                reasoning_effort='medium', response_format={'type': 'json_object'})
        except APIError as error:
            raise HTTPException(503, '模型暂时繁忙，请稍后重试，已保存的内容仍会保留。') from error
    text = response.choices[0].message.content or ''
    try:
        result = json.loads(text.strip().removeprefix('```json').removeprefix('```').removesuffix('```'))
        if not isinstance(result, dict):
            raise ValueError('Expected object')
        return result
    except (ValueError, TypeError) as error:
        raise HTTPException(502, '这次回复没有生成完整结果，请重试。') from error
