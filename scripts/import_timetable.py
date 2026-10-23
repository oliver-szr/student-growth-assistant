"""Preview by default. --apply imports the reviewed local source atomically."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy.orm import Session
from app.services.schema_migrations import upgrade_database
from app.database import Base,create_sqlite_engine
from app.services.course_import import expand_source,import_source
from app.services.planning_state import begin_planning_transaction


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    source=json.loads(args.source.read_text(encoding='utf-8-sig'))
    rows,warnings=expand_source(source)
    report=dict(mode='apply' if args.apply else 'preview',count=len(rows),warnings=warnings,first=min(r['date'] for r in rows),last=max(r['date'] for r in rows))
    if args.apply:
        target=ROOT/'backend'/'data'/'app.db'
        if target.exists():
            backup=ROOT/'scripts'/'.runtime'/f'normal-before-import-{datetime.now():%Y%m%d%H%M%S}.db'
            backup.parent.mkdir(exist_ok=True)
            with sqlite3.connect(target) as a,sqlite3.connect(backup) as b:a.backup(b)
        engine=create_sqlite_engine(f'sqlite:///{target.as_posix()}');upgrade_database(engine)
        with Session(engine) as db:
            begin_planning_transaction(db)
            report.update(import_source(db,source));db.commit()
        engine.dispose()
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
