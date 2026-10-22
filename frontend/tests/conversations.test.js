import test from 'node:test'
import assert from 'node:assert/strict'
import { createConversation, getConversations, getConversation, getConversationMessages, saveConversationMessage, updateConversation, deleteConversation } from '../src/api.js'
import { editKey, readEdit, writeEdit, compatibleEdit, mergeMessages, applyReply, requestGate, restoredWorkbench, initialWorkbench, visibleChatMessages, toolNotices,messageResourceLinks } from '../src/workbench.js'

test('generic chat navigation has one header entry while genuine resource links remain visible',()=>{
  const task={page:'schedule',kind:'task',id:7,label:'真实任务'}
  assert.deepEqual(messageResourceLinks([{page:'schedule',kind:'schedule',label:'查看正式日程与任务'},task,task]),[task])
  assert.deepEqual(messageResourceLinks(null),[])
  assert.deepEqual(toolNotices([{tool:'tasks'}]),['已查询：任务。'])
})
import { startConversationRun, getConversationRun, stopConversationRun, retryConversationRun } from '../src/api.js'
import { canConfirmDraft,previewCompletionDeadline } from '../src/draftCoordination.js'

test('edited incomplete previews can submit for validation without enabling stale or final drafts',()=>{
  const partial={status:'needs_input',content:{schedule:{}},unresolved:['请填写截止时间']}
  assert.equal(canConfirmDraft(partial,false),false)
  assert.equal(canConfirmDraft(partial,true),true)
  assert.equal(canConfirmDraft({status:'ready'},false),true)
  assert.equal(canConfirmDraft(null,true),false)
  for(const status of ['applied','discarded','superseded','stale'])assert.equal(canConfirmDraft({...partial,status},true),false)
})

test('explicit completion deadline uses the last segment of the target rather than unrelated tasks',()=>{
  const draft={schedule_target:'draft:preview-7',items:[
    {ref:'draft:preview-7',end_at:'2026-10-14T19:45:00+08:00'},
    {ref:'task:5',end_at:'2026-10-17T22:00:00+08:00'},
    {ref:'draft:preview-7',end_at:'2026-10-14T20:40:00+08:00'}]}
  assert.equal(previewCompletionDeadline(draft),'2026-10-14T20:40:00+08:00')
  assert.equal(previewCompletionDeadline({...draft,items:[]}),null)
  assert.equal(previewCompletionDeadline({...draft,schedule_target:null}),null)
})
import { getCalendarEvents, getReviewFacts, saveReviewRecord, editWorkspaceDraft, actWorkspaceDraft, createReviewDraft } from '../src/api.js'
import { calendarEvent, reviewRange } from '../src/calendar.js'
import { registerEditor, coordinateDrafts, hasUnsavedDraft } from '../src/draftCoordination.js'
import { getMemories,getMemory,createMemory,editMemory,actMemory,getConversationSummaries,createConversationSummary,getSummaryRequest } from '../src/api.js'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFile } from 'node:fs/promises'
import { transformWithEsbuild } from 'vite'

const menuSource=await readFile(new URL('../src/components/ConversationMenu.jsx',import.meta.url),'utf8')
const compiledMenu=await transformWithEsbuild(`import React from '${import.meta.resolve('react')}';\n${menuSource.replace("from 'react'",`from '${import.meta.resolve('react')}'`).replace("from 'react-dom'",`from '${import.meta.resolve('react-dom')}'`)}`,'ConversationMenu.jsx',{jsx:'transform',jsxFactory:'React.createElement'})
const {ConversationRow,menuPosition}=await import(`data:text/javascript;base64,${Buffer.from(compiledMenu.code).toString('base64')}`)

test('query results produce one truthful notice, preserving distinct errors and questions',()=>{
  assert.deepEqual(toolNotices([{tool:'tasks'},{tool:'calendar'},{tool:'tasks'}]),['已查询：任务、日程。'])
  assert.deepEqual(toolNotices([{tool:'planning_draft',questions:['几点前完成？']},{tool:'planning_draft',questions:['几点前完成？']},
    {tool:'calendar',error:'FAILED',message:'查询失败'},{tool:'calendar',error:'FAILED',message:'查询失败'}]),['几点前完成？','查询失败'])
  assert.deepEqual(toolNotices([{tool:'planning_draft',draft:{id:1}}]),[])
  assert.deepEqual(toolNotices([{tool:'planning_draft',questions:['几点前完成？']}],['几点前完成？']),[])
})

test('recovered model errors retain a truthful fallback notice and completed query receipts',()=>{
  assert.deepEqual(toolNotices([{tool:'tasks'},{tool:'planning_draft',error:'INVALID_TOOL_ARGUMENTS',message:'无效参数',recovered_by:'trusted_defaults'},
    {tool:'planning_draft',draft:{id:1}}]),['模型处理未完成，已使用已知信息生成默认初稿，请审核。','已查询：任务。'])
})
test('later success hides obsolete empty failed placeholders without deleting partial replies or cards',()=>{
  const messages=[{id:1,role:'assistant',text:'',content:{status:'failed',links:[{page:'schedule'}]}},
    {id:2,role:'assistant',text:'已收到的部分内容',content:{status:'failed'}},
    {id:3,role:'assistant',text:'',content:{status:'failed',tools:[{draft:{id:1}}]}},
    {id:4,role:'assistant',text:'最新完整回答',content:{status:'completed'}}]
  assert.deepEqual(visibleChatMessages(messages).map(m=>m.id),[2,3,4])
  assert.equal(messages.length,4)
  assert.deepEqual(visibleChatMessages(messages.slice(0,1)),messages.slice(0,1))
})

test('conversation row exposes only title and menu, including archived and legacy resources',()=>{
  for(const row of [{id:1,title:'长标题 & 真实正文',scope:'conversation'}, {id:2,title:'历史会话',scope:'planning',archived_at:'2026-10-22'}]){
    const html=renderToStaticMarkup(React.createElement(ConversationRow,{row,onOpen:()=>{},onMenu:()=>{},expanded:false}))
    assert.equal((html.match(/<button /g)||[]).length,2)
    assert.ok(html.includes('aria-haspopup="menu"'));assert.ok(html.includes('aria-expanded="false"'))
    assert.ok(html.includes('title="'+row.title.replace('&','&amp;')+'"'))
    assert.ok(!/<small|<time|<details|持久会话|历史工具|会话操作/.test(html))
  }
})
test('selection and menu expansion remain separate presentation states',()=>{
  const html=renderToStaticMarkup(React.createElement(ConversationRow,{row:{id:7,title:'未选中'},selected:false,expanded:true,onOpen:()=>{},onMenu:()=>{}}))
  assert.ok(html.includes('aria-expanded="true"'));assert.ok(!html.includes('aria-current='));assert.ok(!html.includes('data-selected='))
})
test('conversation menu flips above a bottom row and stays inside narrow viewports',()=>{
  const value=menuPosition({top:730,bottom:766,right:220},{width:248,height:180},{width:1280,height:800})
  assert.equal(value.top,544);assert.equal(value.left,8)
  const mobile=menuPosition({top:810,bottom:844,right:390},{width:248,height:900},{width:390,height:844})
  assert.equal(mobile.top,8);assert.equal(mobile.left,134);assert.equal(mobile.maxHeight,828)
})
test('menu beside a top row remains below without extending past the right edge',()=>{
  assert.deepEqual(menuPosition({top:20,bottom:56,right:1438},{width:248,height:180},{width:1440,height:900}),{left:1184,top:62,maxHeight:884})
})

test('secretary uses real memory versions, explicit summary requests and stable retry identifiers',async context=>{
  const calls=[];context.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url:new URL(url),...options});return new Response('{}')})
  await getMemories({status:'suggested',q:'100% 学习',offset:25});await getMemory(3)
  await createMemory({client_request_id:'once',text:'先看例子',scope:'study'})
  await editMemory(3,{expected_version:2,text:'修改参考',scope:'study'})
  await actMemory(3,{expected_version:3,action:'disable'})
  await getConversationSummaries(7);await createConversationSummary(7,{client_request_id:'summary-once'})
  await getSummaryRequest(7,'summary-once');await createConversationSummary(7,{client_request_id:'summary-once',retry_attempt:1})
  await getConversationMessages(7,{latest:true,limit:30})
  assert.equal(calls[0].url.searchParams.get('q'),'100% 学习');assert.equal(calls[0].url.searchParams.get('offset'),'25')
  assert.equal(calls[3].method,'PATCH');assert.equal(JSON.parse(calls[4].body).expected_version,3)
  assert.equal(calls[5].method,undefined);assert.equal(calls[7].url.pathname,'/api/conversations/7/summaries/requests/summary-once')
  assert.equal(JSON.parse(calls[8].body).client_request_id,'summary-once');assert.equal(JSON.parse(calls[8].body).retry_attempt,1)
  assert.equal(calls[9].url.searchParams.get('latest'),'true')
  assert.ok(calls.every(c=>!c.url.pathname.includes('/assistant/')))
})

for(const [code,message] of [['MEMORY_VERSION_CONFLICT','核对'],['SOURCE_UNAVAILABLE','来源'],['SUMMARY_IN_PROGRESS','小结'],['AI_CONTEXT_TOO_LARGE','上限'],['AI_SKILLS_UNAVAILABLE','技能']])test(`secretary ${code} preserves actionable error code`,async context=>{
  context.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:{code}}),{status:409}))
  await assert.rejects(()=>actMemory(3,{expected_version:1,action:'confirm'}),e=>e.code===code&&e.message.includes(message))
})

test('stage2 saves local valid draft edits before providing exact current server references',async()=>{
  let dirty=true,version='old';const order=[]
  const unregister=registerEditor('test-draft',{dirty:()=>dirty,save:async()=>{order.push('save');dirty=false;version='latest'},reference:async()=>{order.push('reference');return {kind:'breakdown',id:5,version}}})
  try{
    assert.equal(hasUnsavedDraft(),true)
    assert.deepEqual(await coordinateDrafts(),[{kind:'breakdown',id:5,version:'latest'}])
    assert.deepEqual(order,['save','reference']);assert.equal(hasUnsavedDraft(),false)
  }finally{unregister()}
})

test('invalid draft edits block AI coordination and retain editable local content',async()=>{
  const content={minutes:-1};let referenced=false
  const unregister=registerEditor('invalid',{dirty:()=>true,save:async()=>{throw Error('请修正时长')},reference:()=>{referenced=true}})
  try{await assert.rejects(coordinateDrafts,/请修正时长/);assert.equal(content.minutes,-1);assert.equal(referenced,false)}finally{unregister()}
})

test('Shanghai calendar preserves all-day deadlines and spans midnight in any browser zone',()=>{
  const original={id:'plan:1',start:'2026-10-14T15:30:00Z',end:'2026-10-14T16:30:00Z',kind:'formal_task',allDay:false}
  const event=calendarEvent(original)
  assert.equal(event.start,'2026-10-14T23:30:00Z');assert.equal(event.end,'2026-10-15T00:30:00Z')
  assert.equal(event.extendedProps,original);assert.equal(event.editable,false)
  assert.equal(calendarEvent({id:'deadline:1',start:'2026-10-15',allDay:true,kind:'deadline'}).start,'2026-10-15')
})

test('day/week/month reviews use exclusive bounds including leap month and Shanghai week',()=>{
  assert.deepEqual(reviewRange('2026-10-18','week'),['2026-10-12','2026-10-19'])
  assert.deepEqual(reviewRange('2024-02-29','month'),['2024-02-01','2024-03-01'])
  assert.deepEqual(reviewRange('2026-12-31','day'),['2026-12-31','2027-01-01'])
})

test('stage2 endpoints keep readonly views, draft editing and explicit formal confirmation separate',async context=>{
  const calls=[];context.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url:new URL(url),...options});return new Response('{}')})
  await getCalendarEvents('2026-01-01','2027-01-01');await getReviewFacts('2026-10-12','2026-10-19')
  await editWorkspaceDraft('breakdown',5,'version1',{parent:{title:'同一草案'}})
  await actWorkspaceDraft('breakdown',5,'version2','confirm')
  await createReviewDraft(7,{client_request_id:'review-once',start_date:'2026-10-12',end_date:'2026-10-19'})
  await saveReviewRecord({client_request_id:'manual',title:'自己写几句'})
  await saveReviewRecord({expected_version:2,title:'编辑'},9)
  assert.equal(calls[0].url.searchParams.get('end'),'2027-01-01')
  assert.equal(calls[1].method,undefined)
  assert.equal(calls[2].method,'PATCH');assert.equal(JSON.parse(calls[2].body).expected_version,'version1')
  assert.equal(calls[3].url.pathname,'/api/workspace/drafts/breakdown/5/confirm')
  assert.equal(calls[4].url.pathname,'/api/conversations/7/review-drafts')
  assert.equal(calls[6].method,'PATCH');assert.equal(calls[6].url.pathname,'/api/reviews/records/9')
})

test('reply cursor uses server code points, handles reset and rejects duplicate deltas',()=>{
  const first={assistant_message_id:5,session_id:1,reset:true,delta:'你好🙂',next_cursor:3,from_cursor:0,content:{status:'running'}}
  let messages=applyReply([],first)
  const tail={...first,reset:false,delta:'继续',from_cursor:3,next_cursor:5}
  messages=applyReply(messages,tail);assert.equal(messages[0].text,'你好🙂继续')
  assert.deepEqual(applyReply(messages,tail),messages)
  assert.equal(applyReply(messages,{...first,delta:'新尝试'})[0].text,'新尝试')
})

test('chat runs use versioned attempt actions and bounded cursor reads, never planning',async context=>{
  const calls=[]
  context.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url:new URL(url),...options});return new Response('{}')})
  await startConversationRun(2,{text:'你好',client_message_id:'once'})
  await getConversationRun(2,9,15,2);await stopConversationRun(2,9,2);await retryConversationRun(2,9,2)
  assert.ok(calls.every(c=>c.url.pathname.startsWith('/api/conversations/2/runs')))
  assert.equal(calls[1].url.searchParams.get('after'),'15');assert.equal(calls[1].url.searchParams.get('attempt'),'2')
  assert.deepEqual(JSON.parse(calls[3].body),{expected_attempt:2})
})

test('conversation operations use real versioned endpoints and never planning AI', async context => {
  const calls=[]
  context.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url:new URL(url),...options});return new Response(JSON.stringify({items:[]}))})
  await getConversations({q:'100%_ 报告',archive:'all',scope:'all',offset:30,limit:30})
  await createConversation({client_request_id:'create-once'})
  await getConversation(7)
  await updateConversation(7,{expected_version:3,title:'新名称'})
  await updateConversation(7,{expected_version:4,pinned:true,archived:false})
  await getConversationMessages(7,{after_id:11,limit:30})
  await getConversationMessages(7,{before_id:11,limit:30})
  await saveConversationMessage(7,{client_message_id:'same-on-retry',text:'保存正文'})
  await deleteConversation(7,5)
  assert.ok(calls.every(call=>call.url.pathname.startsWith('/api/conversations')))
  assert.equal(calls[0].url.searchParams.get('q'),'100%_ 报告')
  assert.equal(calls[0].url.searchParams.get('offset'),'30')
  assert.deepEqual(JSON.parse(calls[3].body),{expected_version:3,title:'新名称'})
  assert.equal(calls[5].url.searchParams.get('after_id'),'11')
  assert.equal(calls[6].url.searchParams.get('before_id'),'11')
  assert.equal(calls[8].method,'DELETE')
  assert.equal(calls[8].url.searchParams.get('expected_version'),'5')
})

for(const [code,text] of [
  ['CONVERSATION_BUSY','运行中的请求'],['CONVERSATION_HAS_DRAFTS','未处理草案'],
  ['CONVERSATION_VERSION_CONFLICT','其他页面修改'],['CONVERSATION_ARCHIVED','归档'],
  ['CONVERSATION_DELETED','正式任务和日程仍保留'],
])test(`backend ${code} remains actionable with machine code`,async context=>{
  context.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:{code}}),{status:code==='CONVERSATION_DELETED'?410:409}))
  await assert.rejects(()=>deleteConversation(7,1),error=>error.code===code&&error.message.includes(text))
})

test('late reads lose permission to update another conversation or search generation',async()=>{
  const gate=requestGate();const old=gate.next();let release
  const pending=new Promise(resolve=>{release=resolve})
  const output=[]
  const read=pending.then(value=>{if(gate.current(old))output.push(value)})
  const current=gate.next();assert.ok(gate.current(current));release('old conversation text');await read
  assert.deepEqual(output,[])
  gate.next();assert.equal(gate.current(current),false)
})

test('message pages deduplicate by backend ID and keep stable order',()=>{
  assert.deepEqual(mergeMessages([{id:4,text:'old'},{id:9}], [{id:2},{id:4,text:'server'}]),[{id:2},{id:4,text:'server'},{id:9}])
})

test('edit caches isolate workspace, session and resource, including NULL versions',()=>{
  const map=new Map(),storage={getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)}
  const keys=[editKey('one','conversation:7:input'),editKey('one','conversation:8:input'),editKey('two','conversation:7:input'),editKey('one','profile-editors')]
  assert.equal(new Set(keys).size,4)
  keys.forEach((key,index)=>writeEdit(storage,key,index===3?'baseVersion:2':null,{text:`draft${index}`}))
  assert.equal(readEdit(storage,keys[0]).value.text,'draft0')
  storage.removeItem(keys[0]);assert.equal(readEdit(storage,keys[0]),null)
  assert.equal(readEdit(storage,keys[1]).value.text,'draft1')
  assert.notEqual(readEdit(storage,keys[3]).base,'baseVersion:3')
  assert.equal(editKey(null,'input'),null)
})

test('corrupt and blocked storage are errors, never empty successful restoration',()=>{
  assert.throws(()=>readEdit({getItem:()=>'{broken'},'key'))
  assert.throws(()=>readEdit({getItem:()=>JSON.stringify({schema:0,value:'old'})},'key'))
  const blocked={getItem(){throw Error('blocked')},setItem(){throw Error('quota')}}
  assert.throws(()=>readEdit(blocked,'key'),/blocked/)
  assert.throws(()=>writeEdit(blocked,'key',null,{text:'retained in editor'}),/quota/)
})

test('restored UI validates states, restores visited pages and preserves width preference',()=>{
  const state=restoredWorkbench({navigation:'profile',auxiliaryPage:'review',panel:'collapsed',mobile:'primary',conversations:false},initialWorkbench)
  assert.equal(state.navigation,'profile');assert.equal(state.auxiliaryPage,'review');assert.equal(state.panel,'collapsed')
  assert.ok(state.visited.includes('profile'));assert.equal(state.splitRatio,initialWorkbench.splitRatio)
  assert.equal(restoredWorkbench({navigation:'bogus',panel:'giant'},initialWorkbench).navigation,'home')
})


test('old or malformed editor payloads cannot replace a current form shape',()=>{
  const sample={manual:false,form:{title:'',minutes:'60'},request:null}
  assert.equal(compatibleEdit({manual:true,form:null,request:null},sample),false)
  assert.equal(compatibleEdit({manual:true,form:{title:'retained',minutes:'7'},request:null},sample),true)
  assert.equal(compatibleEdit(null,sample),false)
  assert.equal(compatibleEdit({text:'chat',requestId:null},{text:'',requestId:null}),true)
  const selection = { editingId: 5, addingChildId: undefined, showAdd: false }
  assert.equal(compatibleEdit(JSON.parse(JSON.stringify(selection)), selection), true)
})
