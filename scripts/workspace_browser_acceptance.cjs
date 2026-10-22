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
    await page.getByRole('button',{name:'刷新列表',exact:true}).click();await page.waitForLoadState('networkidle');
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
    await choose(main.id,'置顶');await expect(page.locator('.conversation-list [role=alert]')).toContainText('其他页面修改');
    await expect(input).toHaveValue('切换与操作后仍应保留的未发送文字');
    const stale=await create('等待失效的匿名会话','ui-stale');await page.getByRole('button',{name:'刷新列表',exact:true}).click();await expect(row(stale.id)).toBeVisible();
    await call(`/api/conversations/${stale.id}?expected_version=${stale.version}`,'DELETE');
    await choose(stale.id,'置顶');await expect(page.locator('.conversation-list [role=alert]')).toContainText('正式任务和日程仍保留');
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
    assert.equal(await mobile.locator('#v2-auxiliary-shared .day-column').count(),1);await expect(mobile.getByRole('separator')).toBeHidden();
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
  if(process.argv.includes('--ui')) {await verifyConversationUI();return}
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
    await page.reload();await expect(page.locator('.conversation-chat [role="alert"]')).toContainText('正式任务和日程仍保留');
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
    await expect(page.locator('.reply-status')).toContainText('回复未完成',{timeout:30000});
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
    assert.equal(await page.locator('#v2-auxiliary-shared .day-column').count(),1);
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
