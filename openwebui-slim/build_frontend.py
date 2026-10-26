"""Build the pinned Open WebUI frontend, reusing the installed Pyodide assets."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'webui-src'
NODE = Path('/opt/homebrew/opt/node@22/bin')
ENV = os.environ | {'PATH': f'{NODE}:{os.environ.get("PATH", "")}',
                    'NODE_OPTIONS': '--max-old-space-size=8192'}

# Upstream's verifier uses URL.pathname without decoding Chinese directory names.
# An ASCII symlink lets the original verifier check its unchanged source/manifest.
# This temporary link is removed automatically; no encryption checks are skipped.
with tempfile.TemporaryDirectory(prefix='jiadian-build-', dir='/tmp') as temporary:
    link = Path(temporary) / 'source'
    link.symlink_to(SOURCE, target_is_directory=True)
    subprocess.run([str(NODE / 'node'), '--preserve-symlinks-main',
                    str(link / 'scripts/encryption/artifact.mjs')], check=True, env=ENV)

subprocess.run([str(SOURCE / 'node_modules/.bin/vite'), 'build'],
               cwd=SOURCE, env=ENV, check=True)
installed = Path('/opt/homebrew/Caskroom/miniforge/base/envs/jiadian-webui/lib/python3.12/site-packages/open_webui/frontend/pyodide')
shutil.copytree(installed, SOURCE / 'build/pyodide', dirs_exist_ok=True)
print('Frontend ready. Restart the WebUI process to load this build.')
