import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
import { breakdownPayload, breakdownTotals, editableContent, groupTasks, moveChild } from '../src/taskHierarchy.js'
import { createTaskBreakdown, getTaskBreakdowns, getTaskBreakdown, editTaskBreakdown, confirmTaskBreakdown, discardTaskBreakdown } from '../src/api.js'

async function component(name) {
  const path = new URL(`../src/components/${name}.jsx`, import.meta.url)
  let source = await readFile(path, 'utf8')
  if(name==='WorkspaceDraft'){
    const breakdown=await component('TaskBreakdown')
    source=source.replace("from './TaskBreakdown.jsx'",`from '${breakdown.url}'`)
  }
  if (name !== 'EditRecovery' && source.includes("from './EditRecovery.jsx'")) {
    const recovery = await component('EditRecovery')
    source = source.replace("from './EditRecovery.jsx'", `from '${recovery.url}'`)
  }
  const imports = source.replace(/from '(\.\.\/[^']+)'/g, (_, relative) => `from '${new URL(relative, path).href}'`).replace("from 'react'", `from '${import.meta.resolve('react')}'`)
  const compiled = await transformWithEsbuild(`import React from '${import.meta.resolve('react')}';\n${imports}`, `${name}.jsx`, { jsx: 'transform', jsxFactory: 'React.createElement' })
  const url = `data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`
  return { ...await import(url), url }
}

const { default: TaskHierarchy } = await component('TaskHierarchy')
const { BreakdownEditor } = await component('TaskBreakdown')
const { PreviewDetails,PlanningStartField } = await component('WorkspaceDraft')
const deadline = '2026-10-25T12:00:00Z'
const content = { parent: { title: '课程项目', description: null, deadline }, children: [{ title: '需求分析', description: null, duration_minutes: 60, deadline, sort_order: 0 }, { title: '实现', description: null, duration_minutes: 120, deadline, sort_order: 1 }] }
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props))

test('full planning action renders an editable five-minute datetime picker from its candidate',()=>{
  const action={op:'add',target:'draft:report',fields:{title:'实验报告'}}
  const html=render(PlanningStartField,{draft:{items:[{ref:action.target,start_at:'2026-10-29T11:00:00Z'}]},action,onChange:()=>{}})
  assert.match(html,/开始时间/)
  assert.match(html,/type="datetime-local"/)
  assert.match(html,/step="300"/)
  assert.match(html,/value="2026-10-29T19:00"/)
  assert.equal(render(PlanningStartField,{draft:{items:[]},action:{op:'remove',target:'task:1'},onChange:()=>{}}),'')
})

test('schedule preview distinguishes defaults, user work time, unset deadline and real conflicts',()=>{
  const html=render(PreviewDetails,{draft:{content:{schedule:{day:'2026-10-14',start_time:'19:00',duration_minutes:90,deadline:null,segments:2,break_minutes:10}},
    field_sources:{start_time:'system_default',duration_minutes:'user_explicit'},unresolved:['请补充真实截止时间'],notices:['课程冲突未排入']}})
  assert.match(html,/19:00/);assert.match(html,/系统默认，可修改/);assert.match(html,/90分钟（你提供）/)
  assert.match(html,/硬截止时间：未设置/);assert.match(html,/休息10分钟，不计入工作时长/)
  assert.match(html,/请补充真实截止时间/);assert.match(html,/课程冲突未排入/)
})

test('partial breakdown edit retains NULL deadlines instead of inventing a date',()=>{
  const partial={parent:{title:'报告',deadline:null},children:[{title:'待细化',deadline:null,duration_minutes:60,sort_order:0}]}
  const payload=breakdownPayload(editableContent(partial))
  assert.equal(payload.parent.deadline,null);assert.equal(payload.children[0].deadline,null)
})

test('task hierarchy keeps ordinary tasks and stable child IDs in suggested order', () => {
  const rows = [{ id: 1, task_kind: 'executable' }, { id: 2, task_kind: 'container' }, { id: 4, parent_task_id: 2, sort_order: 1 }, { id: 3, parent_task_id: 2, sort_order: 0 }]
  const groups = groupTasks(rows)
  assert.deepEqual(groups.map(g => g.task.id), [1, 2])
  assert.deepEqual(groups[1].children.map(c => c.id), [3, 4])
  assert.deepEqual(rows.map(r => r.id), [1, 2, 4, 3])
})

test('parent renders real progress, expandable children, estimates and no execution controls', () => {
  const tasks = [{ id: 2, task_kind: 'container', title: '项目', deadline, progress: { completed_children: 1, total_estimate_minutes: 180, actual_minutes: 30, executed_children: 1, scheduled_children: 2, partial_children: 1 } }, { id: 3, title: '分析', status: 'done', parent_task_id: 2, sort_order: 0 }]
  const html = render(TaskHierarchy, { tasks, renderTask: t => React.createElement('p', { key: t.id }, `${t.title} · ${t.status}`) })
  for (const text of ['父任务 · 汇总容器', '已确认完成 1 / 1 项', '总预计 180 分钟', '已安排 2 项', '部分完成 1 项', '子任务（1）', '<details open="">', '分析 · done', '建议顺序']) assert.ok(html.includes(text), text)
  assert.ok(!html.includes('开始计时'))
})

test('empty parent offers manual addition and no invented progress', () => {
  const html = render(TaskHierarchy, { tasks: [{ id: 1, task_kind: 'container', title: '空项目', deadline }], renderTask: () => null })
  assert.ok(html.includes('还没有子任务，可手动添加。'))
  assert.ok(html.includes('已确认完成 0 / 0 项'))
})

test('draft editing renders title, duration, deadline, removal, manual addition and order controls', () => {
  const html = render(BreakdownEditor, { content: editableContent(content), expected: 120, onChange: () => {} })
  for (const text of ['父任务标题', '父任务截止时间', '子任务 1 标题', '子任务 1 预计分钟', '子任务 2 截止时间', '原始预期 120 分钟', '子任务合计 180 分钟', '+60 分钟', '删除建议', '增加手动子任务', '上移', '下移', '不强制前后依赖']) assert.ok(html.includes(text), text)
})

test('edits recompute workload while preserving original expected duration', () => {
  const children = [...content.children.map(c => ({ ...c }))]
  children[0].duration_minutes = 90
  children.splice(1, 1)
  children.push({ ...content.children[1], duration_minutes: 30 })
  assert.deepEqual(breakdownTotals(children, 180), { total: 120, difference: -60 })
  assert.equal(content.children[0].duration_minutes, 60)
})

test('reordering is advice and normalizes server order without changing child values', () => {
  const moved = moveChild(content.children, 1, -1)
  assert.deepEqual(moved.map(c => c.title), ['实现', '需求分析'])
  assert.deepEqual(moved.map(c => c.sort_order), [0, 1])
  assert.deepEqual(moveChild(content.children, 0, -1), content.children)
  assert.deepEqual(content.children.map(c => c.title), ['需求分析', '实现'])
})

test('editing round trip uses Shanghai deadlines and sends numeric estimates', () => {
  const local = editableContent(content)
  assert.equal(local.parent.deadline, '2026-10-25T20:00')
  local.children[0].duration_minutes = '90'
  const payload = breakdownPayload(local)
  assert.equal(payload.parent.deadline, '2026-10-25T20:00:00+08:00')
  assert.equal(payload.children[0].duration_minutes, 90)
})

test('empty draft and pending editor show truthful states and bounded manual input', () => {
  const empty = render(BreakdownEditor, { content: { ...editableContent(content), children: [] }, expected: 180, disabled: true, onChange: () => {} })
  assert.ok(empty.includes('至少添加一项'))
  assert.ok(empty.includes('<fieldset class="breakdown-fields" disabled="">'))
  const full = render(BreakdownEditor, { content: { ...editableContent(content), children: Array.from({ length: 20 }, () => editableContent(content).children[0]) }, expected: 180, onChange: () => {} })
  assert.match(full, /disabled="">增加手动子任务/)
})

test('draft lifecycle uses typed API wrappers, versions and explicit confirm', async context => {
  const calls = []
  context.mock.method(globalThis, 'fetch', async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ status: 'ready' })) })
  await createTaskBreakdown({ source: 'manual' }); await getTaskBreakdowns(); await getTaskBreakdown(4)
  await editTaskBreakdown(4, { version: 2, content }); await confirmTaskBreakdown(4, 3); await discardTaskBreakdown(4, 3)
  assert.deepEqual(calls.map(c => new URL(c.url).pathname), ['/api/tasks/breakdown-drafts', '/api/tasks/breakdown-drafts', '/api/tasks/breakdown-drafts/4', '/api/tasks/breakdown-drafts/4', '/api/tasks/breakdown-drafts/4/confirm', '/api/tasks/breakdown-drafts/4/discard'])
  assert.equal(calls[3].options.method, 'PATCH')
  assert.deepEqual(JSON.parse(calls[4].options.body), { version: 3 })
})

test('stale, invalid hierarchy, missing AI and network errors have actionable feedback', async context => {
  for (const [code, status, text] of [['STALE_DRAFT', 409, '最新资料'], ['DRAFT_VERSION_CONFLICT', 409, '重新加载草案'], ['CHILD_DEADLINE_INVALID', 422, '不能晚于父任务'], ['AI_NOT_CONFIGURED', 503, '手动拆解']]) {
    context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: { code } }), { status }))
    await assert.rejects(() => confirmTaskBreakdown(4, 2), e => e.code === code && e.message.includes(text))
  }
  context.mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline') })
  await assert.rejects(() => getTaskBreakdowns(), /无法连接后端/)
})
