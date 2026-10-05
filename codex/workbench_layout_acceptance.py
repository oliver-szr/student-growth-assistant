"""Read-only layout checks on the live preview; writes screenshots only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'codex'/'.local'/'layout-upgrade'/'after';OUT.mkdir(parents=True,exist_ok=True)
report={'checks':[],'errors':[]}
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 page=browser.new_page(locale='zh-CN',timezone_id='America/Los_Angeles')
 page.on('pageerror',lambda e:report['errors'].append(str(e)))
 for width,height in [(1381,1163),(1161,1163),(1024,1163),(1023,1163),(390,844)]:
  page.set_viewport_size({'width':width,'height':height});page.goto('http://localhost:5175/',wait_until='networkidle')
  for tab in ['规划','复盘','我的档案']:
   page.get_by_role('button',name=tab,exact=True).first.click()
   expect(page.locator('.workbench-grid')).to_be_visible(timeout=15000)
   page.wait_for_timeout(300)
   grid=page.locator('.workbench-grid')
   chat=grid.locator('.workbench-chat-column');result=grid.locator('.workbench-result-column')
   if width>=1024:
    assert chat.is_visible() and result.is_visible()
    cb,rb=chat.bounding_box(),result.bounding_box();assert rb['x']>=cb['x']+cb['width']+18
    assert 319<=cb['width']<=441
   else:
    assert chat.is_visible() and not result.is_visible()
    field=chat.locator('textarea').first;field.fill('切换保留输入')
    page.locator('.workbench-switch').get_by_role('button',name='日程' if tab=='规划' else '结果',exact=True).click()
    assert result.is_visible() and not chat.is_visible()
    page.locator('.workbench-switch').get_by_role('button',name='聊天',exact=True).click()
    assert field.input_value()=='切换保留输入';field.fill('')
    page.locator('.workbench-switch').get_by_role('button',name='日程' if tab=='规划' else '结果',exact=True).click()
   assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),(width,tab)
   title=page.locator('h2').filter(has_text=tab).first
   assert title.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')==(24 if width<=600 else 28)
   assert chat.locator('h3').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')==18
   assert chat.locator('textarea').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')==15
   if width>=1024:
    submit=chat.get_by_role('button',name='发送',exact=True).bounding_box()
    assert submit['y']+submit['height']<=height,(width,tab,'compose off first viewport')
   if tab=='规划':
    assert page.locator('.day-column').count()==7
    assert page.locator('.week-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1 && e.scrollHeight<=e.clientHeight+1')
    block=page.locator('.calendar-block').first;block.focus();page.keyboard.press('Enter')
    expect(page.get_by_role('dialog')).to_be_visible();page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).not_to_be_visible();assert block.evaluate('(e)=>e===document.activeElement')
   page.screenshot(path=str(OUT/f'{width}-{tab}.png'),full_page=True)
   report['checks'].append(f'{width}x{height} {tab}: columns, overflow, view preservation')
 page.get_by_role('button',name='我的档案',exact=True).first.click()
 page.locator('.workbench-switch').get_by_role('button',name='结果',exact=True).click()
 page.get_by_role('button',name='新增目标',exact=True).click()
 page.locator('#goal-editor input').first.fill('保留输入验证')
 page.locator('.workbench-switch').get_by_role('button',name='聊天',exact=True).click()
 page.locator('.workbench-switch').get_by_role('button',name='结果',exact=True).click()
 assert page.locator('#goal-editor input').first.input_value()=='保留输入验证'
 assert not report['errors'],report['errors']
 browser.close()
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
