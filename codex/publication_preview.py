"""Capture anonymous public previews and verify a fresh, AI-free demo checkout."""
import argparse
import functools
import http.server
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--python', required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    output = ROOT / 'codex' / 'previews'
    output.mkdir(exist_ok=True)
    local = ROOT / 'codex' / '.local' / 'publication'
    local.mkdir(parents=True, exist_ok=True)
    scenario = json.loads((project / 'codex' / 'demo_scenario.json').read_text(encoding='utf-8'))
    env = {**os.environ, 'SGA_DEMO': '1', 'SGA_DEMO_NOW': scenario['now'], 'SGA_AUTO_BACKUP': '0',
           'AI_API_FORMAT': 'openai', 'OPENAI_API_KEY': '', 'CLAUDE_API_KEY': '',
           'SGA_DATABASE_PATH': str(project / 'codex' / '.runtime' / 'demo-publication.db')}
    for port in (8003, 5187):
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} occupied; no process will be stopped.')
    for _ in range(2):
        subprocess.run([args.python, 'codex/demo_init.py', '--database', env['SGA_DATABASE_PATH']], cwd=project, env=env, check=True, capture_output=True)
    log = (local / 'preview-backend.log').open('w', encoding='utf-8')
    backend = subprocess.Popen([args.python, '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8003'], cwd=project, env=env, stdout=log, stderr=log)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 5187), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(project / 'frontend' / 'dist')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    report = {'anonymous_demo': True, 'ai_mode': 'disabled', 'checks': [], 'browser_errors': []}
    try:
        api = httpx.Client(base_url='http://127.0.0.1:8003', timeout=10)
        deadline = time.monotonic() + 30
        while True:
            try:
                if api.get('/api/health').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if backend.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Fresh demo backend did not start.')
            time.sleep(.2)
        settings = api.get('/api/assistant/settings').json()
        assert settings['demo'] and settings['week_start'] == scenario['week_start']
        tasks = api.get('/api/tasks').json()
        assert len([task for task in tasks if task['status'] == 'todo']) == 3
        report['checks'] += ['fresh_start_without_credentials', 'anonymous_seed_repeatable', 'fixed_demo_clock']
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(locale='zh-CN', timezone_id='America/Los_Angeles', viewport={'width': 1373, 'height': 1163})
            page.on('pageerror', lambda error: report['browser_errors'].append(str(error)))
            page.goto('http://127.0.0.1:5187/', wait_until='networkidle')
            expect(page.get_by_role('heading', name='一起安排这一周', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='规划助手', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'planning.png'), full_page=True)
            page.get_by_role('button', name='复盘', exact=True).click()
            expect(page.get_by_role('heading', name='复盘助手', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'review.png'), full_page=True)
            page.get_by_role('button', name='我的档案', exact=True).click()
            expect(page.get_by_role('heading', name='档案助手', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='安排偏好', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'profile.png'), full_page=True)
            page.reload(wait_until='networkidle')
            page.get_by_role('button', name='我的档案', exact=True).click()
            expect(page.get_by_role('heading', name='档案助手', exact=True)).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('heading', name='档案助手', exact=True)).to_be_visible()
            browser.close()
        report['checks'] += ['three_page_desktop', 'refresh_restore', 'narrow_screen', 'non_shanghai_browser_timezone']
        session = api.post('/api/assistant/sessions/open', json={'scope': 'profile'}).json()
        run = api.post(f"/api/assistant/sessions/{session['id']}/runs", json={'client_message_id': str(uuid.uuid4()), 'text': '新增编程类别'}).json()
        for _ in range(50):
            result = api.get(f"/api/assistant/runs/{run['id']}").json()
            if result['status'] != 'running':
                break
            time.sleep(.1)
        assert result['status'] == 'failed', result
        assert api.get('/api/tasks').json() == tasks
        report['checks'].append('ai_unconfigured_failure_preserves_formal_tasks')
        assert not report['browser_errors'], report['browser_errors']
    finally:
        server.shutdown(); server.server_close()
        backend.terminate(); backend.wait(timeout=15); log.close()
        (local / 'preview-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
