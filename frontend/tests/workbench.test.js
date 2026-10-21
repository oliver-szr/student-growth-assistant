import test from 'node:test'
import assert from 'node:assert/strict'
import { nearBottom, reviewMetrics, progressPercent, initialWorkbench, workbenchReducer, workbenchVisibility } from '../src/workbench.js'
import { readFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
test('new messages must not displace a reader of history',()=>{assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:100}),false);assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:560}),true)})
test('missing facts stay unknown while confirmed zero remains zero',()=>{assert.deepEqual(reviewMetrics(null),[null,null,null]);assert.deepEqual(reviewMetrics({completed_count:0,confirmed_actual_minutes:90,planned_minutes:120}),[0,90,120])})
test('progress only renders from finite facts and keeps actual numbers separate',()=>{assert.equal(progressPercent(null,3),null);assert.equal(progressPercent(1,0),null);assert.equal(progressPercent(4,3),100);assert.equal(progressPercent(1,4),25)})

test('home focuses chat without resetting the selected workspace or its size', () => {
  const review = workbenchReducer(initialWorkbench, { type: 'open', page: 'review' })
  const expanded = workbenchReducer(review, { type: 'panel', value: 'expanded' })
  const home = workbenchReducer(expanded, { type: 'open', page: 'home' })
  assert.equal(home.mobile, 'chat')
  assert.equal(home.page, 'review')
  assert.equal(home.panel, 'expanded')
  assert.equal(initialWorkbench.navigation, 'home')
  assert.deepEqual(initialWorkbench.visited, ['schedule'])
})

test('navigation and tabs reuse one page and reopening restores a collapsed workspace', () => {
  let state = initialWorkbench
  for (const page of ['profile', 'review', 'profile', 'schedule', 'profile']) state = workbenchReducer(state, { type: 'open', page })
  assert.deepEqual(state.visited, ['schedule', 'profile', 'review'])
  state = workbenchReducer(state, { type: 'panel', value: 'collapsed' })
  assert.equal(state.page, 'profile')
  state = workbenchReducer(state, { type: 'open', page: 'profile' })
  assert.equal(state.panel, 'normal')
  assert.equal(state.navigation, state.page)
  assert.equal(state.visited.length, 3)
})

test('expanded calendar temporarily hides conversations and preserves both list preferences', () => {
  for (const conversations of [false, true]) {
    const original = { ...initialWorkbench, conversations }
    const expanded = workbenchReducer(original, { type: 'panel', value: 'expanded' })
    assert.equal(workbenchVisibility(expanded, false).conversations, false)
    const restored = workbenchReducer(expanded, { type: 'panel', value: 'normal' })
    assert.equal(workbenchVisibility(restored, false).conversations, conversations)
    assert.equal(workbenchVisibility(restored, false).chat, true)
  }
})

test('mobile has exactly one interactive surface, including when desktop workspace is collapsed', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'panel', value: 'collapsed' })
  for (const value of ['conversations', 'chat', 'workspace']) {
    state = workbenchReducer(state, { type: 'mobile', value })
    const visible = workbenchVisibility(state, true)
    assert.equal(Object.values(visible).filter(Boolean).length, 1)
    assert.equal(visible[value], true)
  }
  assert.equal(state.panel, 'normal')
})

test('unknown page, size and surface cannot corrupt workspace state', () => {
  for (const action of [{ type: 'open', page: 'settings' }, { type: 'panel', value: 'huge' }, { type: 'mobile', value: 'all' }, { type: 'unknown' }]) {
    assert.equal(workbenchReducer(initialWorkbench, action), initialWorkbench)
  }
})

const shellSource = await readFile(new URL('../src/components/WorkspaceShell.jsx', import.meta.url), 'utf8')
const compiledShell = await transformWithEsbuild(`import React from '${import.meta.resolve('react')}';\n${shellSource.replace("from 'react'", `from '${import.meta.resolve('react')}'`).replace('../workbench.js', new URL('../src/workbench.js', import.meta.url).href)}`, 'WorkspaceShell.jsx', { jsx: 'transform', jsxFactory: 'React.createElement' })
const { default: WorkspaceShell } = await import(`data:text/javascript;base64,${Buffer.from(compiledShell.code).toString('base64')}`)
const renderShell = state => renderToStaticMarkup(React.createElement(WorkspaceShell, { state, dispatch: () => {}, conversation: 7, chat: 'CHAT', review: 'REVIEW', profile: 'PROFILE' }, 'SCHEDULE'))

test('shell exposes exactly three linked tabs, real current conversation and honest unavailable controls', () => {
  const html = renderShell(initialWorkbench)
  assert.equal((html.match(/role="tab"/g) || []).length, 3)
  for (const page of ['schedule', 'review', 'profile']) assert.ok(html.includes(`aria-controls="v2-page-${page}"`))
  assert.ok(html.includes('本周规划对话'))
  assert.ok(html.includes('新建、搜索与归档将在后续开放'))
  assert.ok(html.includes('href="?layout=legacy"'))
  assert.ok(html.includes('type="search" placeholder="搜索会话" disabled=""'))
  assert.ok(!html.includes('登录'))
})

test('inactive pages stay mounted but hidden and inert, as does a collapsed workspace', () => {
  const html = renderShell(workbenchReducer(initialWorkbench, { type: 'panel', value: 'collapsed' }))
  assert.match(html, /class="v2-workspace-open" hidden="" inert=""/)
  assert.match(html, /id="v2-page-review"[^>]*hidden="" inert="">REVIEW/)
  assert.match(html, /id="v2-page-profile"[^>]*hidden="" inert="">PROFILE/)
  assert.ok(html.includes('恢复工作区'))
})
