from datetime import datetime, date, time
from app.services.scheduling_types import SHANGHAI, TimeRuleInput

NOW = datetime(2026,10,7,18,tzinfo=SHANGHAI)
WEEK = date(2026,10,5)


def task(ref, minutes=60, deadline='2026-10-08T12:00:00+08:00', priority='normal', **profile):
    return dict(ref=ref, title=ref, duration_minutes=minutes, deadline=deadline, priority=priority, status='todo', profile=profile)


def test_no_past_course_overlap_and_deadline():
    from app.services.assistant_scheduler import arrange, validate_assistant
    course = TimeRuleInput(1,'course','优化','once',time(8,50),time(10,25),date=date(2026,10,8))
    result = arrange(WEEK, NOW, [task('task:1')], [course], [])
    assert result['status'] == 'ready'
    item = result['items'][0]
    assert datetime.fromisoformat(item['start_at']) >= NOW
    assert datetime.fromisoformat(item['end_at']) <= datetime(2026,10,8,12,tzinfo=SHANGHAI)
    assert validate_assistant(WEEK,NOW,[task('task:1')],[course],result['items'],[]) == []


def test_fixed_course_conflict_has_alternatives_not_ready():
    from app.services.assistant_scheduler import arrange
    course = TimeRuleInput(1,'course','云计算','once',time(14),time(15,35),date=date(2026,10,8))
    t = task('draft:a',120,'2026-10-09T20:00:00+08:00', fixed_start='2026-10-08T14:00:00+08:00')
    result = arrange(WEEK,NOW,[t],[course],[])
    assert result['status'] == 'conflict'
    assert '云计算' in str(result['diagnostics'])
    assert result['alternatives']


def test_urgent_task_moves_low_priority_and_preserves_lock():
    from app.services.assistant_scheduler import arrange
    previous = [dict(ref='task:1',start_at='2026-10-08T10:30:00+08:00',end_at='2026-10-08T11:30:00+08:00'),dict(ref='task:2',start_at='2026-10-08T19:00:00+08:00',end_at='2026-10-08T20:00:00+08:00')]
    tasks = [task('task:1', deadline='2026-10-11T22:00:00+08:00',priority='low'),task('task:2',deadline='2026-10-11T22:00:00+08:00', locked=True),task('draft:new',fixed_start='2026-10-08T10:30:00+08:00',priority='high')]
    result = arrange(WEEK,NOW,tasks,[],previous)
    assert result['status'] == 'ready'
    items={x['ref']:x for x in result['items']}
    assert items['task:1']['start_at'] != previous[0]['start_at']
    assert items['task:2']['start_at'] == previous[1]['start_at']
    assert items['draft:new']['start_at'] == '2026-10-08T10:30:00+08:00'


def test_capacity_failure_never_returns_partial_success():
    from app.services.assistant_scheduler import arrange
    result=arrange(WEEK,NOW,[task('draft:x',900)],[],[])
    assert result['status']=='no_plan'
    assert result['items']==[]


def test_confirmation_validator_rejects_time_advance_and_locked_move():
    from app.services.assistant_scheduler import validate_assistant
    old=[dict(ref='task:1',start_at='2026-10-08T10:30:00+08:00',end_at='2026-10-08T11:30:00+08:00')]
    moved=[dict(ref='task:1',start_at='2026-10-08T11:00:00+08:00',end_at='2026-10-08T12:00:00+08:00')]
    errors=validate_assistant(WEEK,datetime(2026,10,8,11,15,tzinfo=SHANGHAI),[task('task:1',locked=True)],[],moved,old)
    assert errors


def test_personal_preference_can_change_candidate_schedule_without_breaking_deadline():
    from app.services.assistant_scheduler import arrange
    prefs={'task_windows':{'writing':[{'start':'08:00','end':'12:00'}]},'avoid_windows':[], 'deadline_buffer_hours':0,'adjustment_mode':'balanced'}
    t=task('draft:report',60,'2026-10-11T22:00:00+08:00')
    t['task_type']='writing'
    result=arrange(WEEK,NOW,[t],[],[],preferences=prefs,include_strategies=True)
    assert result['status']=='ready'
    assert result['candidate_options']
    preferred=min(result['candidate_options'],key=lambda x:x['metrics']['preference_misses_weight'])
    assert datetime.fromisoformat(preferred['items'][0]['start_at']).time().hour < 12
    assert all(datetime.fromisoformat(x['end_at']) <= datetime.fromisoformat(t['deadline']) for c in result['candidate_options'] for x in c['items'])
