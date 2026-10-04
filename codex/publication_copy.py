"""Copy the explicit Git publication file list into an isolated local checkout."""
import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to(ROOT / 'codex' / '.local') or target.exists():
        raise ValueError('Output must be a new directory under codex/.local.')
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    count = 0
    for name in sorted(set(names) - {''}):
        source = ROOT / name
        if source.is_file():
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            count += 1
    assert not (target / 'backend' / '.env').exists()
    assert not (target / 'frontend' / '.env').exists()
    print(f'Copied {count} publication files; local credentials excluded.')


if __name__ == '__main__':
    main()
