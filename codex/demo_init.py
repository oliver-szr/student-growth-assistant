"""Initialize a named demo database; never reset or touch the normal database."""
import argparse
import json
import sys
from pathlib import Path
from datetime import date, time, datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import Base,create_sqlite_engine
from app.models import Task,TimeRule,Plan,PlanItem
from app.services.course_import import import_source
from app.services.assistant_clock import demo_database
from app.services.scheduling_types import SHANGHAI
from app.services.planning_state import get_or_create_planning_state,bump_revision
from app.services.validator import expand_time_rules
from app.services.assistant_state import time_rules


def example_source():
    return dict(semester_week_1_monday='2026-08-31',course_entries=[
        dict(course='示例课程A',weekday=4,weeks_raw='第6周',start_time='08:50',end_time='10:25'),
        dict(course='示例课程B',weekday=4,weeks_raw='第6周',start_time='14:00',end_time='15:35'),
        dict(course='示例课程C',weekday=5,weeks_raw='第6周',start_time='15:45',end_time='17:20')],practice_entries=[])


def seed(db,source):
    import_source(db,source)
    if db.scalar(select(Plan).where(Plan.week_start==date(2026,10,5),Plan.status=='confirmed')):
        return
    if db.scalar(select(Task.id)):
        raise ValueError('已有任务但缺少初始演示计划；请使用新演示数据库。')
    for weekday in range(1,8):
        for start,end,label in [(time(12),time(14),'午间'),(time(18),time(19),'晚餐'),(time(21),time(22),'休息')]:
            db.add(TimeRule(kind='protected',title=f'演示保护时间：{label}',recurrence='weekly',weekday=weekday,start_time=start,end_time=end))
    examples=[('云计算作业',90,'normal','2026-10-08T20:00:00+08:00','2026-10-08T16:00:00+08:00'),('软件工程报告',120,'high','2026-10-11T20:00:00+08:00','2026-10-07T19:00:00+08:00'),('文献阅读',60,'low','2026-10-11T22:00:00+08:00','2026-10-08T10:30:00+08:00')]
    tasks=[]
    for title,minutes,priority,deadline,start in examples:
        t=Task(title=title,description='演示样例，不代表真实作业',duration_minutes=minutes,priority=priority,deadline=datetime.fromisoformat(deadline),status='todo')
        db.add(t);db.flush();tasks.append((t,datetime.fromisoformat(start)))
    plan=Plan(week_start=date(2026,10,5),status='confirmed',source_revision=get_or_create_planning_state(db).revision,task_ids=[t.id for t,_ in tasks],confirmed_at=datetime(2026,10,7,18,tzinfo=SHANGHAI))
    db.add(plan);db.flush()
    from datetime import timedelta
    for t,start in tasks:
        db.add(PlanItem(plan_id=plan.id,kind='task',task_id=t.id,title_snapshot=t.title,start_at=start,end_at=start+timedelta(minutes=t.duration_minutes)))
    rules=time_rules(db);names={r.id:r.title for r in rules}
    for r in expand_time_rules(date(2026,10,5),rules):
        if r.kind=='course': db.add(PlanItem(plan_id=plan.id,kind='course',time_rule_id=r.time_rule_id,title_snapshot=names[r.time_rule_id],start_at=r.start_at,end_at=r.end_at))
    bump_revision(db)


def initialize(path,source=None):
    target=demo_database(str(path));target.parent.mkdir(parents=True,exist_ok=True)
    engine=create_sqlite_engine(f'sqlite:///{target.as_posix()}');Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db,source or example_source());db.commit()
    engine.dispose()
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    source=json.loads(args.source.read_text(encoding='utf-8-sig')) if args.source else None
    print(initialize(args.database,source))
