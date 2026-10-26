"""Restore the pinned upstream source and apply the published customizations."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'webui-src'
REVISION = '91ea4e3421d1d8069f13d4a463fcb5986d94ea60'
if SOURCE.exists():
    raise SystemExit('webui-src already exists; keep existing work or remove it before preparing a fresh checkout.')
subprocess.run(['git', 'init', str(SOURCE)], check=True)
subprocess.run(['git', '-C', str(SOURCE), 'fetch', '--depth=1', 'https://github.com/open-webui/open-webui.git', REVISION], check=True)
subprocess.run(['git', '-C', str(SOURCE), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
subprocess.run(['git', '-C', str(SOURCE), 'apply', str(ROOT / 'open-webui.patch')], check=True)
shutil.copytree(ROOT / 'webui-overlay', SOURCE, dirs_exist_ok=True)
print('Open WebUI source prepared. Install dependencies and build before starting the application.')
