from datetime import date
import pytest


def test_dated_course_api(client):
    r = client.post('/api/time-rules', json=dict(kind='course', title='课程', recurrence='once', date='2026-10-08', start_time='14:00', end_time='15:35'))
    assert r.status_code == 201
    from app.services.validator import expand_time_rules
    from app.services.scheduling_types import TimeRuleInput
    from datetime import time
    rule = TimeRuleInput(1, 'course', '课程', 'once', time(14), time(15,35), date=date(2026,10,8))
    assert len(expand_time_rules(date(2026,10,5), [rule])) == 1
    assert expand_time_rules(date(2026,10,12), [rule]) == ()


def test_weeks_parser_and_pending():
    from app.services.course_import import parse_weeks, expand_source
    assert parse_weeks('4-6周(双),13周') == [4,6,13]
    assert parse_weeks('3-7周(单),8-11周') == [3,5,7,8,9,10,11]
    source = dict(semester_week_1_monday='2026-08-31', course_entries=[
        dict(course='操作系统', weekday=3, weeks_raw='1-2周,7-8周,11-13周(单)', start_time='09:40', end_time='12:15'),
        dict(course='云计算', weekday=4, weeks_raw='1-6周', start_time='14:00', end_time='15:35')], practice_entries=[{'course':'实训'}])
    rows, warnings = expand_source(source)
    assert len(rows) == 6
    assert rows[-1]['date'] == '2026-10-08'
    assert len(warnings) == 2


def test_demo_clock_cannot_change_normal_database(monkeypatch):
    from app.services.assistant_clock import clock_settings
    monkeypatch.setenv('SGA_DEMO_NOW', '2026-10-07T18:00:00+08:00')
    monkeypatch.delenv('SGA_DEMO', raising=False)
    settings = clock_settings()
    assert settings['demo'] is False
    assert settings['now'] != '2026-10-07T18:00:00+08:00'
    monkeypatch.setenv('SGA_DEMO', '1')
    monkeypatch.setenv('SGA_DATABASE_PATH', 'backend/data/app.db')
    with pytest.raises(ValueError):
        clock_settings()


def test_import_rejects_existing_course_overlap_before_writing(client,test_engine):
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.models import TimeRule,CourseImport
    from app.services.course_import import import_source
    client.post('/api/time-rules',json=dict(kind='course',title='已有课程',recurrence='weekly',weekday=4,start_time='14:00',end_time='15:35'))
    source=dict(semester_week_1_monday='2026-08-31',course_entries=[dict(course='新增课程',weekday=4,weeks_raw='6周',start_time='15:00',end_time='16:00')])
    with Session(test_engine) as db:
        with pytest.raises(ValueError,match='已有课程'):
            import_source(db,source)
        assert len(db.scalars(select(TimeRule)).all())==1
        assert not db.scalars(select(CourseImport)).all()
