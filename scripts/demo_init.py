"""Initialize a named demo database; never reset or touch the normal database."""
import argparse
import json
import sys
from pathlib import Path
from datetime import date, time, datetime, timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services.schema_migrations import upgrade_database
from app.database import Base,create_sqlite_engine
from app.models import (Task,TimeRule,Plan,PlanItem,TaskGrowthContext,TaskSchedulingProfile,
    TaskFeedback,TaskWorkSession,GrowthGoal,GrowthGoalRevision,GrowthUserProfile,AssistantPreference,TaskCategory)
from app.services.course_import import import_source
from app.services.assistant_clock import demo_database
from app.services.scheduling_types import SHANGHAI
from app.services.planning_state import get_or_create_planning_state,bump_revision
from app.services.validator import expand_time_rules
from app.services.assistant_state import time_rules
from app.services.assistant_state import SAMPLE_PREFERENCES

SCENARIO=json.loads((ROOT/'scripts'/'demo_scenario.json').read_text(encoding='utf-8'))
WEEK_START=date.fromisoformat(SCENARIO['week_start'])
DEMO_NOW=datetime.fromisoformat(SCENARIO['now'])


def example_source():
    return dict(semester_week_1_monday='2026-08-31',course_entries=[
        dict(course='示例课程A',weekday=4,weeks_raw='1-17周',start_time='08:50',end_time='10:25'),
        dict(course='示例课程B',weekday=4,weeks_raw='7-10周',start_time='14:00',end_time='17:20'),
        dict(course='示例课程C',weekday=5,weeks_raw='3-11周',start_time='15:45',end_time='17:20')],practice_entries=[])


def seed(db,source):
    import_source(db,source)
    if db.scalar(select(Plan).where(Plan.week_start==WEEK_START,Plan.status=='confirmed')):
        return
    if db.scalar(select(Task.id)):
        raise ValueError('已有任务但缺少初始演示计划；请使用新演示数据库。')
    for weekday in range(1,8):
        for window in SCENARIO['protection_windows']:
            db.add(TimeRule(kind='protected',title=f"演示保护时间：{window['label']}",recurrence='weekly',weekday=weekday,start_time=time.fromisoformat(window['start']),end_time=time.fromisoformat(window['end'])))
    examples=[(x['title'],x['duration_minutes'],x['priority'],x['deadline'],x['start_at'],x['category_key']) for x in SCENARIO['tasks']]
    tasks=[]
    for title,minutes,priority,deadline,start,family in examples:
        t=Task(title=title,description='演示样例，不代表真实作业',duration_minutes=minutes,priority=priority,deadline=datetime.fromisoformat(deadline),status='todo')
        db.add(t);db.flush();tasks.append((t,datetime.fromisoformat(start),family))
    goal=GrowthGoal(title='每周阅读三篇资料',motivation='保持稳定阅读，支持课程项目学习。',goal_type='long_term',priority=1,metric_kind='count',weekly_target=3,unit_label='篇',status='active')
    db.add(goal);db.flush()
    db.add(GrowthGoalRevision(goal_id=goal.id,version=goal.version,snapshot={
        'title':goal.title,'motivation':goal.motivation,'goal_type':goal.goal_type,'priority':goal.priority,
        'metric_kind':goal.metric_kind,'weekly_target':goal.weekly_target,'unit_label':goal.unit_label,
        'due_date':None,'status':goal.status,
    }))
    db.add(GrowthUserProfile(id=1,direction='稳定推进课程项目，同时保持每周阅读习惯。',version=1))
    db.add(AssistantPreference(id=1,settings=SAMPLE_PREFERENCES,is_sample=True))
    for task,_,family in tasks:
        db.add(TaskGrowthContext(task_id=task.id,goal_id=goal.id if family=='reading' else None,
            family=family,family_confirmed=True,initial_estimate_minutes=task.duration_minutes,deadline_source='external'))
        db.add(TaskSchedulingProfile(task_id=task.id,settings={'task_type':family}))

    # Explicitly synthetic history lets the isolated demo explain how observed execution
    # can inform a user-confirmed preference. The demo banner identifies it as sample data.
    sample_minutes=[75,80,85,90,100]
    sample_days=(29,1,3,5,6)
    for index,(day,actual) in enumerate(zip(sample_days,sample_minutes),start=1):
        month=9 if day==29 else 10
        completed_at=datetime(2026,month,day,10,30,tzinfo=SHANGHAI)
        deadline=datetime(2026,month,day,20,0,tzinfo=SHANGHAI)
        sample=Task(title=f'【演示数据】短报告写作 {index}',description='虚构的成长学习样例，不代表用户历史',duration_minutes=120,
            deadline=deadline,priority='normal',status='done')
        db.add(sample);db.flush()
        db.add(TaskGrowthContext(task_id=sample.id,family='writing',family_confirmed=True,initial_estimate_minutes=120,deadline_source='user_target'))
        db.add(TaskSchedulingProfile(task_id=sample.id,settings={'task_type':'writing'}))
        db.add(TaskFeedback(task_id=sample.id,client_action_id=f'demo-writing-feedback-{index}',outcome='completed',
            actual_minutes=actual,title_snapshot=sample.title,deadline_snapshot=deadline,priority_snapshot='normal',
            family_snapshot='writing',category_name_snapshot='写作',family_confirmed_snapshot=True,initial_estimate_minutes=120,
            completed_at=completed_at,created_at=completed_at))
        started_at=datetime(2026,month,day,9,10,tzinfo=SHANGHAI)
        db.add(TaskWorkSession(task_id=sample.id,client_action_id=f'demo-writing-timer-{index}',status='stopped',
            family_snapshot='writing',category_name_snapshot='写作',family_confirmed_snapshot=True,accumulated_seconds=actual*60,
            segment_started_at=None,started_at=started_at,updated_at=completed_at))
    # A second synthetic pattern gives the demo a genuinely new suggestion beyond
    # the sample "writing in the morning" preference already shown in the UI.
    for index,(day,month) in enumerate(((29,9),(1,10),(3,10),(5,10),(6,10)),start=1):
        completed_at=datetime(2026,month,day,17,30,tzinfo=SHANGHAI)
        deadline=datetime(2026,month,day,22,0,tzinfo=SHANGHAI)
        sample=Task(title=f'【演示数据】练习任务 {index}',description='虚构的成长学习样例，不代表真实用户记录',duration_minutes=60,
            deadline=deadline,priority='normal',status='done')
        db.add(sample);db.flush()
        db.add(TaskGrowthContext(task_id=sample.id,family='practice',family_confirmed=True,initial_estimate_minutes=60,deadline_source='user_target'))
        db.add(TaskSchedulingProfile(task_id=sample.id,settings={'task_type':'practice'}))
        db.add(TaskFeedback(task_id=sample.id,client_action_id=f'demo-practice-feedback-{index}',outcome='completed',
            actual_minutes=50,title_snapshot=sample.title,deadline_snapshot=deadline,priority_snapshot='normal',
            family_snapshot='practice',category_name_snapshot='练习',family_confirmed_snapshot=True,initial_estimate_minutes=60,
            completed_at=completed_at,created_at=completed_at))
        started_at=datetime(2026,month,day,16,10,tzinfo=SHANGHAI)
        db.add(TaskWorkSession(task_id=sample.id,client_action_id=f'demo-practice-timer-{index}',status='stopped',
            family_snapshot='practice',category_name_snapshot='练习',family_confirmed_snapshot=True,accumulated_seconds=50*60,
            segment_started_at=None,started_at=started_at,updated_at=completed_at))
    plan=Plan(week_start=WEEK_START,status='confirmed',source_revision=get_or_create_planning_state(db).revision,task_ids=[t.id for t,_,_ in tasks],confirmed_at=DEMO_NOW)
    db.add(plan);db.flush()
    from datetime import timedelta
    for t,start,_ in tasks:
        db.add(PlanItem(plan_id=plan.id,kind='task',task_id=t.id,title_snapshot=t.title,start_at=start,end_at=start+timedelta(minutes=t.duration_minutes)))
    rules=time_rules(db);names={r.id:r.title for r in rules}
    for r in expand_time_rules(WEEK_START,rules):
        if r.kind=='course': db.add(PlanItem(plan_id=plan.id,kind='course',time_rule_id=r.time_rule_id,title_snapshot=names[r.time_rule_id],start_at=r.start_at,end_at=r.end_at))
    from app.services.assistant_scheduler import validate_assistant
    from app.services.assistant_state import time_rules as load_rules
    task_facts=[dict(ref=f'task:{task.id}',title=task.title,duration_minutes=task.duration_minutes,deadline=task.deadline.isoformat(),priority=task.priority.value if hasattr(task.priority,'value') else task.priority,profile={}) for task,_,_ in tasks]
    schedule_facts=[dict(ref=f'task:{task.id}',title=task.title,start_at=start.isoformat(),end_at=(start+timedelta(minutes=task.duration_minutes)).isoformat()) for task,start,_ in tasks]
    errors=validate_assistant(WEEK_START,DEMO_NOW,task_facts,load_rules(db),schedule_facts,[])
    if errors: raise ValueError('第7周演示计划未通过独立校验：'+'；'.join(errors))
    from app.services.taxonomy import migrate_taxonomy
    migrate_taxonomy(db)
    bump_revision(db)


def initialize(path,source=None):
    target=demo_database(str(path));target.parent.mkdir(parents=True,exist_ok=True)
    engine=create_sqlite_engine(f'sqlite:///{target.as_posix()}');upgrade_database(engine)
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
