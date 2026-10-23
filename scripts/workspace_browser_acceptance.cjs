// Stage 2/3 acceptance on the explicit isolated integration_demo server only.
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
async function verifyQualityUI(){
  const settings=await call('/api/assistant/settings');assert.equal(settings.now,'2026-10-23T13:00:00+08:00');
  const task=await call('/api/tasks','POST',{title:'【示例】数据库实验报告',duration_minutes:60,deadline:'2026-10-23T22:00:00+08:00',priority:'normal'});
  let snapshot=await call('/api/growth/attention');assert.equal(snapshot.items[0].available_start_count,97);assert.equal(snapshot.items[0].free_minutes,540);
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'America/Los_Angeles'}),errors=[],checks=[];
  page.on('pageerror',error=>errors.push(error.message));const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try{
    await page.goto(web);const nav=page.getByRole('navigation',{name:'主导航'}),focus=page.locator('.today-focus');
    await nav.getByRole('button',{name:'日程',exact:true}).click();
    const attention=focus.locator(`[data-attention-task="${task.id}"]`);
    await expect(attention).toContainText('预计还需1小时');await expect(attention).toContainText('今天 22:00截止');
    await attention.getByText('可用时间与任务详情',{exact:true}).click();
    await expect(attention).toContainText('1段空闲，共9小时');await expect(attention).toContainText('97个合法连续起点');
    await expect(attention.getByRole('button',{name:/^生成 .* 草案$/})).toHaveCount(3);
    await expect(attention).not.toContainText('很紧急');checked('attention:one_9h_gap_97_starts_3_real_choices_correct_workload_and_urgency');
    // Drop a real response after the server persisted it, then retry the exact
    // idempotency identity via the visible UI. No formal write before confirm.
    let lostDraft;
    await page.route(`**/api/growth/tasks/${task.id}/schedule-draft`,async route=>{const response=await route.fetch();lostDraft=await response.json();await route.abort('failed')});
    await attention.getByRole('button',{name:/^生成 .* 草案$/}).first().click();
    await expect(focus.getByRole('alert')).toBeVisible();await page.unroute(`**/api/growth/tasks/${task.id}/schedule-draft`);
    await page.reload();await focus.getByRole('button',{name:'核实或重试上次生成',exact:true}).click();
    const editor=page.getByRole('region',{name:'共享草案编辑器'});
    await expect(editor).toHaveAttribute('data-status','ready');await expect(page.locator('.v2-shell')).toHaveAttribute('data-navigation','schedule');
    assert.equal((await call(`/api/workspace/drafts/planning/${lostDraft.id}`)).status,'ready');
    assert.equal((await call('/api/calendar/events?start=2026-10-23&end=2026-10-24')).events.filter(e=>e.kind==='formal_task').length,0);
    await editor.getByLabel('指定开始时间',{exact:true}).fill('2026-10-23T14:00');
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor).toHaveAttribute('data-status','applied');
    assert.ok((await call('/api/calendar/events?start=2026-10-23&end=2026-10-24')).events.some(e=>e.kind==='formal_task'&&Date.parse(e.start)===Date.parse('2026-10-23T14:00:00+08:00')));
    await page.reload();await expect(editor).toHaveAttribute('data-status','applied');
    checked('attention:lost_reply_reload_same_draft_edit_in_right_pane_then_original_validator_confirm');
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    // Make the main scenario empty again by completing it, using real feedback.
    await attention.getByRole('button',{name:task.title,exact:true}).click();
    const taskRow=page.locator(`[data-resource-task="${task.id}"]`);
    await taskRow.getByRole('button',{name:'可选：开始计时',exact:true}).click();
    await taskRow.getByRole('button',{name:'暂停',exact:true}).click();
    await taskRow.getByRole('button',{name:'继续',exact:true}).click();
    await taskRow.getByRole('button',{name:'结束计时并填写反馈',exact:true}).click();
    await taskRow.getByLabel('本次结果').selectOption('completed');
    await taskRow.getByLabel('实际投入（分钟，可留空）',{exact:true}).fill('');
    await taskRow.getByRole('button',{name:'保存记录',exact:true}).click();
    await expect.poll(async()=>(await call('/api/tasks')).find(t=>t.id===task.id).status).toBe('done');
    const facts=await call('/api/reviews/facts?start=2026-10-19&end=2026-10-26');
    assert.equal(facts.completed_count,1);assert.equal(facts.unknown_count,1);assert.equal(facts.known_minutes,0);
    checked('execution:timer_pause_resume_finish_and_unknown_feedback_not_double_counted');
    const other=await call('/api/tasks','POST',{title:'匿名多空档任务',duration_minutes:60,deadline:'2026-10-23T22:00:00+08:00',priority:'normal'});
    for(const [start,end] of [['14:00','15:00'],['17:00','18:00']])await call('/api/time-rules','POST',{title:'匿名固定占用',kind:'protected',recurrence:'once',date:'2026-10-23',start_time:start,end_time:end});
    snapshot=await call('/api/growth/attention');const multiple=snapshot.items.find(t=>t.task_id===other.id);
    assert.equal(multiple.free_interval_count,3);assert.equal(multiple.available_start_count,51);
    await nav.getByRole('button',{name:'首页',exact:true}).click();await nav.getByRole('button',{name:'日程',exact:true}).click();
    await focus.getByText('可用时间与任务详情',{exact:true}).click();await expect(focus).toContainText('3段空闲，共7小时');
    checked('attention:multiple_real_windows_explain_exact_51_starts');
    // Real errors must not turn into successful empty queries or endless loads.
    const fail=route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{code:'UNAVAILABLE'}})});
    await page.route('**/api/reviews/facts?*',fail);await nav.getByRole('button',{name:'复盘',exact:true}).click();
    const review=page.getByRole('region',{name:'回顾与复盘记录'});
    await expect(review.getByRole('alert')).toBeVisible();await expect(review.getByText('正在读取事实…',{exact:true})).toHaveCount(0);
    await page.unroute('**/api/reviews/facts?*');await review.getByRole('button',{name:'重试回顾事实',exact:true}).click();await expect(review.locator('.review-metrics')).toContainText('耗时未知');
    await page.route('**/api/reviews/records?*',fail);const recordTab=review.getByRole('tab',{name:'回顾',exact:true});await recordTab.focus();await recordTab.press('ArrowRight');
    await expect(review.getByRole('tab',{name:'复盘记录',exact:true})).toHaveAttribute('aria-selected','true');
    await expect(review.getByRole('button',{name:'重试复盘记录',exact:true})).toBeVisible();await expect(review.getByText('尚无符合条件的正式复盘记录。',{exact:true})).toHaveCount(0);
    await page.unroute('**/api/reviews/records?*');await review.getByRole('button',{name:'重试复盘记录',exact:true}).click();await expect(review.getByText('尚无符合条件的正式复盘记录。',{exact:true})).toBeVisible();
    await page.route('**/api/memories?*',fail);await nav.getByRole('button',{name:'档案',exact:true}).click();await page.getByRole('tab',{name:'记忆',exact:true}).click();
    const memory=page.getByRole('region',{name:'长期记忆管理'});await expect(memory.getByRole('button',{name:'重试记忆列表',exact:true})).toBeVisible();await expect(memory.getByText('暂无符合条件的记忆。',{exact:true})).toHaveCount(0);
    await page.unroute('**/api/memories?*');await memory.getByRole('button',{name:'重试记忆列表',exact:true}).click();await expect(memory.getByText('暂无符合条件的记忆。',{exact:true})).toBeVisible();
    checked('states:review_memory_failure_retry_empty_unknown_minutes_and_keyboard_tabs');
    await nav.getByRole('button',{name:'首页',exact:true}).click();await page.getByRole('button',{name:'＋ 新对话',exact:true}).click();
    const send=async text=>{await page.getByRole('textbox',{name:'会话输入',exact:true}).fill(text);const response=page.waitForResponse(r=>r.url().endsWith('/runs')&&r.request().method()==='POST');await page.getByRole('button',{name:'发送',exact:true}).click();const run=await(await response).json();await expect.poll(async()=>(await call(`/api/conversations/${run.session_id}/runs/${run.id}`)).status,{timeout:30000}).not.toBe('running');return call(`/api/conversations/${run.session_id}/runs/${run.id}`)};
    const broken=await send('质量验收：坏JSON，今天晚上写操作系统作业90分钟，帮我安排一下。');
    assert.equal(broken.status,'completed');const restored=broken.content.tools.find(r=>r.draft).draft;assert.ok(restored.id);
    await expect(page.locator('.workspace-message.assistant').last()).toContainText('尚未保存正式修改');
    await expect.poll(async()=>(await call(`/api/conversations/${broken.session_id}/runs/${broken.id}`)).content.diagnostics?.events?.length||0).toBeGreaterThan(0);const diagnosticRun=await call(`/api/conversations/${broken.session_id}/runs/${broken.id}`);const stages=diagnosticRun.content.diagnostics.events.map(e=>e.stage);assert.ok(stages.includes('provider.http'));assert.ok(stages.includes('tool_plan.json_failed'));assert.ok(stages.includes('planning_draft.persisted'));
    const altered=await send('改成晚上八点，分成两段，每段45分钟');assert.equal(altered.content.tools.find(r=>r.draft).draft.id,restored.id);
    const compound=await send('质量验收：复合任务，帮我拆解一份两小时交付，周日20点截止');assert.ok(compound.content.tools.some(r=>r.draft?.kind==='breakdown'));
    const reviewed=await send('质量验收：日期别名，帮我回顾本周并整理为复盘草案');assert.equal(reviewed.status,'completed');assert.equal(reviewed.content.tools.filter(r=>r.tool==='review').length,1);assert.ok(reviewed.content.tools.some(r=>r.draft?.kind==='review_record'));
    checked('wire:real_HTTP_adapter_invalid_JSON_defaults_same_ID_compound_task_date_alias_review_one_query_receipt');
    const child=compound.content.tools.find(r=>r.draft?.kind==='breakdown').draft;
    await page.locator(`[data-draft-kind="breakdown"][data-draft-id="${child.id}"]`).getByRole('button',{name:'查看最新草案',exact:true}).click();
    await editor.getByLabel('子任务 1 预计分钟',{exact:true}).fill('7');
    await editor.getByRole('button',{name:'保存草案编辑',exact:true}).click();await expect(editor.getByRole('alert')).toBeVisible();
    page.once('dialog',dialog=>dialog.accept());await editor.getByRole('button',{name:'放弃草案',exact:true}).click();
    await expect(editor).toHaveAttribute('data-status','discarded');await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    checked('draft:explicit_discard_invalid_local_edit_without_saving_or_formal_write');
    // Independent surfaces and all common panel operations at the required sizes.
    for(const width of [1440,1280,1024,390]){
      await page.setViewportSize({width,height:width===390?844:1000});
      for(const name of ['首页','日程','复盘','档案']){
        await nav.getByRole('button',{name,exact:true}).click();
        if(width>=1024){const divider=page.getByRole('separator');await divider.focus();await divider.press('End');const box=await divider.boundingBox();await page.mouse.move(box.x+3,box.y+60);await page.mouse.down();await page.mouse.move(box.x-20,box.y+60);await page.mouse.up();await page.getByRole('button',{name:'展开辅助栏',exact:true}).click();await page.getByRole('button',{name:'恢复普通辅助栏',exact:true}).click();await page.getByRole('button',{name:'收起辅助栏',exact:true}).click();await page.getByRole('button',{name:'恢复辅助栏',exact:true}).click();
          await expect.poll(()=>page.locator('#v2-auxiliary-shared').evaluate(el=>Math.abs(el.getBoundingClientRect().right-document.querySelector('.v2-grid').getBoundingClientRect().right))).toBeLessThan(2);}
        else await page.getByRole('button',{name:'辅助栏',exact:true}).click();
        await page.getByRole('tablist',{name:'辅助栏页签'}).getByRole('tab',{name:'日程',exact:true}).click();await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
    }
    checked('layout:1440_1280_1024_390_four_pages_independent_single_day_sidebar_resize_keyboard_modes_no_overflow');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,pageErrors:errors,provider:'Mock HTTP only',database:'new anonymous database'},null,2));
  }catch(error){console.error((await page.locator('body').innerText()).slice(-7000));throw error}finally{await browser.close()}
}
async function verifyLegacyRemovalUI(){
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'}),errors=[],writes=[],checks=[];
  const checked=text=>{checks.push(text);console.log('PASS '+text)};
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!['GET','HEAD','OPTIONS'].includes(request.method()))writes.push(request.method()+' '+new URL(request.url()).pathname)});
  try{
    for(const search of ['', '?layout=legacy']){
      const url=new URL(web);url.search=search;
      await page.goto(url.href);
      const nav=page.getByRole('navigation',{name:'主导航',exact:true});
      await expect(nav).toBeVisible();
      await expect(nav.getByRole('button')).toHaveText(['首页','日程','复盘','档案']);
      await expect(page.locator('.v2-shell')).toHaveCount(1);
      await expect(page.locator('a[href*="layout=legacy"],.app-shell:not(.v2-shell),.workbench-grid,.workbench-switch,.site-header')).toHaveCount(0);
      checked(search?'old_layout_bookmark_loads_only_current_workspace':'root_loads_only_current_workspace');
    }
    const nav=page.getByRole('navigation',{name:'主导航',exact:true});
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:width===390?844:1000});
      await page.reload();await expect(nav).toBeVisible();
      for(const name of ['首页','日程','复盘','档案']){
        await nav.getByRole('button',{name,exact:true}).click();
        await expect(page.getByRole('heading',{name,exact:true}).first()).toBeVisible();
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
      await expect(page.locator('.workbench-grid,.workbench-switch')).toHaveCount(0);
      checked('old_bookmark_refresh_four_current_pages_no_overflow:'+width);
    }
    await page.setViewportSize({width:1440,height:1000});
    await nav.getByRole('button',{name:'复盘',exact:true}).click();
    await page.getByText('统计与习惯建议',{exact:true}).click();
    await expect(page.getByRole('region',{name:'成长统计概览',exact:true})).toBeVisible();
    await expect(page.locator('.analytics-note').first()).toBeVisible();
    assert.deepEqual(writes,[],'Opening current pages and shared statistics must not write business data');
    checked('shared_analytics_and_existing_notes_remain_in_current_review_without_writes');
    await nav.getByRole('button',{name:'档案',exact:true}).click();
    await page.getByRole('button',{name:'用 AI 整理目标或偏好',exact:true}).click();
    await page.getByRole('textbox',{name:'修改目标或偏好',exact:true}).fill('匿名新增目标：旧版删除后的档案草案');
    await page.locator('.workspace-chat-input').getByRole('button',{name:'发送',exact:true}).click();
    await expect(page.locator('.workspace-draft')).toBeVisible({timeout:30000});
    await page.locator('.workspace-draft .button.primary').click();
    await expect(page.locator('.workspace-confirmed')).toBeVisible({timeout:30000});
    checked('shared_profile_chat_draft_and_explicit_save');
    await page.getByRole('button',{name:'本周规划入口',exact:true}).click();
    await page.getByRole('button',{name:'手动添加',exact:true}).click();
    const form=page.locator('.manual-task'),title='旧版删除后的手动规划';
    await form.getByLabel('名称',{exact:true}).fill(title);
    await form.getByLabel('剩余时长（分钟）',{exact:true}).fill('10');
    await form.getByLabel('截止时间',{exact:true}).fill('2026-10-14T22:00');
    await form.getByRole('button',{name:'生成候选',exact:true}).click();
    const adopt=page.getByRole('button',{name:'采用方案',exact:true});
    await expect(adopt).toBeEnabled({timeout:60000});
    assert.ok(!(await call('/api/tasks')).some(task=>task.title===title));
    await adopt.click();
    await expect(page.getByRole('heading',{name:'已采用方案',exact:true})).toBeVisible({timeout:30000});
    assert.ok((await call('/api/tasks')).some(task=>task.title===title));
    checked('shared_planning_manual_preview_and_explicit_adoption');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({checks,pageErrors:errors,provider:'Mock only',database:'new anonymous database'},null,2));
  }catch(error){console.error((await page.locator('body').innerText()).slice(-4000));throw error}
  finally{await browser.close()}
}
async function verifyReviewSidebarUI(){
  const beforeRecords=(await call('/api/reviews/records')).items.length;
  const conversation=await call('/api/conversations','POST',{client_request_id:'review-sidebar',title:'匿名复盘侧栏'});
  const draft=await call(`/api/conversations/${conversation.id}/review-drafts`,'POST',{client_request_id:'review-sidebar-draft',period:'week',start_date:'2026-10-19',end_date:'2026-10-26'});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'}),errors=[],checks=[];
  const checked=name=>{checks.push(name);console.log('PASS '+name)};
  page.on('pageerror',error=>errors.push(error.message));
  try{
    await page.goto(web);
    await page.locator(`.conversation-row[data-conversation-id="${conversation.id}"] .conversation-title`).click();
    const chat=page.getByRole('textbox',{name:'会话输入',exact:true});await chat.fill('侧栏操作后保留的聊天输入');
    await page.getByRole('button',{name:'审核复盘草案',exact:true}).click();
    const editor=page.getByRole('region',{name:'共享草案编辑器'}),nav=page.getByRole('navigation',{name:'主导航'}),tabs=page.getByRole('tablist',{name:'辅助栏页签'});
    await expect(editor.getByLabel('标题',{exact:true})).toHaveValue(draft.content.title);
    const title='【示例】本周学习复盘：在侧栏里核对完整内容，再明确确认保存';
    const summary='本周完成操作系统练习、数据库实验和需求整理。\n\n'+('记录投入与实际困难，下一次先列出边界条件，再预留完整时间处理。'.repeat(30));
    const conclusion='拆开小任务更容易开始。\n保留这些原始感受，下一周再检查。';
    const nextSteps='下周补完阅读，检查文档。参考标识：'+('长文本'.repeat(60));
    await editor.getByLabel('标题',{exact:true}).fill(title);
    await editor.getByLabel('回顾摘要',{exact:true}).fill(summary);
    await editor.getByLabel('我的结论',{exact:true}).fill(conclusion);
    await editor.getByLabel('下一步（可空）',{exact:true}).fill(nextSteps);
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:width===390?844:1000});
      if(width===390)await page.getByRole('button',{name:'辅助栏',exact:true}).click();
      else{const divider=page.getByRole('separator');await divider.focus();await divider.press('End')}
      await expect(editor).toBeVisible();
      const fields=await editor.locator('.draft-editor-fields>label').evaluateAll(labels=>labels.map(label=>label.getBoundingClientRect().toJSON()));
      assert.equal(fields.length,4);for(let i=1;i<fields.length;i++)assert.ok(fields[i].top-fields[i-1].bottom>=16);
      for(const textarea of await editor.locator('textarea').all()){
        assert.ok(await textarea.evaluate(el=>el.clientHeight>=120));
        if(await textarea.evaluate(()=>CSS.supports('field-sizing','content')))assert.ok(await textarea.evaluate(el=>el.scrollHeight<=el.clientHeight+2));
      }
      assert.ok(await editor.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    checked('review_editing_320px_auxiliary_and_390_mobile_has_field_spacing_full_text_no_horizontal_overflow');
    await editor.getByLabel('下一步（可空）',{exact:true}).focus();await page.keyboard.press('Tab');
    await expect(editor.getByRole('button',{name:'确认正式保存',exact:true})).toBeFocused();
    checked('review_primary_action_is_first_in_visual_and_keyboard_order');
    await page.setViewportSize({width:1440,height:1000});
    await nav.getByRole('button',{name:'日程',exact:true}).click();
    await tabs.getByRole('tab',{name:'日程',exact:true}).click();await expect(editor).toBeHidden();
    await tabs.getByRole('tab',{name:'复盘',exact:true}).click();
    await expect(editor.getByLabel('回顾摘要',{exact:true})).toHaveValue(summary);
    await nav.getByRole('button',{name:'首页',exact:true}).click();await expect(chat).toHaveValue('侧栏操作后保留的聊天输入');
    assert.equal((await call('/api/reviews/records')).items.length,beforeRecords);
    assert.deepEqual(await call('/api/tasks'),[]);
    checked('review_editing_keeps_primary_chat_auxiliary_tabs_and_requires_explicit_save');
    await editor.getByRole('button',{name:'确认正式保存',exact:true}).click();
    const reading=editor.getByRole('article',{name:'已保存的复盘内容'});
    await expect(reading).toBeVisible();await expect(reading.getByRole('heading',{name:title,exact:true})).toBeVisible();
    assert.equal(await reading.locator('section p').nth(0).textContent(),summary);
    assert.equal(await reading.locator('section p').nth(1).textContent(),conclusion);
    assert.equal(await reading.locator('section p').nth(2).textContent(),nextSteps);
    await expect(reading).toContainText('2026-10-25');
    await expect(editor.locator('input,textarea,.review-draft-actions')).toHaveCount(0);
    assert.equal((await call('/api/reviews/records')).items.length,beforeRecords+1);
    assert.deepEqual(await call('/api/tasks'),[]);
    checked('confirmed_review_becomes_full_readonly_text_without_disabled_forms_or_business_changes');
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:width===390?844:1000});
      if(width===390)await page.getByRole('button',{name:'辅助栏',exact:true}).click();
      else{await page.getByRole('button',{name:'展开辅助栏',exact:true}).click();await expect(reading).toBeVisible();await page.getByRole('button',{name:'恢复普通辅助栏',exact:true}).click()}
      assert.ok(await editor.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
    await page.reload();await expect(reading).toBeVisible();await expect(editor.locator('textarea')).toHaveCount(0);
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();await expect(editor).toBeHidden();
    assert.ok(await page.evaluate(()=>!document.activeElement?.closest('[hidden],[inert]')));
    checked('saved_review_survives_resize_expand_mobile_refresh_and_close_without_hidden_focus');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,pageErrors:errors,provider:'Mock only',database:'new anonymous database'},null,2));
  }catch(error){console.error((await page.locator('body').innerText()).slice(-4000));throw error}
  finally{await browser.close()}
}
async function verifyIndependentScheduleUI(){
  assert.deepEqual((await call('/api/conversations?scope=all')).items,[]);
  const settings=await call('/api/assistant/settings');
  const task=await call('/api/tasks','POST',{title:'独立日程正式作业',duration_minutes:90,deadline:'2026-10-14T22:00:00+08:00',priority:'normal'});
  await call('/api/time-rules','POST',{title:'独立日程正式课程',kind:'course',recurrence:'weekly',weekday:3,start_time:'15:00',end_time:'16:00'});
  const candidate=await call('/api/plans/candidates','POST',{week_start:settings.week_start,task_ids:[task.id]});
  await call(`/api/plans/${candidate.candidate.id}/confirm`,'POST');
  await call('/api/goals','POST',{title:'独立日程月末目标',metric_kind:'count',weekly_target:1,due_date:'2026-10-30'});
  const planning=await call('/api/assistant/sessions','POST',{});
  let deleted=await call(`/api/conversations/${planning.id}`);
  await call(`/api/conversations/${planning.id}?expected_version=${deleted.version}`,'DELETE');
  const conversation=await call('/api/conversations','POST',{client_request_id:'deleted-chat-fixture'});
  await call(`/api/conversations/${conversation.id}?expected_version=${conversation.version}`,'DELETE');
  const before=await call('/api/calendar/events?start=2026-10-12&end=2026-10-19');
  const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});
  const errors=[],checks=[],sessionRequests=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',request=>{
    const path=new URL(request.url()).pathname;
    if(path.startsWith('/api/assistant/sessions'))sessionRequests.push({path,method:request.method()});
    if(request.url().startsWith(api)&&['POST','PUT','PATCH','DELETE'].includes(request.method()))writes.push(path);
  });
  const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try{
    await page.addInitScript(({workspace,week,planning,conversation})=>{
      if(sessionStorage.getItem('independent-schedule-fixture'))return;
      sessionStorage.setItem('independent-schedule-fixture','1');
      localStorage.setItem(`sga-assistant-session:${workspace}:${week}`,String(planning));
      const save=(key,value)=>sessionStorage.setItem(`sga-edit-v1:${JSON.stringify([workspace,key])}`,JSON.stringify({schema:1,base:key==='layout'?'layout-v1':null,value}));
      save('selection',conversation);save('layout',{navigation:'schedule',auxiliaryPage:'schedule',panel:'normal',conversations:true,mobile:'primary'});
    },{workspace:settings.workspace_id,week:settings.week_start,planning:planning.id,conversation:conversation.id});
    await page.goto(web);
    const nav=page.getByRole('navigation',{name:'主导航'}),primary=page.locator('#v2-page-schedule'),calendar=primary.getByRole('region',{name:'完整日历'});
    await expect(calendar).toBeVisible();await expect(calendar.locator('.calendar-formal_task').first()).toBeVisible();
    await expect(calendar.locator('.calendar-course').first()).toBeVisible();
    await expect(primary).not.toContainText('会话已删除');assert.equal(sessionRequests.length,0);
    await primary.locator('.task-memory').getByText('任务与执行',{exact:true}).click();
    await expect(primary.locator(`[data-resource-task="${task.id}"]`)).toContainText('独立日程正式作业');
    checked('deleted_cached_planning_and_chat_do_not_gate_formal_calendar_courses_tasks_or_create_sessions');
    await nav.getByRole('button',{name:'首页',exact:true}).click();await expect(page.locator('.conversation-chat [role="alert"]')).toContainText('会话已删除');
    await nav.getByRole('button',{name:'日程',exact:true}).click();await expect(calendar).toBeVisible();
    await nav.getByRole('button',{name:'首页',exact:true}).click();await page.getByRole('button',{name:'本周规划入口',exact:true}).click();
    await expect(page.locator('#v2-chat')).toContainText('会话已删除');
    await nav.getByRole('button',{name:'日程',exact:true}).click();await expect(calendar.locator('.calendar-formal_task').first()).toBeVisible();
    assert.equal(sessionRequests.filter(r=>r.method==='POST').length,0);
    checked('unavailable_regular_or_legacy_chat_errors_stay_in_chat_and_never_replace_primary_schedule');
    const auxiliaryDate=page.getByLabel('辅助日程日期',{exact:true});
    await expect(auxiliaryDate).toHaveValue('2026-10-14');
    await calendar.getByRole('button',{name:'天',exact:true}).click();await calendar.getByLabel('日历日期',{exact:true}).fill('2026-10-15');
    await expect(auxiliaryDate).toHaveValue('2026-10-14');await auxiliaryDate.fill('2026-10-16');
    await expect(calendar.getByLabel('日历日期',{exact:true})).toHaveValue('2026-10-15');
    await calendar.getByRole('button',{name:'月',exact:true}).click();await expect(calendar.locator('.calendar-goal').first()).toBeVisible();
    await calendar.getByRole('button',{name:'年',exact:true}).click();await expect(calendar.locator('.fc-multimonth-month')).toHaveCount(12);
    await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
    checked('all_four_calendar_views_read_all_workspace_sources_independent_of_auxiliary_date_and_chat');
    await page.reload();await expect(calendar).toBeVisible();await expect(calendar.getByRole('button',{name:'年',exact:true})).toHaveAttribute('aria-pressed','true');
    await expect(auxiliaryDate).toHaveValue('2026-10-16');
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:900});await nav.getByRole('button',{name:'日程',exact:true}).click();
      await expect(calendar).toBeVisible();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if(width<700){await page.getByRole('button',{name:'辅助栏',exact:true}).click();await expect(page.getByRole('region',{name:'单日日程预览'})).toBeVisible()}
    }
    const after=await call('/api/calendar/events?start=2026-10-12&end=2026-10-19');
    assert.deepEqual(after,before);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    checked('reload_and_1440_1280_390_browsing_preserve_ui_without_writes_or_replacement_sessions');
    console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'}));
  }finally{await browser.close()}
}
async function verifySkillsUI() {
  assert.deepEqual((await call('/api/conversations?scope=all')).items,[], 'Use a new anonymous database');
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'}),errors=[],checks=[];
  page.on('pageerror',error=>errors.push(error.message));
  const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try {
    await page.goto(web);
    await page.getByRole('button',{name:'开始新对话',exact:true}).click();
    const input=page.getByRole('textbox',{name:'会话输入',exact:true});await expect(input).toBeEnabled();
    const sid=(await call('/api/conversations')).items[0].id;
    async function send(text){
      await expect(input).toBeEnabled();await input.fill(text);
      await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled();
      const pending=page.waitForResponse(r=>r.url().endsWith(`/api/conversations/${sid}/runs`)&&r.request().method()==='POST');
      await page.getByRole('button',{name:'发送',exact:true}).click();
      const initial=await (await pending).json();
      await expect.poll(async()=>(await call(`/api/conversations/${sid}/runs/${initial.id}`)).status).not.toBe('running');
      await expect(page.locator('.reply-status')).not.toContainText('正在');
      return call(`/api/conversations/${sid}/runs/${initial.id}`);
    }
    await send('技能验收：今晚写匿名作业');
    await expect(page.locator('.conversation-chat')).toContainText('预计需要多少分钟');
    await send('一个半小时');const partial=await send('帮我安排一下');
    assert.equal(partial.content.tools.find(r=>r.draft)?.draft.content.schedule.deadline,null);
    assert.deepEqual(await call('/api/tasks'),[]);
    const planned=await send('今晚22点前完成');const draft=planned.content.tools.find(r=>r.draft)?.draft;
    assert.ok(draft?.id>0);assert.equal(draft.kind,'planning');assert.equal(draft.status,'ready');
    await expect(page.getByRole('button',{name:'查看最新草案',exact:true})).toHaveCount(2);
    assert.deepEqual(await call('/api/tasks'),[]);
    checked('skills_multi_turn_title_duration_date_real_draft_no_early_formal_write');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    const editor=page.getByRole('region',{name:'共享草案编辑器'});
    await expect(editor).toBeVisible();await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor.getByRole('status')).toContainText('已正式保存');
    assert.equal((await call('/api/tasks')).length,1);
    assert.ok((await call('/api/calendar/events?start=2026-10-14&end=2026-10-15')).events.some(e=>e.kind==='formal_task'));
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    const nav=page.getByRole('navigation',{name:'主导航'});await nav.getByRole('button',{name:'首页',exact:true}).click();
    checked('skills_original_confirm_receipt_and_formal_calendar');
    await send('技能验收：今天有什么安排');
    const article=page.locator('.workspace-message.assistant').last();
    await expect(article.locator('.helper')).toHaveCount(1);await expect(article.locator('.helper')).toContainText('已查询：任务、日程');
    assert.equal(await page.getByText('已读取正式记录，供本次回答参考。',{exact:true}).count(),0);
    checked('skills_query_receipts_are_aggregated_once');
    const review=await send('技能验收：帮我复盘一下今天');
    const ref=review.content.tools.find(r=>r.draft)?.draft;assert.equal(ref?.kind,'review_record');
    assert.equal((await call('/api/reviews/records')).items.length,0);
    const latestArticle=page.locator(`#conversation-message-${sid}-${review.assistant_message_id}`);
    await expect(latestArticle.getByRole('button',{name:'查看最新草案',exact:true})).toHaveCount(1);
    checked('skills_explicit_natural_language_review_is_one_real_editable_preview');
    const denied=await send('技能验收：先不要帮我安排');
    assert.equal(denied.content.tools[0].error,'TOOL_NOT_ALLOWED');
    const missing=await send('技能验收：帮我安排但没有模型工具');
    assert.equal(missing.content.business_status,'awaiting_confirmation');assert.ok(missing.content.tools.find(r=>r.draft)?.draft.id>0);
    await expect(page.locator(`#conversation-message-${sid}-${missing.assistant_message_id}`)).toContainText('默认值');
    assert.equal((await call('/api/tasks')).length,1);
    checked('skills_negative_model_plan_blocked_and_empty_plan_uses_real_default_draft');
    await send('[无Key]匿名旧失败');await send('技能验收：今天有什么安排');
    await expect(page.getByText('回复未正常结束，内容可能不完整',{exact:true})).toHaveCount(0);
    checked('skills_old_empty_failure_does_not_label_new_complete_reply');
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:900});
      if(width<700)await page.getByRole('button',{name:'辅助栏',exact:true}).click();
      const auxiliary=page.getByRole('tablist',{name:'辅助栏页签'});
      await auxiliary.getByRole('tab',{name:'日程',exact:true}).click();
      await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if(width<700){await expect(page.getByRole('separator')).toHaveCount(0);await page.getByRole('button',{name:'聊天',exact:true}).click()}
    }
    checked('skills_1440_1280_390_independent_single_day_preview_no_overflow');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'}));
  }finally{await browser.close()}
}
async function verifyDefaultDraftUI(){
  assert.deepEqual((await call('/api/conversations?scope=all')).items,[]);
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'}),errors=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try{
    await page.goto(web);await page.getByRole('button',{name:'开始新对话',exact:true}).click();
    await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    const sid=(await call('/api/conversations')).items[0].id;
    const input=page.getByRole('textbox',{name:'会话输入',exact:true});
    const nav=page.getByRole('navigation',{name:'主导航'});
    const blockedRequests=[];
    const observe=request=>{if(request.method()==='POST'&&request.url().endsWith(`/api/conversations/${sid}/runs`))blockedRequests.push(request)};
    page.on('request',observe);
    await page.route(api+'/api/health',route=>route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':web},body:JSON.stringify({status:'ok'})}));
    await input.fill('旧后端检查：输入必须保留');await page.getByRole('button',{name:'发送',exact:true}).click();
    await expect(page.getByRole('alert')).toContainText('请重启后端');await expect(input).toHaveValue('旧后端检查：输入必须保留');
    assert.equal(blockedRequests.length,0);await page.unroute(api+'/api/health');page.off('request',observe);
    checked('runtime_mismatch_blocks_paid_send_and_keeps_input');
    async function send(text){
      await expect(input).toBeEnabled();await input.fill(text);
      const pending=page.waitForResponse(r=>r.url().endsWith(`/api/conversations/${sid}/runs`)&&r.request().method()==='POST');
      await page.getByRole('button',{name:'发送',exact:true}).click();const initial=await(await pending).json();
      await expect.poll(async()=>(await call(`/api/conversations/${sid}/runs/${initial.id}`)).status).not.toBe('running');
      await expect(page.locator('.reply-status')).not.toContainText('正在');
      return call(`/api/conversations/${sid}/runs/${initial.id}`);
    }
    const ref=result=>result.content.tools.find(r=>r.draft)?.draft;
    await send('我今天晚上要完成操作系统作业。');
    const initial=await send('大概一个半小时，你帮我安排一下。'),draft=ref(initial);
    assert.equal(initial.status,'completed');assert.equal(draft.content.schedule.title,'操作系统作业');
    assert.equal(draft.content.schedule.duration_minutes,90);assert.equal(draft.content.schedule.deadline,null);
    assert.equal(draft.field_sources.start_time,'system_default');assert.ok(draft.items.length);
    await expect(page.getByRole('button',{name:'查看正式日程与任务',exact:true})).toHaveCount(0);
    await expect(page.getByRole('button',{name:'日程与任务',exact:true})).toHaveCount(1);
    assert.deepEqual(await call('/api/tasks'),[]);
    await expect(page.locator('.workspace-message.assistant').last()).toContainText('硬截止时间：未设置');
    checked('defaults_OS_homework_invalid_ToolPlan_repair_to_real_persisted_preview_without_DDL');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    const editor=page.getByRole('region',{name:'共享草案编辑器'});
    await expect(editor.getByRole('button',{name:'确认采用方案',exact:true})).toBeDisabled();
    await expect(editor.getByLabel('预计分钟',{exact:true})).toHaveValue('90');
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();await nav.getByRole('button',{name:'首页',exact:true}).click();
    const changed=ref(await send('改成晚上八点，两个小时'));
    assert.equal(changed.id,draft.id);assert.equal(changed.content.schedule.start_time,'20:00');assert.equal(changed.content.schedule.duration_minutes,120);
    const split=ref(await send('分成两段，每段45分钟，中间休息十分钟'));
    assert.equal(split.id,draft.id);assert.equal(split.items.length,2);
    assert.equal(new Date(split.items[1].start_at)-new Date(split.items[0].end_at),600000);
    checked('defaults_chat_updates_same_ID_and_exact_work_rest_segments');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await editor.getByLabel('名称',{exact:true}).fill('操作系统作业（手动确认）');
    await nav.getByRole('button',{name:'首页',exact:true}).click();
    const final=ref(await send('截止今晚22点'));
    assert.equal(final.id,draft.id);assert.equal(final.content.schedule.title,'操作系统作业（手动确认）');
    assert.equal(final.content.schedule.start_time,'20:00');assert.equal(final.status,'ready');
    assert.deepEqual(await call('/api/tasks'),[]);
    checked('defaults_send_coordinates_valid_manual_edits_before_chat_and_keeps_time');
    await page.reload();await expect(page.getByRole('button',{name:'查看最新草案',exact:true}).last()).toBeVisible();
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await expect(editor.getByLabel('名称',{exact:true})).toHaveValue('操作系统作业（手动确认）');
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor.getByRole('status')).toContainText('已正式保存');
    assert.equal((await call('/api/tasks')).length,1);
    assert.ok((await call('/api/calendar/events?start=2026-10-14&end=2026-10-15')).events.some(e=>e.kind==='formal_task'));
    checked('defaults_reload_latest_preview_then_original_confirm_real_receipt_calendar');
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();await nav.getByRole('button',{name:'首页',exact:true}).click();
    const review=ref(await send('帮我复盘一下'));
    assert.equal(review.content.title,'本周学习复盘');assert.equal(review.content.conclusion,'');
    assert.deepEqual((await call('/api/reviews/records')).items,[]);
    checked('defaults_review_blank_week_with_real_sources_no_formal_write');
    const denied=await send('先别安排，我只是问问。');assert.deepEqual(denied.content.tools,[]);
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:900});
      if(width<700)await page.getByRole('button',{name:'辅助栏',exact:true}).click();
      await page.getByRole('tablist',{name:'辅助栏页签'}).getByRole('tab',{name:'日程',exact:true}).click();
      await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if(width<700)await page.getByRole('button',{name:'聊天',exact:true}).click();
    }
    checked('defaults_negative_requests_and_1440_1280_390_independent_single_day_preview');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'}));
  }catch(e){console.error((await page.locator('body').innerText()).slice(-4000));throw e}finally{await browser.close()}
}

async function verifyDraftSidebarUI(){
  assert.deepEqual((await call('/api/conversations?scope=all')).items,[]);
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'}),errors=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try{
    await page.goto(web);await page.getByRole('button',{name:'开始新对话',exact:true}).click();
    const input=page.getByRole('textbox',{name:'会话输入',exact:true});await expect(input).toBeEnabled();
    let sid=(await call('/api/conversations')).items[0].id;
    async function send(text){
      await input.fill(text);
      const pending=page.waitForResponse(r=>r.url().endsWith(`/api/conversations/${sid}/runs`)&&r.request().method()==='POST');
      await page.getByRole('button',{name:'发送',exact:true}).click();const run=await(await pending).json();
      await expect.poll(async()=>(await call(`/api/conversations/${sid}/runs/${run.id}`)).status).not.toBe('running');
      await expect(page.locator('.reply-status')).not.toContainText('正在');
      return (await call(`/api/conversations/${sid}/runs/${run.id}`)).content.tools.find(t=>t.draft)?.draft;
    }
    const initial=await send('今晚帮我安排操作系统作业，90分钟');
    assert.equal(initial.status,'needs_input');assert.equal(initial.content.schedule.deadline,null);
    const nav=page.getByRole('navigation',{name:'主导航'}),tabs=page.getByRole('tablist',{name:'辅助栏页签'});
    await input.fill('保留在聊天中的输入');
    await page.getByRole('button',{name:'收起辅助栏',exact:true}).click();
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    const editor=page.locator('#v2-auxiliary-shared').getByRole('region',{name:'共享草案编辑器'});
    await expect(editor).toBeVisible();await expect(nav.getByRole('button',{name:'首页',exact:true})).toHaveAttribute('aria-current','page');
    await expect(input).toHaveValue('保留在聊天中的输入');await expect(page.locator('#v2-draft-preview')).toBeFocused();
    checked('draft_opens_collapsed_auxiliary_without_changing_home_or_chat_input');
    await editor.getByLabel('名称',{exact:true}).fill('操作系统作业（保留编辑）');
    for(const name of ['日程','复盘','档案','首页']){
      await nav.getByRole('button',{name,exact:true}).click();await expect(editor).toBeVisible();
      await expect(editor.getByLabel('名称',{exact:true})).toHaveValue('操作系统作业（保留编辑）');
    }
    await tabs.getByRole('tab',{name:'复盘',exact:true}).click();await expect(editor).toBeHidden();
    assert.ok(await page.evaluate(()=>!document.activeElement?.closest('[hidden],[inert]')));
    await tabs.getByRole('tab',{name:'日程',exact:true}).click();await expect(editor).toBeVisible();
    await expect(editor.getByLabel('名称',{exact:true})).toHaveValue('操作系统作业（保留编辑）');
    checked('draft_edits_survive_four_primary_pages_and_independent_auxiliary_tabs');
    for(const width of [1440,1280,390]){
      await page.setViewportSize({width,height:900});
      if(width<700)await page.getByRole('button',{name:'辅助栏',exact:true}).click();
      await expect(editor).toBeVisible();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if(width>=700){
        const divider=page.getByRole('separator');await divider.focus();await divider.press('ArrowLeft');
        await page.getByRole('button',{name:'展开辅助栏',exact:true}).click();await expect(editor).toBeVisible();
        await page.getByRole('button',{name:'恢复普通辅助栏',exact:true}).click();
      }else{await expect(page.getByRole('separator')).toHaveCount(0);await expect(input).toBeHidden()}
    }
    checked('draft_sidebar_1440_1280_390_resize_expand_single_surface_no_overflow');
    await page.getByRole('button',{name:'收起辅助栏',exact:true}).click();await expect(editor).toBeHidden();
    assert.ok(await page.evaluate(()=>!document.activeElement?.closest('[hidden],[inert]')));
    await page.getByRole('button',{name:'辅助栏',exact:true}).click();await expect(editor).toBeVisible();
    await editor.getByRole('button',{name:'保存草案编辑',exact:true}).click();
    await expect(editor.getByRole('button',{name:'保存草案编辑',exact:true})).toBeDisabled();
    await page.reload();await expect(editor).toBeVisible();
    await expect(editor.getByLabel('名称',{exact:true})).toHaveValue('操作系统作业（保留编辑）');
    await expect(editor.getByRole('button',{name:'确认采用方案',exact:true})).toBeDisabled();
    checked('draft_sidebar_collapse_focus_and_refresh_keep_same_preview');
    await editor.getByRole('button',{name:'以安排结束时间作为截止',exact:true}).click();
    const expectedEnd=initial.items.filter(i=>i.ref===initial.schedule_target).reduce((last,i)=>new Date(i.end_at)>new Date(last)?i.end_at:last,initial.items.find(i=>i.ref===initial.schedule_target).end_at);
    await expect(editor.getByLabel('截止时间',{exact:true})).toHaveValue(expectedEnd.slice(0,16));
    assert.deepEqual(await call('/api/tasks'),[]);
    await expect(editor.getByRole('button',{name:'确认采用方案',exact:true})).toBeEnabled();
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();await expect(editor.getByRole('status')).toContainText('已正式保存');
    let tasks=await call('/api/tasks');assert.equal(tasks.length,1);assert.equal(Date.parse(tasks[0].deadline),Date.parse(expectedEnd));
    assert.ok((await call('/api/calendar/events?start=2026-10-14&end=2026-10-15')).events.some(e=>e.kind==='formal_task'));
    checked('explicit_preview_end_then_one_confirm_persists_real_task_calendar_and_receipt');
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    await expect(page.getByLabel('辅助日程日期',{exact:true})).toBeVisible();
    await page.setViewportSize({width:1440,height:1000});await nav.getByRole('button',{name:'首页',exact:true}).click();
    await page.getByRole('button',{name:'＋ 新对话',exact:true}).click();await expect(input).toBeEnabled();
    sid=(await call('/api/conversations')).items[0].id;
    await send('明天晚上帮我安排编译原理作业，60分钟');
    await page.getByRole('button',{name:'查看最新草案',exact:true}).last().click();
    await expect(editor.getByRole('button',{name:'确认采用方案',exact:true})).toBeDisabled();
    await editor.getByLabel('截止时间',{exact:true}).fill('2026-10-15T22:00');
    // No separate save: the former needs_input button must submit current edits.
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();await expect(editor.getByRole('status')).toContainText('已正式保存');
    assert.equal((await call('/api/tasks')).length,2);
    await expect(nav.getByRole('button',{name:'首页',exact:true})).toHaveAttribute('aria-current','page');
    checked('manual_deadline_edit_confirms_directly_without_separate_save_or_primary_navigation');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'}));
  }finally{await browser.close()}
}
async function verifyConversationUI() {
  assert.deepEqual((await call('/api/conversations?scope=all')).items,[], 'Use a new anonymous database');
  const create=(title,key)=>call('/api/conversations','POST',{title,client_request_id:key});
  for(let i=0;i<64;i++)await create(`匿名会话 ${i+1}`,'ui-seed-'+i);
  const archived=await create('已归档的匿名会话','ui-archived');
  await call(`/api/conversations/${archived.id}`,'PATCH',{expected_version:archived.version,archived:true});
  const other=await create('另一条匿名会话','ui-other');
  const main=await create('首页精修示例：'+ '这是一条需要单行省略且可悬停查看的长会话标题'.repeat(3),'ui-main');
  const first=await call(`/api/conversations/${main.id}/messages`,'POST',{client_message_id:'hit-1',text:'正文定位关键字：蓝桥计划，还没有决定下一步。'});
  const second=await call(`/api/conversations/${main.id}/messages`,'POST',{client_message_id:'hit-2',text:'第二处蓝桥计划，需要继续讨论。'});
  const legacy=await call('/api/assistant/sessions','POST',{});
  const legacyMeta=await call(`/api/conversations/${legacy.id}`);
  await call(`/api/conversations/${legacy.id}`,'PATCH',{expected_version:legacyMeta.version,title:'匿名历史规划'});
  const browser=await chromium.launch({channel:'msedge',headless:true});let page;
  const errors=[],checks=[],requests=[];const checked=name=>{checks.push(name);console.log('PASS '+name)};
  try {
    page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});
    page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.url().startsWith(api))requests.push({url:request.url(),method:request.method(),body:request.postDataJSON()})});
    await page.goto(web);
    const nav=page.getByRole('navigation',{name:'主导航'}), list=page.locator('.conversation-groups');
    const row=id=>page.locator(`.conversation-row[data-conversation-id="${id}"]`);
    const menu=page.getByRole('menu',{name:'会话操作菜单'});
    const input=page.getByRole('textbox',{name:'会话输入',exact:true});
    async function openMenu(id,keyboard=false) {
      const trigger=row(id).getByRole('button',{name:/更多操作/});
      await expect(trigger).toBeEnabled();await trigger.scrollIntoViewIfNeeded();
      if(keyboard){await trigger.focus();await trigger.press('ArrowDown')}
      else {await row(id).hover();await trigger.click()}
      await expect(menu).toBeVisible();return trigger;
    }
    async function choose(id,label) {await openMenu(id);await menu.getByRole('menuitem',{name:label,exact:true}).click();await expect(menu).toHaveCount(0)}
    await row(main.id).locator('.conversation-title').click();await expect(input).toBeEnabled();
    await input.fill('切换与操作后仍应保留的未发送文字');
    await expect(page.locator('.workspace-chat-heading .conversation-summary-button')).toHaveCount(1);
    const intro=page.locator('.conversation-intro');
    assert.ok(parseFloat(await intro.evaluate(el=>getComputedStyle(el).marginTop))>=10);
    assert.ok(parseFloat(await intro.evaluate(el=>getComputedStyle(el).lineHeight))>=20);
    assert.equal(await row(main.id).locator('.conversation-title').getAttribute('title'),main.title);
    const titleBox=await row(main.id).locator('.conversation-title').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth,whiteSpace:getComputedStyle(el).whiteSpace,overflow:getComputedStyle(el).textOverflow}));
    assert.ok(titleBox.scroll>titleBox.client);assert.equal(titleBox.whiteSpace,'nowrap');assert.equal(titleBox.overflow,'ellipsis');
    for(const item of await page.locator('.conversation-row').all()) {
      assert.equal(await item.locator('button').count(),2);assert.equal(await item.locator('small,time,summary').count(),0);
      assert.ok((await item.boundingBox()).height<=38);
    }
    const visible=await list.evaluate(el=>{const box=el.getBoundingClientRect();return [...el.querySelectorAll('.conversation-row')].filter(row=>{const r=row.getBoundingClientRect();return r.top>=box.top&&r.bottom<=box.bottom}).length});
    assert.ok(visible>=12,`Only ${visible} fully visible rows`);
    checked(`single_line_title_tooltip_no_labels_${visible}_visible_rows_at_1440`);
    await page.waitForLoadState('networkidle');
    // Initial legacy planning startup can insert a row while page one loads.
    // Refresh before testing the existing offset pagination on a stable list.
    const refreshed=page.waitForResponse(r=>r.url().startsWith(api+'/api/conversations?')&&r.request().method()==='GET');
    await page.getByRole('button',{name:'刷新列表',exact:true}).click();await refreshed;
    await expect(list.getByText('正在读取会话列表…',{exact:true})).toBeHidden();
    await expect(row(other.id).getByRole('button',{name:/更多操作/})).toBeEnabled();
    const beforeHeight=await list.evaluate(el=>el.scrollHeight),beforeRow=(await row(other.id).boundingBox()).height,requestCount=requests.length;
    const trigger=await openMenu(other.id,true);
    assert.equal(await list.evaluate(el=>el.scrollHeight),beforeHeight);assert.equal((await row(other.id).boundingBox()).height,beforeRow);
    assert.equal(await row(main.id).locator('.conversation-title').getAttribute('aria-current'),'true');
    await expect(menu.getByRole('menuitem',{name:'重命名',exact:true})).toBeFocused();
    await page.keyboard.press('End');await expect(menu.getByRole('menuitem',{name:'删除会话',exact:true})).toBeFocused();
    await page.keyboard.press('Home');await page.keyboard.press('ArrowDown');await expect(menu.getByRole('menuitem',{name:'置顶',exact:true})).toBeFocused();
    await page.keyboard.press('Escape');await expect(trigger).toBeFocused();await expect(menu).toHaveCount(0);
    await trigger.press('Space');await expect(menu).toBeVisible();await page.keyboard.press('Tab');await expect(menu).toHaveCount(0);
    assert.equal(await page.evaluate(()=>Boolean(document.activeElement.closest('[hidden],[inert],.conversation-menu'))),false);
    await openMenu(other.id);await page.locator('.workspace-chat-heading h2').click();await expect(menu).toHaveCount(0);
    assert.equal(requests.length,requestCount,'Opening and closing menus must not request data');
    checked('menu_pointer_keyboard_space_arrows_escape_tab_outside_focus_no_reflow_or_requests');
    const total=(await call('/api/conversations?scope=all&archive=active&limit=100')).items.length;
    for(let n=0;n<2;n++){await page.getByRole('button',{name:'加载更多会话',exact:true}).click();await expect(page.locator('.conversation-row')).toHaveCount(Math.min((n+2)*30,total))}
    const bottom=page.locator('.conversation-row').last();const bottomId=Number(await bottom.getAttribute('data-conversation-id'));
    const bottomTrigger=await openMenu(bottomId);const menuBox=await menu.boundingBox(),anchor=await bottomTrigger.boundingBox();
    assert.ok(menuBox.y<anchor.y);assert.ok(menuBox.y>=0&&menuBox.y+menuBox.height<=1000&&menuBox.x>=0&&menuBox.x+menuBox.width<=1440);
    await list.evaluate(el=>{el.scrollTop-=90});await expect(menu).toHaveCount(0);
    await openMenu(main.id);await page.setViewportSize({width:1280,height:1000});await expect(menu).toHaveCount(0);
    checked('long_list_pagination_bottom_menu_flips_no_clipping_scroll_resize_close');
    await choose(other.id,'重命名');await expect(page.getByRole('textbox',{name:'会话标题',exact:true})).toBeFocused();
    await page.getByRole('textbox',{name:'会话标题',exact:true}).fill('已改名的匿名会话');
    await page.getByRole('button',{name:'保存标题',exact:true}).click();await expect(row(other.id).locator('.conversation-title')).toHaveText('已改名的匿名会话');
    await choose(other.id,'置顶');await expect(page.getByRole('region',{name:'置顶',exact:true}).locator(`[data-conversation-id="${other.id}"]`)).toBeVisible();
    await choose(other.id,'取消置顶');await expect(row(other.id)).toBeVisible();
    await choose(other.id,'归档会话');await expect(row(other.id)).toHaveCount(0);
    await page.getByRole('button',{name:'归档',exact:true}).click();await choose(other.id,'恢复会话');await expect(row(other.id)).toHaveCount(0);
    await page.getByRole('button',{name:'最近',exact:true}).click();await choose(other.id,'删除会话');
    await expect(page.getByRole('region',{name:'删除会话确认'})).toContainText('软删除');
    await page.getByRole('button',{name:'取消删除',exact:true}).click();await expect(row(other.id).getByRole('button',{name:/更多操作/})).toBeFocused();
    await choose(other.id,'删除会话');await page.getByRole('button',{name:'确认删除会话',exact:true}).click();await expect(row(other.id)).toHaveCount(0);
    assert.equal((await fetch(api+`/api/conversations/${other.id}`)).status,410);assert.deepEqual(await call('/api/tasks'),[]);
    await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
    const mutations=requests.filter(r=>r.method==='PATCH'&&new URL(r.url).pathname===`/api/conversations/${other.id}`);
    assert.equal(mutations.length,5);assert.ok(mutations.every(r=>r.body.expected_version));
    checked('real_rename_pin_unpin_archive_restore_soft_delete_original_versions_no_duplicate_mutation');
    await page.getByRole('searchbox',{name:'搜索会话',exact:true}).fill('蓝桥计划');await page.getByRole('search',{name:'搜索会话',exact:true}).getByRole('button',{name:'搜索',exact:true}).click();
    await expect(page.locator('.conversation-row')).toHaveCount(1);assert.equal(await row(main.id).locator('button').count(),2);
    await openMenu(main.id);await expect(menu.getByRole('menuitem',{name:/查看匹配：/})).toHaveCount(2);
    await menu.getByRole('menuitem',{name:/查看匹配：第二处/}).click();
    await expect(page.locator(`#conversation-message-${main.id}-${second.id}`)).toHaveClass(/search-match/);
    await expect(page.locator(`#conversation-message-${main.id}-${second.id}`)).toBeFocused();
    await page.getByRole('button',{name:'清除搜索',exact:true}).click();
    await row(legacy.id).locator('.conversation-title').click();await expect(input).toBeDisabled();
    await expect(page.locator('.conversation-intro')).toContainText('历史工具会话只读');
    await openMenu(legacy.id);assert.deepEqual(await menu.getByRole('menuitem').allTextContents(),['重命名','置顶','归档会话','删除会话']);await page.keyboard.press('Escape');
    await row(main.id).locator('.conversation-title').click();await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
    checked('search_snippets_on_demand_original_message_focus_legacy_content_stays_readonly');
    const run=await call(`/api/conversations/${main.id}/runs`,'POST',{client_message_id:'ui-busy',text:'[慢]匿名检查运行中会话，继续慢慢讨论之前尚未决定的蓝桥计划。'});
    await page.getByRole('button',{name:'刷新列表',exact:true}).click();await expect(page.locator('.reply-status')).toContainText('正在');
    await choose(main.id,'归档会话');await expect(page.locator('.conversation-list [role=alert]')).toContainText('运行中的请求');
    await choose(main.id,'删除会话');await page.getByRole('button',{name:'确认删除会话',exact:true}).click();await expect(page.locator('.conversation-list [role=alert]')).toContainText('运行中的请求');
    await page.getByRole('button',{name:'取消删除',exact:true}).click();
    const running=await call(`/api/conversations/${main.id}/runs/${run.id}`);if(running.status==='running')await call(`/api/conversations/${main.id}/runs/${run.id}/stop`,'POST',{expected_attempt:running.attempt});
    const draft=await call(`/api/conversations/${main.id}/runs`,'POST',{client_message_id:'ui-pending-draft',text:'匿名拆解：周五20点前完成120分钟的匿名交付。'});
    await expect.poll(async()=>(await call(`/api/conversations/${main.id}/runs/${draft.id}`)).status,{timeout:30000}).toBe('completed');
    await choose(main.id,'归档会话');await expect(page.locator('.conversation-list [role=alert]')).toContainText('未处理草案');
    await choose(main.id,'删除会话');await page.getByRole('button',{name:'确认删除会话',exact:true}).click();await expect(page.locator('.conversation-list [role=alert]')).toContainText('未处理草案');
    await page.getByRole('button',{name:'取消删除',exact:true}).click();assert.deepEqual(await call('/api/tasks'),[]);
    const current=await call(`/api/conversations/${main.id}`);
    await call(`/api/conversations/${main.id}`,'PATCH',{expected_version:current.version,title:'外部修改后的匿名标题'});
    await choose(main.id,'置顶');await expect(page.locator('.conversation-list [role=alert]')).toContainText(/已修改|其他页面修改/);
    await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
    const stale=await create('等待失效的匿名会话','ui-stale');await page.getByRole('button',{name:'刷新列表',exact:true}).click();await expect(row(stale.id)).toBeVisible();
    await call(`/api/conversations/${stale.id}?expected_version=${stale.version}`,'DELETE');
    await choose(stale.id,'置顶');await expect(page.locator('.conversation-list [role=alert]')).toContainText(/已删除|正式任务和日程仍保留/);
    await page.getByRole('button',{name:'刷新列表',exact:true}).click();
    checked('busy_pending_draft_409_and_deleted_410_rejections_keep_input_and_business');
    await page.getByRole('button',{name:'查看会话小结',exact:true}).click();await page.getByRole('button',{name:'生成会话小结',exact:true}).click();
    await expect(page.getByRole('heading',{name:'会话小结 v1',exact:true})).toBeVisible();
    await page.getByRole('region',{name:'会话小结',exact:true}).getByRole('button',{name:'回到原消息',exact:true}).first().click();
    await expect(page.locator('.search-match')).toBeVisible();
    const auxiliary=page.getByRole('tablist',{name:'辅助栏页签'});await auxiliary.getByRole('tab',{name:'档案',exact:true}).click();
    for(const width of [1440,1280,1024]) {
      await page.setViewportSize({width,height:1000});
      for(const [name,key] of [['日程与任务','schedule'],['查看复盘','review'],['目标与档案','profile']]) {
        await page.getByRole('group',{name:'聊天业务入口'}).getByRole('button',{name,exact:true}).click();
        await expect(page.locator('.v2-shell')).toHaveAttribute('data-navigation',key);await expect(auxiliary.getByRole('tab',{name:'档案',exact:true})).toHaveAttribute('aria-selected','true');
        const splitter=page.getByRole('separator',{name:'调整主体与辅助栏宽度'});await splitter.focus();await splitter.press('ArrowLeft');
        await page.getByRole('button',{name:'展开辅助栏',exact:true}).click();await page.getByRole('button',{name:'恢复普通辅助栏',exact:true}).click();
        await page.getByRole('button',{name:'收起辅助栏',exact:true}).click();await page.getByRole('button',{name:'恢复辅助栏',exact:true}).click();
        await nav.getByRole('button',{name:'首页',exact:true}).click();await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
    }
    await page.reload();await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
    checked('summary_header_generation_source_shortcuts_independent_auxiliary_1440_1280_1024_refresh');
    const touch=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,locale:'zh-CN'});
    const mobile=await touch.newPage();mobile.on('pageerror',error=>errors.push(error.message));await mobile.goto(web);
    await mobile.getByRole('button',{name:'会话',exact:true}).tap();
    const mobileRow=mobile.locator(`.conversation-row[data-conversation-id="${main.id}"]`);
    const mobileTrigger=mobileRow.getByRole('button',{name:/更多操作/});await expect(mobileTrigger).toHaveCSS('opacity','1');
    await mobileTrigger.tap();const mobileMenu=mobile.getByRole('menu',{name:'会话操作菜单'});await expect(mobileMenu).toBeVisible();
    const mobileBox=await mobileMenu.boundingBox();assert.ok(mobileBox.x>=0&&mobileBox.x+mobileBox.width<=390&&mobileBox.y+mobileBox.height<=844);
    await mobile.keyboard.press('Escape');await expect(mobileTrigger).toBeFocused();
    await mobileRow.locator('.conversation-title').tap();const mobileInput=mobile.getByRole('textbox',{name:'会话输入',exact:true});await expect(mobileInput).toBeEnabled();await mobileInput.fill('手机未发送文字');
    let releaseMetadata;const metadataGate=new Promise(resolve=>{releaseMetadata=resolve});
    const metadataURL=api+`/api/conversations/${main.id}`;
    await mobile.route(metadataURL,async route=>{await metadataGate;await route.continue()});
    await mobile.reload({waitUntil:'domcontentloaded'});await expect(mobileInput).toBeDisabled();
    releaseMetadata();await expect(mobileInput).toHaveValue('手机未发送文字');await expect(mobileInput).toBeEnabled();
    await mobile.unroute(metadataURL);
    await mobileInput.fill('恢复检查完成后的新文字');
    await mobile.reload();await expect(mobileInput).toHaveValue('恢复检查完成后的新文字');
    checked('refresh_recovery_waits_for_server_then_preserves_first_replacement_input');
    await mobile.getByRole('button',{name:'辅助栏',exact:true}).tap();
    await mobile.getByRole('tablist',{name:'辅助栏页签'}).getByRole('tab',{name:'日程',exact:true}).tap();
    await expect(mobile.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);await expect(mobile.getByRole('separator')).toBeHidden();
    for(let i=0;i<15;i++){await mobile.keyboard.press('Tab');assert.equal(await mobile.evaluate(()=>Boolean(document.activeElement.closest('[hidden],[inert]'))),false)}
    assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    checked('390_touch_menu_single_surface_draft_refresh_independent_day_preview_focus');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,visibleRows1440:visible,pageErrors:errors,provider:'Mock only',database:'new anonymous database'},null,2));
  } catch(error) {if(page)console.error((await page.locator('body').innerText()).slice(-4500));throw error}
  finally {await browser.close()}
}
(async()=>{
  assert.ok(['localhost','127.0.0.1','[::1]'].includes(new URL(api).hostname));
  const settings=await call('/api/assistant/settings');assert.ok(settings.demo);
  assert.deepEqual(await call('/api/tasks'),[], 'Use a fresh anonymous demo server');
  if(process.argv.includes('--quality')) {await verifyQualityUI();return}
  if(process.argv.includes('--legacy-removal')) {await verifyLegacyRemovalUI();return}
  if(process.argv.includes('--review-sidebar')) {await verifyReviewSidebarUI();return}
  if(process.argv.includes('--ui')) {await verifyConversationUI();return}
  if(process.argv.includes('--skills')) {await verifySkillsUI();return}
  if(process.argv.includes('--schedule-independent')) {await verifyIndependentScheduleUI();return}
  if(process.argv.includes('--draft-sidebar')) {await verifyDraftSidebarUI();return}
  if(process.argv.includes('--defaults')) {await verifyDefaultDraftUI();return}
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
      await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled();
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
    assert.equal((await call('/api/memories')).items.length,0);
    await send('匿名记忆建议：以后学习讨论时喜欢先看短例子。');
    let memory=(await call('/api/memories')).items[0];assert.equal(memory.status,'suggested');
    await page.getByRole('button',{name:'审核或管理记忆',exact:true}).click();
    const memories=page.getByRole('region',{name:'长期记忆管理'});
    await memories.getByRole('button',{name:'确认保存记忆',exact:true}).click();
    await expect(memories.locator('.memory-card')).toContainText('已确认');
    await home();await send('我的学习偏好是什么？');
    await expect(page.locator('.workspace-message.assistant').last()).toContainText('已确认参考：学习讨论时喜欢先看短例子');
    await nav.getByRole('button',{name:'档案',exact:true}).click();
    await memories.getByRole('button',{name:'编辑记忆',exact:true}).click();
    await memories.getByLabel('记忆内容',{exact:true}).fill('学习讨论时喜欢先看完整例子');
    await memories.getByRole('button',{name:'保存记忆修改',exact:true}).click();
    await expect(memories.locator('.memory-card')).toContainText('完整例子');
    await home();await send('我的学习偏好是什么？');
    await expect(page.locator('.workspace-message.assistant').last()).toContainText('已确认参考：学习讨论时喜欢先看完整例子');
    await nav.getByRole('button',{name:'档案',exact:true}).click();
    await memories.getByRole('button',{name:'停用记忆',exact:true}).click();
    await expect(memories.locator('.memory-card')).toContainText('已停用');
    await home();await send('我的学习偏好是什么？');
    await expect(page.locator('.workspace-message.assistant').last()).not.toContainText('已确认参考');
    assert.deepEqual(await call('/api/tasks'),[]);
    checked('stage3:A_memory_suggestion_confirm_reference_edit_disable_no_formal_write');
    // Memory editing survives refresh and keeps a conflicting server version for comparison.
    await nav.getByRole('button',{name:'档案',exact:true}).click();
    await memories.getByRole('button',{name:'编辑记忆',exact:true}).click();
    await memories.getByLabel('记忆内容',{exact:true}).fill('学习讨论时的未保存本地文字');
    await page.reload();await expect(memories).toBeVisible();
    await memories.getByRole('button',{name:'恢复到编辑器',exact:true}).click();
    await expect(memories.getByLabel('记忆内容',{exact:true})).toHaveValue('学习讨论时的未保存本地文字');
    memory=(await call('/api/memories')).items[0];
    await call(`/api/memories/${memory.id}`,'PATCH',{expected_version:memory.version,text:'学习时服务器更新的文字',scope:'study'});
    await memories.getByRole('button',{name:'保存记忆修改',exact:true}).click();
    await expect(memories.getByRole('alert')).toContainText('其他入口修改');
    await expect(memories.getByLabel('记忆内容',{exact:true})).toHaveValue('学习讨论时的未保存本地文字');
    await expect(memories).toContainText('学习时服务器更新的文字');
    page.once('dialog',dialog=>dialog.accept());await memories.getByRole('button',{name:'关闭编辑',exact:true}).click();
    checked('stage3:memory_refresh_recovery_409_preserves_local_and_remote');
    await home();
    const sid=(await call('/api/conversations')).items.find(row=>row.scope==='conversation').id;
    const sources=[];
    for(let i=0;i<135;i++)sources.push(await call(`/api/conversations/${sid}/messages`,'POST',{client_message_id:'history-'+i,text:`匿名多主题讨论 ${i}：${i%2?'还没决定下一步':'比较学习方法'}。`+'长内容'.repeat(40)}));
    await page.reload();await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    assert.ok(await page.locator('.conversation-chat .chat-scroll article').count()<=31);
    await page.getByRole('button',{name:'查看会话小结',exact:true}).click();
    await page.getByRole('button',{name:'生成会话小结',exact:true}).click();
    const summaries=page.getByRole('region',{name:'会话小结'});
    await expect(summaries.getByRole('heading',{name:'会话小结 v1',exact:true})).toBeVisible();
    const summary=(await call(`/api/conversations/${sid}/summaries`)).items[0];assert.equal(summary.coverage.bounded,true);
    assert.ok(summary.source.message_ids.every(mid=>sources.some(source=>source.id===mid)));
    await summaries.getByRole('button',{name:'回到原消息',exact:true}).first().click();
    await expect(page.locator('.search-match')).toBeVisible();
    await page.getByRole('button',{name:'加载更早消息',exact:true}).click();
    await page.getByRole('button',{name:'加载更早消息',exact:true}).click();
    await page.getByRole('button',{name:'加载更早消息',exact:true}).click();
    await page.getByRole('button',{name:'加载更早消息',exact:true}).click();
    assert.ok(await page.locator('.conversation-chat .chat-scroll article').count()<=120);
    const scroll=page.locator('.conversation-chat .chat-scroll');
    await scroll.evaluate(el=>{el.scrollTop=160;el.dispatchEvent(new Event('scroll'))});
    const scrollBefore=await scroll.evaluate(el=>el.scrollTop);assert.ok(scrollBefore>0);
    const anchorBefore=await scroll.evaluate(el=>{const top=el.getBoundingClientRect().top;const item=[...el.querySelectorAll('article')].find(row=>row.getBoundingClientRect().bottom>top);return {id:item.id,offset:item.getBoundingClientRect().top-top}});
    await page.reload();await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    await expect.poll(()=>scroll.evaluate((el,saved)=>{const item=document.getElementById(saved.id);return item?Math.abs(item.getBoundingClientRect().top-el.getBoundingClientRect().top-saved.offset):9999},anchorBefore)).toBeLessThan(4);
    checked('stage3:C_bounded_summary_original_reference_120_DOM_window_scroll_restore');
    const deletedMeta=await call(`/api/conversations/${sid}`);
    await call(`/api/conversations/${sid}?expected_version=${deletedMeta.version}`,'DELETE');
    await page.reload();await expect(page.locator('.conversation-chat [role="alert"]')).toContainText(/已删除|正式任务和日程仍保留/);
    await nav.getByRole('button',{name:'档案',exact:true}).click();
    await expect(memories).toContainText('来源会话已不可访问');
    await home();await page.getByRole('button',{name:'＋ 新对话',exact:true}).click();
    await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    checked('stage3:deleted_summary_source_inaccessible_independent_memory_retained');
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
    await nav.getByRole('button',{name:'日程',exact:true}).click();
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
    await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
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
    await expect(editor.getByRole('status').filter({hasText:/^已保存$/})).toBeVisible();
    await expect(editor.getByRole('article',{name:'已保存的复盘内容'})).toContainText('我审核后的结论。');
    assert.equal((await call('/api/reviews/records')).items.length,2);assert.equal((await call('/api/tasks')).length,3);
    await home();await send('匿名排程：基于回顾，另外提出下周安排建议，30分钟，截止下周五20点。');
    await page.locator('.workspace-message.assistant').last().getByRole('button',{name:'查看最新草案',exact:true}).click();
    await editor.getByRole('button',{name:'确认采用方案',exact:true}).click();
    await expect(editor.getByRole('heading',{name:/已保存/})).toBeVisible();
    await editor.getByRole('button',{name:'关闭草案',exact:true}).click();
    assert.ok((await call('/api/calendar/events?start=2026-10-19&end=2026-10-26')).events.some(e=>e.kind==='formal_task'));
    checked('C:facts_discussion_explicit_review_preview_confirm_then_separate_schedule');
    // Refined surfaces keep every existing control, including in a narrow primary pane.
    for(const width of [1440,1280,1024,390]) {
      await page.setViewportSize({width,height:width===390?844:1000});
      await home();
      const chatInput=page.getByRole('textbox',{name:'会话输入',exact:true});
      await chatInput.fill('视觉切页检查后应保留的输入');
      assert.equal(await page.locator('.conversation-chat').evaluate(el=>getComputedStyle(el).borderTopWidth),'0px');
      for(const name of ['日程','复盘','档案']) {
        await nav.getByRole('button',{name,exact:true}).click();
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
      await page.getByRole('tab',{name:'偏好',exact:true}).click();
      await page.getByRole('button',{name:'新增偏好',exact:true}).click();
      await page.getByLabel('偏好名称',{exact:true}).fill('视觉验收的未保存偏好');
      await nav.getByRole('button',{name:'复盘',exact:true}).click();
      await review.getByRole('tab',{name:'回顾',exact:true}).click();
      const definitions=review.locator('.review-definitions');
      await definitions.locator('summary').click();await expect(definitions.locator('.helper')).toBeVisible();
      await definitions.locator('summary').click();await expect(definitions.locator('.helper')).toBeHidden();
      assert.ok(await review.locator('.review-range-toolbar').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Review controls must stay inside their pane');
      if(width===390) {
        const metrics=await review.locator('.metric-card').evaluateAll(els=>els.map(el=>el.getBoundingClientRect().toJSON()));
        assert.ok(metrics[1].y>=metrics[0].bottom&&metrics[2].y>=metrics[1].bottom,'Phone facts must be readable rows');
      }
      await nav.getByRole('button',{name:'日程',exact:true}).click();
      for(const name of ['天','周','月','年']) {
        await calendar.getByRole('button',{name,exact:true}).click();
        await expect(calendar.getByRole('button',{name,exact:true})).toHaveAttribute('aria-pressed','true');
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
        assert.ok(await calendar.locator('.full-calendar-toolbar').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Calendar controls must stay inside their pane');
      }
      await calendar.getByRole('button',{name:'天',exact:true}).click();
      const dayScroller=calendar.locator('.fc-scroller').last();
      assert.ok(await dayScroller.evaluate(el=>el.scrollHeight>el.clientHeight),'All 24 hours remain scrollable');
      await dayScroller.evaluate(el=>{el.scrollTop=el.scrollHeight});
      const note=calendar.locator('.calendar-reading-note');await note.locator('summary').click();await expect(note).toContainText('拖动不会修改日程');await note.locator('summary').click();
      await nav.getByRole('button',{name:'档案',exact:true}).click();
      await expect(page.getByLabel('偏好名称',{exact:true})).toHaveValue('视觉验收的未保存偏好');
      await page.locator('#preference-editor').getByRole('button',{name:'取消',exact:true}).click();
      await home();await expect(chatInput).toHaveValue('视觉切页检查后应保留的输入');
    }
    checked('polish:1440_1280_1024_390_four_views_readable_facts_notes_and_unsaved_edit_preservation');
    for(const width of [1440,1280,1024]) {
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
        await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
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
    checked('layout:1440_1280_1024_four_pages_resize_keyboard_expand_collapse_reset_independent_tabs_ranges');
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
    async function begin(text){
      await page.getByRole('textbox',{name:'会话输入',exact:true}).fill(text);
      const pending=page.waitForResponse(r=>r.url().endsWith('/runs')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'发送',exact:true}).click();return (await pending).json();
    }
    const recoverRun=await begin('[慢]匿名断线后继续读取');
    await page.reload();await expect(page.locator('.reply-status')).toContainText('正在');
    await page.route('**/runs/*?*',route=>route.request().method()==='GET'?route.abort('failed'):route.continue());
    await expect(page.getByRole('button',{name:'继续读取',exact:true})).toBeVisible();
    await page.unroute('**/runs/*?*');await page.getByRole('button',{name:'继续读取',exact:true}).click();
    await expect(page.locator('.reply-status')).toContainText('回复已完成',{timeout:30000});
    const duplicate=await call(`/api/conversations/${recoverRun.session_id}/runs`,'POST',{text:'[慢]匿名断线后继续读取',client_message_id:recoverRun.client_message_id});
    assert.equal(duplicate.id,recoverRun.id);
    const stopped=await begin('[慢]匿名停止再重试');
    await page.getByRole('button',{name:'停止等待',exact:true}).click();
    assert.equal((await call(`/api/conversations/${stopped.session_id}/runs/${stopped.id}`)).status,'running');
    await page.getByRole('button',{name:'停止生成',exact:true}).click();
    await expect(page.locator('.reply-status')).toContainText('已停止生成');
    await page.getByRole('button',{name:'重试回复',exact:true}).click();
    await expect(page.locator('.reply-status')).toContainText('回复已完成',{timeout:30000});
    assert.equal((await call(`/api/conversations/${stopped.session_id}/runs/${stopped.id}`)).attempt,2);
    const failed=await begin('[失败]匿名同请求重试');
    await expect(page.locator('.reply-status')).toContainText('回复未正常结束',{timeout:30000});
    await page.getByRole('button',{name:'重试回复',exact:true}).click();
    await expect(page.locator('.reply-status')).toContainText('回复已完成',{timeout:30000});
    assert.equal((await call(`/api/conversations/${failed.session_id}/runs/${failed.id}`)).attempt,2);
    const old=await begin('[慢]匿名旧会话迟到内容');
    const createdResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/conversations'&&r.request().method()==='POST');
    await page.getByRole('button',{name:'＋ 新对话',exact:true}).click();
    const created=await (await createdResponse).json();
    await expect(page.locator(`.conversation-row[data-conversation-id="${created.id}"] .conversation-title`)).toHaveAttribute('aria-current','true');
    await expect(page.getByRole('textbox',{name:'会话输入',exact:true})).toBeEnabled();
    await send('新会话独立问候');
    assert.ok(!(await page.locator('.conversation-chat .chat-scroll').innerText()).includes('匿名旧会话迟到内容'));
    await expect.poll(async()=>(await call(`/api/conversations/${old.session_id}/runs/${old.id}`)).status,{timeout:30000}).toBe('completed');
    checked('stage3:E_running_reload_network_resume_stop_wait_stop_generate_same_key_retry_late_isolation');
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'辅助栏',exact:true}).click();
    await auxiliary.getByRole('tab',{name:'日程',exact:true}).click();
    await expect(page.locator('#v2-auxiliary-shared .day-column')).toHaveCount(1);
    await expect(page.getByRole('separator')).toBeHidden();
    for(let i=0;i<25;i++){await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>Boolean(document.activeElement.closest('[hidden],[inert]'))),false)}
    for(const name of ['首页','日程','复盘','档案']) {
      await nav.getByRole('button',{name,exact:true}).click();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    const clocks=await page.locator('.workspace-clock').allTextContents();assert.ok(clocks.every(value=>value===clocks[0]));
    checked('mobile:390_single_surface_focus_no_overflow_refresh_input_restore_shared_clock');
    await home();
    const mobileInput=page.getByRole('textbox',{name:'会话输入',exact:true});await mobileInput.fill('手机键盘模拟的未发送内容');
    await page.evaluate(()=>{Object.defineProperty(window.visualViewport,'height',{configurable:true,value:440});window.visualViewport.dispatchEvent(new Event('resize'))});
    await expect(page.locator('.v2-shell')).toHaveAttribute('data-keyboard','');
    await expect(nav).toBeHidden();
    await page.getByRole('button',{name:'发送',exact:true}).scrollIntoViewIfNeeded();
    const sendBox=await page.getByRole('button',{name:'发送',exact:true}).boundingBox();assert.ok(sendBox.y+sendBox.height<=445);
    await page.evaluate(()=>{delete window.visualViewport.height;window.visualViewport.dispatchEvent(new Event('resize'))});
    await expect(nav).toBeVisible();
    // Actual restore UI rotates the workspace cache identity and interrupts old runs.
    const beforeRestore=await call('/api/assistant/settings');const backup=await call('/api/data/export');
    await nav.getByRole('button',{name:'档案',exact:true}).click();await page.getByRole('tab',{name:'数据管理',exact:true}).click();
    await page.getByText('历史与备份',{exact:true}).click();
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('input[type=file]').setInputFiles({name:'anonymous-memory.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))});
    await expect.poll(async()=>(await call('/api/assistant/settings')).workspace_id).not.toBe(beforeRestore.workspace_id);
    await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'首页',exact:true}).click();
    await expect(page.getByRole('button',{name:'开始新对话',exact:true})).toBeVisible();
    checked('stage3:F_simulated_visual_keyboard_and_actual_JSON_restore_cache_identity');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,consoleErrors:errors,provider:'Mock only',database:'new anonymous database'},null,2));
  }catch(error){if(page)console.error((await page.locator('body').innerText()).slice(-4500));throw error}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
