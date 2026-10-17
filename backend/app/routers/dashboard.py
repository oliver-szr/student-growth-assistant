"""Page snapshots use bulk queries. Full execution history remains on demand."""
from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Task, TaskGrowthContext, TaskFeedback, TaskWorkSession, GrowthWeeklyReview, GrowthInsight
from ..schemas import TaskResponse
from ..services.assistant_clock import assistant_now
from ..services.growth_tracking import session_payload
from ..services.taxonomy import categories_payload, rules_payload
from .growth_attention import _duration_advice
from .goals import list_goals
from .growth_profile import get_growth_profile

router=APIRouter(tags=['Workspace Snapshots'])

def task_snapshot(db):
    now=assistant_now()
    tasks=list(db.scalars(select(Task).order_by(Task.id)).all())
    contexts={c.task_id:c for c in db.scalars(select(TaskGrowthContext)).all()}
    sessions={}
    latest=select(func.max(TaskWorkSession.id).label('id')).group_by(TaskWorkSession.task_id).subquery()
    for row in db.scalars(select(TaskWorkSession).join(latest,TaskWorkSession.id==latest.c.id)).all():sessions[row.task_id]=session_payload(row)
    samples=list(db.scalars(select(TaskFeedback).where(TaskFeedback.outcome=='completed',TaskFeedback.retracted_at.is_(None),TaskFeedback.family_confirmed_snapshot.is_(True),TaskFeedback.completed_at>=now-timedelta(days=28),TaskFeedback.completed_at<=now,TaskFeedback.actual_minutes.is_not(None)).order_by(TaskFeedback.id.desc())).all())
    feedbacks=list(db.scalars(select(TaskFeedback)).all())
    from collections import Counter
    counts=dict(Counter(row.task_id for row in feedbacks))
    context_data={}; advice={}
    for task in tasks:
        c=contexts.get(task.id) or TaskGrowthContext(task_id=task.id,initial_estimate_minutes=task.duration_minutes,family='',family_confirmed=False)
        context_data[task.id]={'task_id':task.id,'goal_id':c.goal_id,'family':c.family,'family_confirmed':c.family_confirmed,'initial_estimate_minutes':c.initial_estimate_minutes,'deadline_source':c.deadline_source or 'external'}
        advice[task.id]=_duration_advice(db,task,c,now,samples) if task.task_kind == 'executable' else {'status':'container'}
    from ..services.task_hierarchy import serialize_tasks
    return {'tasks':[t.model_dump(mode='json') for t in serialize_tasks(db,tasks,contexts,feedbacks)],'contexts':context_data,'sessions':sessions,'advice':advice,'feedback_counts':counts,'categories':categories_payload(db)}

@router.get('/api/tasks/dashboard')
def tasks_dashboard(db:Session=Depends(get_db)):
    return task_snapshot(db)

@router.get('/api/profile/context')
def profile_context(db:Session=Depends(get_db)):
    data=task_snapshot(db)
    return {**data,'profile':get_growth_profile(db),'goals':list_goals(db).model_dump(mode='json')['goals'],'rules':rules_payload(db)}

@router.get('/api/review/context')
def review_context(db:Session=Depends(get_db)):
    data=task_snapshot(db);now=assistant_now();week=now.date()-timedelta(days=now.weekday())
    from .growth_reviews import _review_payload
    reviews=list(db.scalars(select(GrowthWeeklyReview).where(GrowthWeeklyReview.week_start==week).order_by(GrowthWeeklyReview.id.desc()).limit(1)).all())
    insights=list(db.scalars(select(GrowthInsight).order_by(GrowthInsight.id.desc()).limit(100)).all())
    from .growth_insights import _insight_payload
    return {**data,'week_start':week.isoformat(),'goals':list_goals(db).model_dump(mode='json')['goals'],'reviews':[_review_payload(r) for r in reviews],'insights':[_insight_payload(r) for r in insights]}
