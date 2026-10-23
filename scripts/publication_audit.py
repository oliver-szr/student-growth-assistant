"""Audit publishable files and reachable Git blobs without printing secrets."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from urllib.parse import unquote, urlsplit
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'scripts' / '.local' / 'publication'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def file_list():
    return sorted(set(git('ls-files', '-c', '-o', '--exclude-standard', '-z').decode('utf-8').split('\0')) - {''})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', action='store_true')
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    files = file_list()
    if args.snapshot:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        with zipfile.ZipFile(LOCAL / f'working-tree-{stamp}.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in files:
                path = ROOT / name
                if path.is_file():
                    archive.write(path, name)
        (LOCAL / f'recovery-{stamp}.json').write_text(json.dumps({
            'head': git('rev-parse', 'HEAD').decode().strip(),
            'branch': git('branch', '--show-current').decode().strip(),
            'remotes': git('remote', '-v').decode(), 'files': files,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    secrets = []
    env = ROOT / 'backend' / '.env'
    if env.exists():
        for match in re.finditer(r'^\s*[A-Z_]*(?:KEY|TOKEN|SECRET)\s*=\s*(.+)$', env.read_text(encoding='utf-8-sig'), re.M):
            value = match.group(1).strip().strip('"\'')
            if len(value) >= 12:
                secrets.append(value.encode())
    findings = []
    token = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})')

    def inspect(data, name, scope):
        reasons = []
        if any(secret in data for secret in secrets):
            reasons.append('matches_local_secret')
        if token.search(data):
            reasons.append('credential_pattern_review_required')
        lowered = name.lower()
        if lowered.endswith(('.db', '.sqlite', '.sqlite3', '.pdf')) or lowered.split('/')[-1] == '.env':
            reasons.append('private_file_type')
        if reasons:
            findings.append({'scope': scope, 'path': name, 'reasons': reasons})

    manifest = []
    for name in files:
        path = ROOT / name
        if path.is_file():
            data = path.read_bytes()
            inspect(data, name, 'working_tree')
            if name.endswith('.md'):
                document = re.sub(r'```.*?```', '', data.decode('utf-8-sig'), flags=re.S)
                for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', document):
                    target = unquote(target.strip().strip('<>'))
                    if not target or target.startswith('#') or urlsplit(target).scheme:
                        continue
                    linked = (path.parent / target.split('#')[0]).resolve()
                    if not linked.is_relative_to(ROOT) or linked.relative_to(ROOT).as_posix() not in files:
                        findings.append({'scope': 'documentation', 'path': name, 'target': target, 'reasons': ['unpublished_local_link']})
            manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    objects = git('rev-list', '--objects', 'HEAD').decode('utf-8').splitlines()
    for entry in objects:
        oid, _, name = entry.partition(' ')
        if git('cat-file', '-t', oid).strip() == b'blob':
            inspect(git('cat-file', 'blob', oid), name, 'history')
    report = {'files': len(manifest), 'history_objects': len(objects), 'findings': findings}
    (LOCAL / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (LOCAL / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
