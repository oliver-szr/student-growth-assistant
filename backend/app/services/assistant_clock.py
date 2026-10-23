"""A fixed clock is available only for isolated, explicitly named demo databases."""
import os
import json
from pathlib import Path
from datetime import datetime
from .scheduling_types import SHANGHAI

ROOT = Path(__file__).resolve().parents[3]


def demo_database(path: str) -> Path:
    target = Path(path).resolve()
    runtimes = {(ROOT / 'scripts' / '.runtime').resolve(), (ROOT / 'codex' / '.runtime').resolve()}
    if target.parent not in runtimes or not target.name.startswith('demo-') or target.suffix != '.db':
        raise ValueError('演示数据库必须位于 scripts/.runtime/demo-*.db（兼容原本地演示目录），不能使用正常数据库。')
    return target


def clock_settings() -> dict:
    demo = os.getenv('SGA_DEMO') == '1'
    if demo:
        demo_database(os.getenv('SGA_DATABASE_PATH', ''))
        scenario_path = ROOT / 'scripts' / 'demo_scenario.json'
        scenario_now = json.loads(scenario_path.read_text(encoding='utf-8'))['now'] if scenario_path.exists() else '2026-10-14T18:00:00+08:00'
        now = datetime.fromisoformat(os.getenv('SGA_DEMO_NOW', scenario_now))
        if now.tzinfo is None:
            raise ValueError('演示时间必须包含时区。')
        now = now.astimezone(SHANGHAI)
    else:
        now = datetime.now(SHANGHAI)
    return {'demo': demo, 'now': now.isoformat(), 'week_start': (now.date()).fromordinal(now.date().toordinal()-now.weekday()).isoformat()}


def assistant_now() -> datetime:
    return datetime.fromisoformat(clock_settings()['now'])
