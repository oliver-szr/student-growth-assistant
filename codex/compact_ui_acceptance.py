from playwright.sync_api import sync_playwright
from pathlib import Path
import json
out=Path('codex/.local/compact-ui');out.mkdir(parents=True,exist_ok=True)
report={'checks':[],'errors':[]}
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge',headless=True)
 page=b.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
 for w,h in [(1381,1163),(1161,1163),(390,844)]:
  page.set_viewport_size({'width':w,'height':h});page.goto('http://localhost:5175/',wait_until='networkidle')
  for name in ['规划','复盘','我的档案']:
   page.get_by_role('button',name=name,exact=True).first.click();page.wait_for_timeout(900)
   assert page.locator('h2').filter(has_text=name).first.is_visible()
   overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
   assert not overflow,(w,name,'overflow')
   if w<1024 and name=='我的档案':page.locator('.workbench-switch').get_by_role('button',name='结果',exact=True).click()
   page.screenshot(path=str(out/f'{w}-{name}.png'),full_page=True)
   report['checks'].append(f'{w}x{h} {name} no overflow')
 page.get_by_role('button',name='新增目标',exact=True).click()
 page.locator('#goal-editor input').first.fill('保留输入验证')
 page.get_by_role('button',name='新增目标',exact=True).click();page.get_by_role('button',name='新增目标',exact=True).click()
 assert page.locator('#goal-editor input').first.input_value()=='保留输入验证'
 report['checks'].append('goal editor collapse preserves input')
 page.get_by_role('button',name='规划',exact=True).first.click();page.wait_for_timeout(500)
 page.get_by_role('button',name='手动添加',exact=True).click()
 assert page.locator('.manual-task').get_by_label('剩余时长（分钟）',exact=True).is_visible()
 assert page.locator('.week-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1 && e.scrollHeight<=e.clientHeight+1')
 assert not report['errors'],report['errors']
 b.close()
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
