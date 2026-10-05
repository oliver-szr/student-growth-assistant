"""Functional UI regression: isolated SQLite, fixture AI, real API transactions."""
import json,os,socket,subprocess,sys,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'codex'/'.local'/'layout-upgrade';OUT.mkdir(parents=True,exist_ok=True)
scenario=json.loads((ROOT/'codex'/'demo_scenario.json').read_text(encoding='utf-8'))
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env={**os.environ,'SGA_DEMO':'1','SGA_DEMO_NOW':scenario['now'],'SGA_DATABASE_PATH':str(ROOT/'codex'/'.runtime'/f'demo-layout-{uuid.uuid4().hex}.db'),'LAYOUT_TEST_PORT':str(port),'PYTHONIOENCODING':'utf-8'}
creation=getattr(subprocess,'CREATE_NO_WINDOW',0)
subprocess.run([sys.executable,str(ROOT/'codex'/'demo_init.py'),'--database',env['SGA_DATABASE_PATH']],cwd=ROOT,env=env,check=True,stdout=subprocess.DEVNULL,creationflags=creation)
report={'ai':'fixture responses, not real model','checks':[],'errors':[]}
log=(OUT/'fixture-server.log').open('w',encoding='utf-8')
server=subprocess.Popen([sys.executable,str(ROOT/'codex'/'workbench_fixture_server.py')],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=creation)
try:
 api=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=20)
 for _ in range(100):
  try:
   settings=api.get('/api/assistant/settings').json();break
  except Exception:
   assert server.poll() is None,'fixture server exited';time.sleep(.15)
 else:raise AssertionError('server startup timeout')
 assert settings['demo'] and settings['week_start']==scenario['week_start']
 with sync_playwright() as p:
  browser=p.chromium.launch(channel='msedge',headless=True)
  page=browser.new_page(viewport={'width':1381,'height':1163},locale='zh-CN',timezone_id='America/Los_Angeles')
  page.on('pageerror',lambda e:report['errors'].append(str(e)))
  def proxy(route):
   path=urlsplit(route.request.url)
   response=route.fetch(url=f'http://127.0.0.1:{port}{path.path}'+('?' + path.query if path.query else ''))
   route.fulfill(response=response,headers={**response.headers,'access-control-allow-origin':'http://localhost:5175'})
  page.route('**/api/**',proxy)
  page.goto('http://localhost:5175/',wait_until='networkidle')
  page.get_by_role('button',name='手动添加',exact=True).click()
  form=page.locator('.manual-task');form.get_by_label('名称',exact=True).fill('布局候选验证')
  form.get_by_label('截止时间',exact=True).fill('2026-10-18T20:00')
  form.get_by_role('button',name='生成候选',exact=True).click()
  adopt=page.get_by_role('button',name='采用方案',exact=True);expect(adopt).to_be_enabled(timeout=20000)
  assert page.locator('.workbench-result-column #planning-proposal').count()==1
  assert not any(t['title']=='布局候选验证' for t in api.get('/api/tasks').json())
  options=page.locator('.candidate-option')
  if options.count()>1:
   options.nth(1).click();expect(options.nth(1)).to_have_attribute('aria-pressed','true')
  adopt.click();expect(page.get_by_role('heading',name='已采用方案',exact=True)).to_be_visible()
  assert any(t['title']=='布局候选验证' for t in api.get('/api/tasks').json())
  report['checks']+=['candidate in result column','preview does not write tasks','candidate selection synchronizes','adopt persists']
  page.get_by_role('button',name='我的档案',exact=True).first.click()
  field=page.get_by_label('修改目标或偏好',exact=True);expect(field).to_be_enabled()
  field.fill('目标每周两篇，并修改偏好名');page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  save=page.get_by_role('button',name='保存修改',exact=True);expect(save).to_be_enabled(timeout=15000)
  assert page.locator('.workbench-result-column .workspace-draft').count()==1
  assert api.get('/api/goals').json()['goals'][0]['weekly_target']==3
  assert page.locator('.workspace-message strong').filter(has_text='请核对修改').count()==1
  save.click();expect(page.get_by_text('已保存',exact=True)).to_be_visible()
  assert api.get('/api/goals').json()['goals'][0]['weekly_target']==2
  expect(page.locator('.preference-rule-title strong').filter(has_text='写作上午完成（验收）')).to_be_visible()
  report['checks']+=['profile draft at right','AI bold text preserved','profile confirm atomically saves and refreshes']
  page.get_by_role('button',name='复盘',exact=True).first.click()
  field=page.get_by_label('记录执行或询问进展',exact=True);expect(field).to_be_enabled()
  field.fill('补录15分钟，部分完成');page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  save=page.get_by_role('button',name='保存记录',exact=True);expect(save).to_be_enabled(timeout=15000);save.click()
  expect(page.locator('.review-metrics').get_by_text('15',exact=False)).to_be_visible(timeout=20000)
  reviews=api.get('/api/growth/reviews').json()['reviews'];assert reviews[0]['facts']['confirmed_actual_minutes']==15
  assert reviews[0]['summary_mode']=='facts_only'
  report['checks']+=['feedback confirm refreshes review facts','AI review fallback remains explicit']
  page.reload(wait_until='networkidle');page.get_by_role('button',name='我的档案',exact=True).first.click()
  expect(page.locator('.preference-rule-title strong').filter(has_text='写作上午完成（验收）')).to_be_visible()
  field=page.get_by_label('修改目标或偏好',exact=True);expect(field).to_be_enabled();field.fill('失败重试测试');page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  retry=page.get_by_role('button',name='重试',exact=True);expect(retry).to_be_visible(timeout=15000)
  assert field.input_value()=='失败重试测试';retry.click();expect(page.get_by_role('button',name='保存修改',exact=True)).to_be_enabled(timeout=15000)
  page.get_by_role('button',name='放弃',exact=True).click()
  field.fill('取消测试')
  with page.expect_response(lambda response:response.url.endswith('/runs') and response.request.method=='POST'):
   page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  cancel=page.get_by_role('button',name='取消',exact=True);expect(cancel).to_be_visible();cancel.focus();page.keyboard.press('Enter');expect(field).to_be_enabled()
  assert field.input_value()=='取消测试';assert api.get('/api/goals').json()['goals'][0]['weekly_target']==2
  report['checks']+=['refresh restores saved data','failure preserves input and retry works','cancel preserves input without save']
  field.fill('长回复测试');page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  expect(page.get_by_text('第60条：这是用于验证完整消息和阅读位置的测试内容。',exact=True)).to_be_attached(timeout=15000)
  history=page.locator('.workspace-chat-messages');history.evaluate('(e)=>{e.scrollTop=0;e.dispatchEvent(new Event("scroll",{bubbles:true}))}')
  field.fill('继续讨论');page.locator('.workspace-chat-input').get_by_role('button',name='发送',exact=True).click()
  expect(page.get_by_text('这是一条新的完整回复。',exact=False)).to_be_attached(timeout=15000)
  expect(page.get_by_role('button',name='有新回复',exact=True)).to_be_visible()
  assert history.evaluate('(e)=>e.scrollTop')<5
  page.get_by_role('button',name='有新回复',exact=True).click()
  assert history.evaluate('(e)=>e.scrollHeight-e.scrollTop-e.clientHeight')<65
  report['checks']+=['long AI reply remains complete','new reply does not displace history reader','new reply button scrolls only chat']
  assert not report['errors'],report['errors']
  page.screenshot(path=str(OUT/'functional.png'),full_page=True)
  browser.close()
finally:
 server.terminate()
 try:server.wait(timeout=10)
 except subprocess.TimeoutExpired:server.kill();server.wait()
 log.close()
(OUT/'functional-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
