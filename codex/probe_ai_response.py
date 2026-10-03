"""Diagnose output truncation using safe response metadata only."""
import json
import os
import sys
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.services.assistant_ai import SYSTEM
from app.services.claude_client import get_claude_config,extract_text,AIServiceError
from app.assistant_schemas import ParsedCommand

os.environ['CLAUDE_MODEL']='glm-5.3-flash'
config=get_claude_config()
state=httpx.get('http://127.0.0.1:8001/api/assistant/sessions/1').json()
assert state['settings']['demo']
context=dict(now=state['settings']['now'],tasks=state['proposal']['tasks'],history=[])
text=json.dumps(dict(message='实验报告改到今晚19:00，汇报稿明早做。',context=context),ensure_ascii=False)
start=time.monotonic()
response=httpx.post(config.base_url.rstrip('/').removesuffix('/v1')+'/v1/messages',headers={'x-api-key':config.api_key,'anthropic-version':config.api_version},json=dict(model=config.model,max_tokens=600,thinking={'type':'disabled'},system=SYSTEM,messages=[dict(role='user',content=text)]),timeout=20)
result=dict(status=response.status_code,seconds=round(time.monotonic()-start,2))
if response.status_code==200:
    body=response.json();result.update(stop_reason=body.get('stop_reason'),usage=body.get('usage'),block_types=[b.get('type') for b in body.get('content',[])])
    try:
        raw=extract_text(body)
        result['parsed']=ParsedCommand.model_validate_json(raw).model_dump(mode='json',exclude_unset=True)
    except (ValueError,AIServiceError):result['parse_error']='invalid'
print(json.dumps(result,ensure_ascii=False))
(ROOT/'codex/evidence/response-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
