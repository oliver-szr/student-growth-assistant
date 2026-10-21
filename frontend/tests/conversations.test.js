import test from 'node:test'
import assert from 'node:assert/strict'
import { createConversation, getConversations, getConversation, getConversationMessages, saveConversationMessage, updateConversation, deleteConversation } from '../src/api.js'
import { editKey, readEdit, writeEdit, compatibleEdit, mergeMessages, requestGate, restoredWorkbench, initialWorkbench } from '../src/workbench.js'

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
