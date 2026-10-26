"""Start/stop the stock Open WebUI stack on this Mac. No application logic."""
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ENVS = Path('/opt/homebrew/Caskroom/miniforge/base/envs')
PG = Path('/opt/homebrew/opt/postgresql@18/bin')
SECRETS = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
               if '=' in line and not line.startswith('#'))
PROXY = 'http://127.0.0.1:7897'
# Both services use the same outbound proxy; local service calls stay on loopback.
BASE = os.environ | SECRETS | {
    'HTTP_PROXY': PROXY, 'HTTPS_PROXY': PROXY, 'ALL_PROXY': PROXY,
    'http_proxy': PROXY, 'https_proxy': PROXY, 'all_proxy': PROXY,
    'NO_PROXY': 'localhost,127.0.0.1,::1', 'no_proxy': 'localhost,127.0.0.1,::1',
    'AIOHTTP_TRUST_ENV': 'true', 'WEB_SEARCH_TRUST_ENV': 'true',
    'CLOUDSDK_PROXY_TYPE': 'http', 'CLOUDSDK_PROXY_ADDRESS': '127.0.0.1',
    'CLOUDSDK_PROXY_PORT': '7897',
}


def start(name: str, command: list[str], settings: dict[str, str]) -> None:
    pidfile = ROOT / 'run' / f'{name}.pid'
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text()), 0)
            print(f'{name}: already running')
            return
        except ProcessLookupError:
            pass
    with (ROOT / 'logs' / f'{name}.log').open('a') as log:
        proc = subprocess.Popen(command, cwd=ROOT, env=BASE | settings,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pidfile.write_text(str(proc.pid))
    print(f'{name}: started ({proc.pid})')


if sys.argv[1:] == ['stop']:
    for name in ('webui', 'litellm'):
        pidfile = ROOT / 'run' / f'{name}.pid'
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
            pidfile.unlink()
    subprocess.run([str(PG / 'pg_ctl'), '-D', str(ROOT / 'data/postgres'), 'stop', '-m', 'fast'])
    sys.exit()

for folder in ('logs', 'run', 'data/webui'):
    (ROOT / folder).mkdir(parents=True, exist_ok=True)
if subprocess.run([str(PG / 'pg_ctl'), '-D', str(ROOT / 'data/postgres'), 'status'],
                  stdout=subprocess.DEVNULL).returncode:
    subprocess.run([str(PG / 'pg_ctl'), '-D', str(ROOT / 'data/postgres'),
                    '-l', str(ROOT / 'logs/postgres.log'), '-o',
                    f'-h 127.0.0.1 -p 54329 -k {ROOT}/run', 'start'], check=True)
start('litellm', [str(ENVS / 'jiadian-litellm/bin/litellm'), '--config',
                  str(ROOT / 'litellm.yaml'), '--host', '127.0.0.1', '--port', '4001'], {})
start('webui', [str(ENVS / 'jiadian-webui/bin/python'), '-m', 'uvicorn', 'project_server:app',
                '--host', '127.0.0.1', '--port', '3000'], {
    'DATA_DIR': str(ROOT / 'data/webui'),
    'FRONTEND_BUILD_DIR': str(ROOT / 'webui-src/build'),
    # Upstream name of the slim feature switch; this does not start Docker.
    'USE_SLIM_DOCKER': 'true', 'WEBUI_AUTH': 'false',
    'WEBUI_ADMIN_EMAIL': '', 'WEBUI_ADMIN_PASSWORD': '',
    'ENABLE_OLLAMA_API': 'false',
    'OPENAI_API_BASE_URL': 'http://127.0.0.1:4001/v1',
    'OPENAI_API_KEY': SECRETS['LITELLM_MASTER_KEY'],
    'DEFAULT_MODELS': 'jiadian-assistant',
    'DEFAULT_MODEL_PARAMS': '{"function_calling":"native","reasoning_effort":"medium"}',
    # Stock background features use the text-only task model, preserving Vertex quota.
    'TASK_MODEL_EXTERNAL': 'glm-text',
    'ENABLE_FOLLOW_UP_GENERATION': 'true', 'ENABLE_TAGS_GENERATION': 'true',
    'ENABLE_MEMORIES': 'true', 'VECTOR_DB': 'pgvector',
    'PGVECTOR_DB_URL': f"postgresql://jiadian:{SECRETS['POSTGRES_PASSWORD']}@127.0.0.1:54329/knowledge",
    'RAG_EMBEDDING_ENGINE': 'openai',
    'RAG_OPENAI_API_BASE_URL': 'http://127.0.0.1:4001/v1',
    'RAG_OPENAI_API_KEY': SECRETS['LITELLM_MASTER_KEY'],
    'RAG_EMBEDDING_MODEL': 'gemini-embedding-001', 'RAG_EMBEDDING_MODEL_AUTO_UPDATE': 'false',
    'ENABLE_VERSION_UPDATE_CHECK': 'false', 'SCARF_NO_ANALYTICS': 'true',
    'DO_NOT_TRACK': 'true', 'ANONYMIZED_TELEMETRY': 'false',
})
print('Open WebUI: http://127.0.0.1:3000')
