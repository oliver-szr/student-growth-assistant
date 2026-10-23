import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
import { visibleSchedule } from '../src/assistant.js'
import { replanAssistant, expandAssistantScope, discardAssistant, confirmAssistant } from '../src/api.js'

const source=await readFile(new URL('../src/components/ScopedChanges.jsx',import.meta.url),'utf8')
const compiled=await transformWithEsbuild(`import React from '${import.meta.resolve('react')}';\n${source.replace('../assistant.js',new URL('../src/assistant.js',import.meta.url).href)}`,'ScopedChanges.jsx',{jsx:'transform',jsxFactory:'React.createElement'})
const {default:ScopedChanges}=await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`)
const interval=(start,end)=>({start_at:`2026-10-05T${start}:00+08:00`,end_at:`2026-10-05T${end}:00+08:00`})
const proposal={status:'ready',replanning:{mode:'local'},change_groups:{counts:{preserved:1,moved:1,added:0,pending:0},preserved:[{ref:'task:2',title:'阅读',before_segments:[interval('12:00','13:00')],after_segments:[interval('12:00','13:00')]}],moved:[{ref:'task:1',title:'报告',before_segments:[interval('09:00','10:00')],after_segments:[interval('10:00','10:30'),interval('11:00','11:30')],reasons:[{code:'TIME_RULE_CONFLICT',message:'报告与临时课程重叠。'}]}]}}
const render=p=>renderToStaticMarkup(React.createElement(ScopedChanges,p))

test('scoped preview renders actual counts, all segments and program facts',()=>{
  const html=render({proposal})
  for(const text of ['保留 1 项','调整 1 项','新增 0 项','待处理 0 项','保留不变','原时间：2026-10-05 09:00–10:00','新时间：2026-10-05 10:00–10:30；2026-10-05 11:00–11:30','报告与临时课程重叠。'])assert.ok(html.includes(text),text)
  assert.ok(!html.includes('允许扩大范围并重新计算'))
})

test('scope failure offers explicit expansion and decline, with loading disabled',()=>{
  const p={...proposal,status:'no_plan',formal_plan_needs_review:true,replanning:{mode:'local',requires_expansion:true}}
  const html=render({proposal:p,pending:true})
  for(const text of ['原正式计划需要重新核对','允许扩大范围并重新计算','暂不扩大，放弃本轮候选','历史、已开始和锁定片段仍受保护'])assert.ok(html.includes(text))
  assert.equal((html.match(/disabled=""/g)||[]).length,2)
  assert.ok(!render({proposal:{...p,status:'stale'}}).includes('允许扩大范围并重新计算'))
  assert.equal(render({proposal:{}}),'')
})

test('calendar marks only actual moves and retains legacy and no-plan behavior',()=>{
  const confirmed=[{ref:'task:1',...interval('09:00','10:00')},{ref:'task:2',...interval('12:00','13:00')}]
  const p={...proposal,selected_refs:['task:1','task:2'],items:[{ref:'task:1',...interval('10:00','11:00')},confirmed[1]]}
  assert.deepEqual(visibleSchedule(confirmed,p).map(x=>x.candidate),[true,false])
  assert.deepEqual(visibleSchedule(confirmed,{...p,status:'no_plan'}),confirmed)
  assert.deepEqual(visibleSchedule(confirmed,{...p,status:'stale'}),confirmed)
})

test('manual replan, explicit expansion, cancellation and adoption use existing routes',async context=>{
  const calls=[]
  context.mock.method(globalThis,'fetch',async (url,options)=>{calls.push({url,options});return new Response(JSON.stringify({status:'ready'}))})
  await replanAssistant(7,'task:3');await expandAssistantScope(9);await discardAssistant(9);await confirmAssistant(10)
  assert.deepEqual(calls.map(x=>new URL(x.url).pathname),['/api/assistant/sessions/7/messages','/api/assistant/proposals/9/preview','/api/assistant/proposals/9/discard','/api/assistant/proposals/10/confirm'])
  assert.deepEqual(JSON.parse(calls[0].options.body).actions,[{op:'update',target:'task:3',fields:{}}])
  assert.equal(JSON.parse(calls[0].options.body).replan,true)
  assert.equal(JSON.parse(calls[1].options.body).expand_scope,true)
})
