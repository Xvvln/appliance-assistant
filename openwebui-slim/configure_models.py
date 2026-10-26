"""Configure stock Open WebUI models/tasks through its API; keep business tools intact."""
from copy import deepcopy
from pathlib import Path

import requests

BASE = 'http://127.0.0.1:3000'


def configure(session: requests.Session) -> None:
    # Keep native memory tools, but retrieve explicitly by customer instead of
    # injecting semantically similar preferences from other demo customers.
    response = session.get(BASE + '/api/v1/auths/admin/config')
    response.raise_for_status()
    admin_config = response.json()
    admin_config['ENABLE_MEMORY_SYSTEM_CONTEXT'] = False
    session.post(BASE + '/api/v1/auths/admin/config', json=admin_config).raise_for_status()
    response = session.get(BASE + '/api/v1/models/model', params={'id': 'gemini-3.8-flash'})
    response.raise_for_status()
    source = response.json()
    for model_id, name, vision in (
        ('gemini-3.8-flash', 'Gemini 3.8 Flash', True),
        ('jiadian-auto', '家电管家路由', True),
        ('jiadian-assistant', '家电管家', True),
        ('deepseek-text', 'DeepSeek V4 Flash', False),
        ('glm-text', 'GLM 5.2', False),
        ('gemini-embedding-001', 'gemini-embedding-001', False),
    ):
        existing = session.get(BASE + '/api/v1/models/model', params={'id': model_id})
        if existing.status_code not in (200, 401, 404):
            existing.raise_for_status()
        if model_id == 'gemini-embedding-001':
            current = existing.json() if existing.status_code == 200 else {}
            model = {key: deepcopy(current.get(key, default)) for key, default in
                     (('params', {}), ('meta', {}), ('access_grants', []))}
        else:
            model = {key: deepcopy(source[key]) for key in ('params', 'meta', 'access_grants')}
            model['params'].update(function_calling='native', reasoning_effort='medium')
            model['meta']['capabilities']['vision'] = vision
        model.update(id=model_id, name=name, base_model_id='jiadian-auto' if model_id == 'jiadian-assistant' else None, is_active=True)
        # Native visibility only: hidden models remain callable by background tasks.
        model['meta']['hidden'] = model_id != 'jiadian-assistant'
        endpoint = '/model/update' if existing.status_code == 200 else '/create'
        saved = session.post(BASE + '/api/v1/models' + endpoint,
                             params={'id': model_id}, json=model)
        saved.raise_for_status()

    response = session.get(BASE + '/api/v1/tasks/config')
    response.raise_for_status()
    tasks = response.json()
    tasks.update(TASK_MODEL_EXTERNAL='glm-text',
                 ENABLE_TITLE_GENERATION=True, ENABLE_TAGS_GENERATION=True,
                 ENABLE_FOLLOW_UP_GENERATION=True)
    tasks['FOLLOW_UP_GENERATION_PROMPT_TEMPLATE'] = Path(__file__).with_name('follow-up-instructions.txt').read_text()
    tasks['TASK_MODEL_PARAMS']['reasoning_effort'] = 'medium'
    session.post(BASE + '/api/v1/tasks/config/update', json=tasks).raise_for_status()

    response = session.get(BASE + '/api/v1/configs/models')
    response.raise_for_status()
    defaults = response.json()
    defaults['DEFAULT_MODELS'] = 'jiadian-assistant'
    defaults['DEFAULT_MODEL_PARAMS'] = (defaults.get('DEFAULT_MODEL_PARAMS') or {}) | {
        'function_calling': 'native', 'reasoning_effort': 'medium'}
    defaults['MODEL_ORDER_LIST'] = ['jiadian-assistant']
    session.post(BASE + '/api/v1/configs/models', json=defaults).raise_for_status()


if __name__ == '__main__':
    client = requests.Session()
    client.trust_env = False
    auth = client.post(BASE + '/api/v1/auths/signin', json={'email': '', 'password': ''})
    auth.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + auth.json()['token']
    configure(client)
    print('已配置自动路由、medium 思考和文字辅助任务。')
