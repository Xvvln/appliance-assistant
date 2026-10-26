"""Point the existing Open WebUI image editor at the user's Vertex connection."""
import json
from importlib.util import find_spec
from pathlib import Path
import requests

from features.common import setting

ROOT = Path(__file__).resolve().parent


def configure():
    # Vertex requires an explicit role; the stock Gemini editor omits it.
    # Keep the native editor and apply this one-field compatibility fix.
    images_path = Path(find_spec('open_webui').origin).parent / 'routers/images.py'
    source = images_path.read_text()
    before, marker, editor = source.partition('async def image_edits(')
    editor = editor.replace("data = {'contents': [{'parts':", "data = {'contents': [{'role': 'user', 'parts':", 1)
    updated = before + marker + editor
    if updated != source:
        images_path.write_text(updated)

    session = requests.Session()
    session.trust_env = False
    base = 'http://127.0.0.1:3000'
    response = session.post(base + '/api/v1/auths/signin', json={'email': '', 'password': ''})
    response.raise_for_status()
    session.headers['Authorization'] = 'Bearer ' + response.json()['token']
    response = session.get(base + '/api/v1/images/config')
    response.raise_for_status()
    config = response.json()
    settings = json.loads((ROOT / 'assistant-images.json').read_text())
    config.update(IMAGE_EDIT_ENGINE='gemini', IMAGE_EDIT_MODEL=settings['model'],
                  IMAGES_EDIT_GEMINI_API_BASE_URL='https://aiplatform.googleapis.com/v1/publishers/google',
                  IMAGES_EDIT_GEMINI_API_KEY=setting('GOOGLE_VERTEX_API_KEY'))
    # The activity calls the native adapter through its own rate-limited queue.
    # Existing global image-generation switches retain their current setting.
    response = session.post(base + '/api/v1/images/config/update', json=config)
    response.raise_for_status()
    print('空间预览已复用 Open WebUI 的 Gemini 图片编辑接口。')


if __name__ == '__main__':
    configure()
