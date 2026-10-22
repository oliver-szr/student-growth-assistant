// Stage 2 acceptance on the explicit isolated integration_demo server only.
// No reports/screenshots are written. Set SGA_PLAYWRIGHT_PATH for a bundled runtime.
const runtime=process.env.SGA_PLAYWRIGHT_PATH || 'playwright';
const { chromium } = require(runtime);
const { expect } = require(runtime+'/test');
const assert = require('node:assert/strict');
const api = process.env.SGA_TEST_API || 'http://127.0.0.1:8019';
const web = process.env.SGA_TEST_WEB || 'http://127.0.0.1:5187';
async function call(path, method='GET', body) {
  const response=await fetch(api+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  assert.equal(response.headers.get('x-sga-integration-mock'),'1');
  const value=await response.json();assert.ok(response.ok,JSON.stringify(value));return value;
}
(async()=>{
  assert.ok(['localhost','127.0.0.1','[::1]'].includes(new URL(api).hostname));
  const settings=await call('/api/assistant/settings');assert.ok(settings.demo);
  assert.deepEqual(await call('/api/tasks'),[], 'Use a fresh anonymous demo server');
  const checks=[],errors=[];const checked=text=>{checks.push(text);console.log('PASS '+text)};
  const browser=await chromium.launch({channel:'msedge',headless:true});
  let page;
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'America/Los_Angeles'});
    page=await context.newPage();page.on('pageerror',error=>{errors.push(error.message);console.error('PAGE ERROR '+error.message)});
    await page.goto(web);await expect(page.getByRole('button',{name:'＋ 新对话',exact:true})).toBeEnabled();
    const nav=page.getByRole('navigation',{name:'主导航'});
    const home=()=>nav.getByRole('button',{name:'首页',exact:true}).click();
    const send=async text=>{
      await page.getByRole('textbox',{name:'会话输入',exact:true}).fill(text);
      const response=page.waitForResponse(r=>r.url().endsWith('/runs')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'发送',exact:true}).click();const result=await (await response).json();
      await expect.poll(async()=>(await call(`/api/conversations/${result.session_id}/runs/${result.id}`)).status,{timeout:30000}).toBe('completed');
      await expect(page.locator('.reply-status')).toContainText('回复已完成',{timeout:30000});
    };
    await page.getByRole('button',{name:'＋ 新对话',exact:true}).click();
    await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    await send('讨论学习方向，我暂时不想创建任务。');
    assert.deepEqual(await call('/api/tasks'),[]);assert.equal((await call('/api/reviews/records')).items.length,0);
    checked('B:ordinary_chat_no_business_write');
    await send('匿名拆解：周五20点前完成120分钟的匿名交付。');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    const editor=page.getByRole('region',{name:'共享草案编辑器',exact:true});
    await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('60');
    await editor.getByLabel('子任务 1 预计分钟',{exact:true}).fill('45');
    await home();await send('匿名修改草案：保留我手动修改的45分钟，只调整名称。');
    await nav.getByRole('button',{name:'日程',exact:true}).click();
    await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('45');
    await expect(editor.getByLabel('子任务 1 标题',{exact:true})).toHaveValue('保留手改后的名称');
    assert.deepEqual(await call('/api/tasks'),[]);
    await editor.getByRole('button',{name:'确认正式保存',exact:true}).click();
    await expect(editor.getByRole('heading',{name:/已保存/})).toBeVisible();
    let tasks=await call('/api/tasks');assert.equal(tasks.length,3);
    checked('A:chat_shared_draft_save_before_AI_edit_same_ID_explicit_confirm');
    await home();await send('匿名排程：请为已确认任务安排本周时间。');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await expect(editor.getByRole('button',{name:'确认采用方案',exact:true})).toBeEnabled();
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor.getByRole('heading',{name:/已保存/})).toBeVisible();
    const events=await call('/api/calendar/events?start=2026-10-12&end=2026-10-19');assert.equal(events.events.filter(e=>e.kind==='formal_task').length,2);
    checked('A:separate_schedule_confirmation_formal_events');
    await call('/api/time-rules','POST',{title:'匿名课程',kind:'course',recurrence:'weekly',weekday:4,start_time:'09:00',end_time:'10:00'});
    await call('/api/goals','POST',{title:'匿名月末目标',metric_kind:'count',weekly_target:1,due_date:'2026-10-30'});
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    const calendar=page.getByRole('region',{name:'完整日历',exact:true});
    for(const name of ['天','周','月','年']) {
      await calendar.getByRole('button',{name,exact:true}).click();
      await expect(calendar.getByRole('button',{name,exact:true})).toHaveAttribute('aria-pressed','true');
    }
    await expect(calendar.locator('.fc-multimonth-month')).toHaveCount(12);
    await calendar.getByRole('button',{name:'月',exact:true}).click();
    await expect(calendar.locator('.calendar-goal').first()).toBeVisible();
    await calendar.getByRole('button',{name:'天',exact:true}).click();
    await calendar.getByLabel('日历日期',{exact:true}).fill('2026-10-15');
    const previewDate=page.getByLabel('辅助日程日期',{exact:true});const beforePreview=await previewDate.inputValue();
    await expect(previewDate).toHaveValue(beforePreview);
    await previewDate.fill('2026-10-16');await expect(calendar.getByLabel('日历日期',{exact:true})).toHaveValue('2026-10-15');
    assert.equal(await page.locator('#v2-auxiliary-shared .day-column').count(),1);
    checked('calendar:day_week_month_year_12_months_real_goal_dates_independent_auxiliary_day');
    const task=tasks.find(t=>t.task_kind==='executable');
    await call(`/api/tasks/${task.id}/feedback`,'POST',{client_action_id:'browser-feedback',outcome:'completed',actual_minutes:35});
    await nav.getByRole('button',{name:'复盘',exact:true}).click();
    const review=page.getByRole('region',{name:'回顾与复盘记录',exact:true});
    await expect(review.getByRole('button',{name:'已确认完成 1 项'})).toBeVisible();
    for(const name of ['日','月','周'])await review.getByRole('button',{name,exact:true}).click();
    await review.getByRole('button',{name:'已记录投入 35 分钟'}).click();
    await expect(review.locator('.review-source')).toHaveCount(1);
    await review.getByRole('button',{name:'自己写几句',exact:true}).click();
    const record=page.getByRole('form',{name:'复盘记录编辑器'});
    await record.getByLabel('标题',{exact:true}).fill('匿名手写回顾');await record.getByLabel('我的结论',{exact:true}).fill('按自己的节奏来。');
    await record.getByRole('button',{name:'明确保存复盘记录',exact:true}).click();
    await expect(review.getByRole('heading',{name:'匿名手写回顾',exact:true})).toBeVisible();
    checked('review:day_week_month_real_source_drilldown_manual_save');
    await review.getByRole('tab',{name:'回顾',exact:true}).click();
    await review.getByRole('button',{name:'和 AI 复盘',exact:true}).click();
    await page.getByRole('button',{name:'填入聊天（不会自动发送）',exact:true}).click();
    await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.reply-status')).toContainText('回复已完成');
    await page.getByRole('button',{name:'整理为复盘记录',exact:true}).click();
    await page.getByRole('button',{name:'生成可编辑预览',exact:true}).click();
    await expect(editor.getByLabel('标题',{exact:true})).toHaveValue('匿名复盘记录');
    assert.equal((await call('/api/reviews/records')).items.length,1);
    await editor.getByLabel('我的结论',{exact:true}).fill('我审核后的结论。');
    await editor.getByRole('button',{name:'确认正式保存',exact:true}).click();
    await expect(editor.getByRole('heading',{name:/已保存/})).toBeVisible();
    assert.equal((await call('/api/reviews/records')).items.length,2);assert.equal((await call('/api/tasks')).length,3);
    await home();await send('匿名排程：基于回顾，另外提出下周安排建议。');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor.getByRole('heading',{name:/已保存/})).toBeVisible();
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    assert.ok((await call('/api/calendar/events?start=2026-10-19&end=2026-10-26')).events.some(e=>e.kind==='formal_task'));
    checked('C:facts_discussion_explicit_review_preview_confirm_then_separate_schedule');
    for(const width of [1440,1280]) {
      await page.setViewportSize({width,height:1000});
      for(const name of ['首页','日程','复盘','档案']) {
        await nav.getByRole('button',{name,exact:true}).click();
        const separator=page.getByRole('separator',{name:'调整主体与辅助栏宽度'});
        await separator.focus();await separator.press('ArrowLeft');
        const box=await separator.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+80);await page.mouse.down();await page.mouse.move(box.x+30,box.y+80);await page.mouse.up();
        await page.getByRole('button',{name:'展开辅助栏',exact:true}).click();
        await page.getByRole('button',{name:'恢复普通辅助栏',exact:true}).click();
        await page.getByRole('button',{name:'收起辅助栏',exact:true}).click();await page.getByRole('button',{name:'恢复辅助栏',exact:true}).click();
        await page.getByRole('button',{name:'恢复默认宽度',exact:true}).click();
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
        assert.equal(await page.locator('#v2-auxiliary-shared .day-column').count(),1);
      }
    }
    const auxiliary=page.getByRole('tablist',{name:'辅助栏页签'});
    await auxiliary.getByRole('tab',{name:'复盘',exact:true}).click();
    await expect(page.locator('.v2-shell')).toHaveAttribute('data-navigation','profile');
    await expect(page.getByRole('region',{name:'复盘辅助视图'})).toContainText('35 分钟');
    const auxText=await page.getByRole('region',{name:'复盘辅助视图'}).innerText();
    await nav.getByRole('button',{name:'复盘',exact:true}).click();await review.getByRole('button',{name:'月',exact:true}).click();
    assert.equal(await page.getByRole('region',{name:'复盘辅助视图'}).innerText(),auxText);
    await home();await expect(auxiliary.getByRole('tab',{name:'复盘',exact:true})).toHaveAttribute('aria-selected','true');
    checked('layout:1440_1280_four_pages_resize_keyboard_expand_collapse_reset_independent_tabs_ranges');
    // Invalid edits survive navigation, reload and an actual remote version conflict.
    await send('匿名拆解：另一个需要审核的120分钟任务。');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await editor.getByLabel('子任务 1 预计分钟',{exact:true}).fill('7');
    await home();await page.getByRole('textbox',{name:'会话输入',exact:true}).fill('匿名修改草案：请读取我的手改');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await expect(page.locator('.conversation-chat [role="alert"]')).toBeVisible();
    await nav.getByRole('button',{name:'日程',exact:true}).click();
    await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('7');
    const drafts=await call('/api/tasks/breakdown-drafts');const localDraft=drafts.find(d=>d.status==='ready');
    const current=await call(`/api/workspace/drafts/breakdown/${localDraft.id}`);
    assert.equal(current.content.children[0].duration_minutes,60);
    await page.reload();await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('60');
    await editor.getByRole('button',{name:'恢复到编辑器',exact:true}).click();
    await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('7');
    const changed=structuredClone(current.content);changed.children[0].duration_minutes=50;
    await call(`/api/workspace/drafts/breakdown/${current.id}`,'PATCH',{expected_version:current.version,content:changed});
    await editor.getByRole('button',{name:'保存草案编辑',exact:true}).click();
    await expect(editor.getByRole('alert')).toBeVisible();await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('7');
    await expect(editor.getByText('服务端最新内容（本地编辑仍保留）',{exact:true})).toBeVisible();
    await page.reload();await expect(editor.getByLabel('子任务 1 预计分钟',{exact:true})).toHaveValue('50');
    await expect(editor).toContainText('本地内容保留供对照');
    checked('draft:invalid_edit_blocks_AI_reload_restore_409_keeps_input_and_old_cache');
    await home();
    await page.getByRole('textbox',{name:'会话输入',exact:true}).fill('尚未发送的想法');
    await page.reload();await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toHaveValue('尚未发送的想法');
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'辅助栏',exact:true}).click();
    await auxiliary.getByRole('tab',{name:'日程',exact:true}).click();
    assert.equal(await page.locator('#v2-auxiliary-shared .day-column').count(),1);
    await expect(page.getByRole('separator')).toBeHidden();
    for(let i=0;i<25;i++){await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>Boolean(document.activeElement.closest('[hidden],[inert]'))),false)}
    for(const name of ['首页','日程','复盘','档案']) {
      await nav.getByRole('button',{name,exact:true}).click();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    const clocks=await page.locator('.workspace-clock').allTextContents();assert.ok(clocks.every(value=>value===clocks[0]));
    checked('mobile:390_single_surface_focus_no_overflow_refresh_input_restore_shared_clock');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'},null,2));
  }catch(error){if(page)console.error((await page.locator('body').innerText()).slice(-4500));throw error}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
