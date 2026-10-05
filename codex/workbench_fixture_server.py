"""Test-only AI fixtures with real business services on an isolated demo database."""
import asyncio,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
db=Path(os.environ['SGA_DATABASE_PATH']).resolve()
assert db.parent== (ROOT/'codex'/'.runtime').resolve() and db.name.startswith('demo-layout-')
from app.services import assistant_ai
from app.services.claude_client import AIServiceError
attempts={}
async def fixture(scope,text,context):
    if text=='取消测试': await asyncio.sleep(8)
    attempts[text]=attempts.get(text,0)+1
    if text=='失败重试测试' and attempts[text]==1: raise AIServiceError('AI_UNAVAILABLE')
    if text=='长回复测试': return {'reply':'**完整说明**\n'+'\n'.join(f'- 第{i}条：这是用于验证完整消息和阅读位置的测试内容。' for i in range(1,61)),'questions':[],'operations':[]}
    if text=='继续讨论': return {'reply':'**下一步**：这是一条新的完整回复。','questions':[],'operations':[]}
    if scope=='profile':
        return {'reply':'**请核对修改**\n- 目标改为每周两篇。\n- 偏好名称同步调整。','questions':[], 'operations':[
            {'op':'update_goal','goal_id':context['goals'][0]['id'],'fields':{'weekly_target':2}},
            {'op':'update_preference_rule','id':context['preference_rules'][0]['id'],'fields':{'name':'写作上午完成（验收）'}}]}
    task=next(t for t in context['tasks'] if t['status']=='todo')
    return {'reply':'**执行记录待保存**\n实际投入为15分钟，尚未完成。','questions':[], 'operations':[{'op':'record_feedback','task_id':task['id'],'outcome':'partial','actual_minutes':15,'remaining_minutes':60}]}
async def review(facts,suggestions): raise AIServiceError('AI_UNAVAILABLE')
assistant_ai.workspace_message=fixture
assistant_ai.select_growth_review=review
from app.main import app
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ['LAYOUT_TEST_PORT']),log_level='warning')
