from datetime import date, datetime, time
import pytest
from app.services.assistant_scheduler import score, arrange, validate_assistant
from app.services.scheduling_types import SHANGHAI, TimeRuleInput

WEEK = date(2026, 10, 12)
NOW = datetime(2026, 10, 18, 21, tzinfo=SHANGHAI)

def task(ref='task:1', minutes=45, **profile):
    return dict(ref=ref, title=ref, priority='normal', status='todo', duration_minutes=minutes,
                deadline='2026-10-21T12:00:00+08:00', profile=profile)

def test_goal_delay_direction():
    penalties=[]
    item=dict(ref='task:1', start_at='2026-10-19T09:00:00+08:00', end_at='2026-10-19T09:45:00+08:00')
    for priority in (1,2,3):
        t={**task(), 'goal':{'priority':priority}}
        penalties.append(score([item],{t['ref']:t},{},WEEK)[4])
    assert penalties[0] > penalties[1] > penalties[2] > 0

@pytest.mark.parametrize('mode', ['balanced','preference','stable'])
@pytest.mark.parametrize('strategy', ['balanced','preference','stable'])
def test_strategy_independent_of_default(mode,strategy):
    t=task(); t['task_type']='writing'
    item=dict(ref=t['ref'],start_at='2026-10-19T19:00:00+08:00',end_at='2026-10-19T19:45:00+08:00')
    prefs={'task_windows':{'writing':[{'start':'08:00','end':'12:00'}]}}
    assert score([item],{t['ref']:t},{},WEEK,{**prefs,'adjustment_mode':mode},strategy) == score([item],{t['ref']:t},{},WEEK,{**prefs,'adjustment_mode':'balanced'},strategy)

def test_five_minute_crossweek_start():
    t=task(fixed_start='2026-10-19T08:05:00+08:00')
    result=arrange(WEEK,NOW,[t],[],[])
    assert result['status']=='ready'
    assert result['items'][0]['start_at']==t['profile']['fixed_start']
    assert validate_assistant(WEEK,NOW,[t],[],result['items'],[]) == []

def test_split_180_across_two_90_windows():
    windows=[dict(start_at='2026-10-19T08:05:00+08:00',end_at='2026-10-19T09:35:00+08:00'),dict(start_at='2026-10-20T08:05:00+08:00',end_at='2026-10-20T09:35:00+08:00')]
    t=task(minutes=180,allowed_windows=windows)
    assert arrange(WEEK,NOW,[t],[],[])['status']=='no_plan'
    t['profile'].update(splittable=True,min_block_minutes=30,max_segments=2)
    result=arrange(WEEK,NOW,[t],[],[])
    assert result['status']=='ready'
    assert len(result['items'])==2
    assert sum((datetime.fromisoformat(x['end_at'])-datetime.fromisoformat(x['start_at'])).total_seconds()/60 for x in result['items'])==180
    assert validate_assistant(WEEK,NOW,[t],[],result['items'],[]) == []
    assert validate_assistant(WEEK,NOW,[t],[],result['items'][:1],[])

@pytest.mark.parametrize('minutes',[45,75,105])
def test_exact_duration_and_current_time_ceiling(minutes):
    now=datetime(2026,10,19,8,6,1,tzinfo=SHANGHAI)
    t=task(minutes=minutes)
    r=arrange(WEEK,now,[t],[],[])
    assert r['status']=='ready'
    a,b=map(datetime.fromisoformat,(r['items'][0]['start_at'],r['items'][0]['end_at']))
    assert a.minute==10 and (b-a).total_seconds()==minutes*60

def test_goal_priority_places_most_important_first():
    a={**task('task:1',60),'goal':{'priority':3}}
    b={**task('task:2',60),'goal':{'priority':1}}
    result=arrange(WEEK,NOW,[a,b],[],[])
    assert result['status']=='ready'
    starts={x['ref']:x['start_at'] for x in result['items']}
    assert starts['task:2']<starts['task:1']

def test_next_week_course_blocks_exact_time():
    t=task(fixed_start='2026-10-19T08:05:00+08:00')
    rule=TimeRuleInput(1,'course','课','weekly',time(8),time(9,35),weekday=1)
    r=arrange(WEEK,NOW,[t],[rule],[])
    assert r['status']=='conflict' and r['alternatives']

def test_split_maximum_and_locked_segments():
    t=task(minutes=180,splittable=True,min_block_minutes=30,max_segments=2)
    prior=[dict(ref=t['ref'],title=t['title'],start_at='2026-10-19T08:05:00+08:00',end_at='2026-10-19T09:35:00+08:00'),dict(ref=t['ref'],title=t['title'],start_at='2026-10-20T08:05:00+08:00',end_at='2026-10-20T09:35:00+08:00')]
    t['profile']['locked']=True
    r=arrange(WEEK,NOW,[t],[],prior)
    assert r['status']=='ready' and r['items']==prior
    assert validate_assistant(WEEK,NOW,[t],[],[{**prior[0],'start_at':'2026-10-19T08:10:00+08:00'},prior[1]],prior)

def test_preference_and_stability_tradeoff_is_real():
    t=task(minutes=60);t['task_type']='writing'
    prior=[dict(ref=t['ref'],title=t['title'],start_at='2026-10-19T19:00:00+08:00',end_at='2026-10-19T20:00:00+08:00')]
    prefs={'task_windows':{'writing':[{'start':'08:00','end':'12:00'}]},'adjustment_mode':'stable'}
    result=arrange(WEEK,NOW,[t],[],prior,preferences=prefs,include_strategies=True)
    options=result['candidate_options']
    stable=next(x for x in options if x['strategy']=='stable')
    assert stable['items']==prior
    other=next(x for x in options if x['strategy']!='stable')
    assert other['items'][0]['start_at'][11:13] in ('08','09','10','11')
    assert result['items']==stable['items']
    assert len({tuple((x['ref'],x['start_at'],x['end_at']) for x in option['items']) for option in options})==len(options)
