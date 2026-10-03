"""Start fresh isolated servers, run browser acceptance, then stop only owned processes."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]

def main():
    for port in (8000, 5173):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit(f'Port {port} is occupied. Stop local services before running acceptance.')
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required.')
    run_id = uuid4().hex
    evidence = ROOT / 'codex/evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    database = ROOT / 'codex/.runtime' / f'acceptance-{run_id}.db'
    # Override user environment and frontend/.env so UI writes target this isolated server too.
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'VITE_API_BASE_URL': 'http://127.0.0.1:8000'}
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    processes = []
    opener = build_opener(ProxyHandler({}))
    with (evidence / 'backend.log').open('w', encoding='utf-8') as backend_log, (evidence / 'frontend.log').open('w', encoding='utf-8') as frontend_log:
        try:
            processes.append(subprocess.Popen([sys.executable, str(ROOT / 'codex/test_server.py'), '--database', str(database), '--token', run_id], cwd=ROOT, env=environment, stdout=backend_log, stderr=subprocess.STDOUT, creationflags=flags))
            processes.append(subprocess.Popen([node, str(ROOT / 'frontend/node_modules/vite/bin/vite.js')], cwd=ROOT / 'frontend', env=environment, stdout=frontend_log, stderr=subprocess.STDOUT, creationflags=flags))
            for url in ('http://127.0.0.1:8000/api/health', 'http://localhost:5173'):
                deadline = time.monotonic() + 30
                while True:
                    if any(process.poll() is not None for process in processes):
                        raise RuntimeError('A test server exited; see codex/evidence logs.')
                    try:
                        with opener.open(url, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'Server did not start: {url}')
                    time.sleep(0.2)
            completed = subprocess.run([sys.executable, str(ROOT / 'codex/product_acceptance.py'), '--token', run_id], cwd=ROOT, env=environment, creationflags=flags, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', timeout=120)
            (evidence / 'browser-run.log').write_text(completed.stdout, encoding='utf-8')
            print(completed.stdout, end='', flush=True)
            return completed.returncode
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

if __name__ == '__main__':
    sys.exit(main())
