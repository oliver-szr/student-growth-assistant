"""A fixed clock is available only for isolated, explicitly named demo databases."""
import os
from pathlib import Path
from datetime import datetime
from .scheduling_types import SHANGHAI

ROOT = Path(__file__).resolve().parents[3]


def demo_database(path: str) -> Path:
    target = Path(path).resolve()
    runtime = (ROOT / 'codex' / '.runtime').resolve()
    if target.parent != runtime or not target.name.startswith('demo-') or target.suffix != '.db':
        raise ValueError('演示数据库必须位于 codex/.runtime/demo-*.db，不能使用正常数据库。')
    return target


def clock_settings() -> dict:
    demo = os.getenv('SGA_DEMO') == '1'
    if demo:
        demo_database(os.getenv('SGA_DATABASE_PATH', ''))
        now = datetime.fromisoformat(os.getenv('SGA_DEMO_NOW', '2026-10-07T18:00:00+08:00'))
        if now.tzinfo is None:
            raise ValueError('演示时间必须包含时区。')
        now = now.astimezone(SHANGHAI)
    else:
        now = datetime.now(SHANGHAI)
    return {'demo': demo, 'now': now.isoformat(), 'week_start': (now.date()).fromordinal(now.date().toordinal()-now.weekday()).isoformat()}


def assistant_now() -> datetime:
    return datetime.fromisoformat(clock_settings()['now'])
