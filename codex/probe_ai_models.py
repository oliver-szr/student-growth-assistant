"""Compare configured gateway models without changing .env or printing secrets."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.services.assistant_ai import parse_message
from app.services.claude_client import AIServiceError


async def main():
    state=httpx.get('http://127.0.0.1:8001/api/assistant/sessions/1').json()
    assert state['settings']['demo']
    context=dict(now=state['settings']['now'],tasks=state['proposal']['tasks'],history=[])
    results=[]
    for model in sys.argv[1:]:
        os.environ['CLAUDE_MODEL']=model
        start=time.monotonic()
        try:
            parsed=await parse_message('明天中午12:00前还要交汇报稿，预计一小时，很重要。',context)
            data=parsed.model_dump(mode='json',exclude_unset=True)
            result=dict(model=model,seconds=round(time.monotonic()-start,2),parsed=data)
        except AIServiceError as exc:
            result=dict(model=model,seconds=round(time.monotonic()-start,2),error=exc.code)
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    evidence=ROOT/'codex/evidence';evidence.mkdir(exist_ok=True)
    (evidence/'model-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())
