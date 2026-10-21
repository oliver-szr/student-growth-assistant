import test from 'node:test'
import assert from 'node:assert/strict'
import { nearBottom, reviewMetrics, progressPercent, initialWorkbench, workbenchReducer, workbenchVisibility, workbenchPanel, toolPlacement, defaultSplitRatio, clampSplitRatio, readSplitRatio, renderedSplitRatio, splitBounds } from '../src/workbench.js'
import { readFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
test('new messages must not displace a reader of history',()=>{assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:100}),false);assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:560}),true)})
test('missing facts stay unknown while confirmed zero remains zero',()=>{assert.deepEqual(reviewMetrics(null),[null,null,null]);assert.deepEqual(reviewMetrics({completed_count:0,confirmed_actual_minutes:90,planned_minutes:120}),[0,90,120])})
test('progress only renders from finite facts and keeps actual numbers separate',()=>{assert.equal(progressPercent(null,3),null);assert.equal(progressPercent(1,0),null);assert.equal(progressPercent(4,3),100);assert.equal(progressPercent(1,4),25)})

test('primary navigation and auxiliary tabs have independent states in both directions', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'auxiliary', page: 'profile' })
  assert.equal(state.navigation, 'home')
  assert.equal(state.auxiliaryPage, 'profile')
  state = workbenchReducer(state, { type: 'navigate', page: 'review' })
  assert.equal(state.navigation, 'review')
  assert.equal(state.auxiliaryPage, 'profile')
  state = workbenchReducer(state, { type: 'auxiliary', page: 'schedule' })
  assert.equal(state.navigation, 'review')
  assert.equal(state.auxiliaryPage, 'schedule')
  assert.equal(workbenchPanel(state), 'normal')
})

test('tool navigation uses the primary pane with unnecessary auxiliary surfaces collapsed', () => {
  for (const page of ['schedule', 'review', 'profile']) {
    const state = workbenchReducer(initialWorkbench, { type: 'navigate', page })
    assert.equal(toolPlacement(state, page), 'primary')
    assert.equal(workbenchPanel(state), 'collapsed')
    assert.deepEqual(workbenchVisibility(state, false), { conversations: false, primary: true, auxiliary: false })
    assert.equal(state.mobile, 'primary')
  }
})

test('returning home restores its independent panel, conversation and width preferences', () => {
  let state = { ...initialWorkbench, conversations: false, splitRatio: 0.66 }
  state = workbenchReducer(state, { type: 'auxiliary', page: 'profile' })
  state = workbenchReducer(state, { type: 'navigate', page: 'schedule' })
  state = workbenchReducer(state, { type: 'panel', value: 'expanded' })
  state = workbenchReducer(state, { type: 'navigate', page: 'home' })
  assert.equal(workbenchPanel(state), 'normal')
  assert.equal(state.auxiliaryPage, 'profile')
  assert.equal(state.conversations, false)
  assert.equal(state.splitRatio, 0.66)
  assert.equal(state.mobile, 'primary')
})

test('same tool selects a primary placement once without producing duplicate editing instances', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'profile' })
  for (let i = 0; i < 3; i++) state = workbenchReducer(state, { type: 'auxiliary', page: 'profile' })
  assert.equal(toolPlacement(state, 'profile'), 'primary')
  assert.deepEqual(state.visited, ['schedule', 'profile'])
  state = workbenchReducer(state, { type: 'navigate', page: 'home' })
  assert.equal(toolPlacement(state, 'profile'), 'auxiliary')
})

test('expanded auxiliary pane temporarily hides the conversation list without changing its preference', () => {
  for (const conversations of [false, true]) {
    const expanded = workbenchReducer({ ...initialWorkbench, conversations }, { type: 'panel', value: 'expanded' })
    assert.equal(workbenchVisibility(expanded, false).conversations, false)
    const restored = workbenchReducer(expanded, { type: 'panel', value: 'normal' })
    assert.equal(workbenchVisibility(restored, false).conversations, conversations)
    assert.equal(restored.navigation, 'home')
  }
})

test('mobile has exactly one surface and auxiliary switching cannot change the primary page', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'review' })
  for (const value of ['conversations', 'primary', 'auxiliary']) {
    state = workbenchReducer(state, { type: 'mobile', value })
    const visible = workbenchVisibility(state, true)
    assert.equal(Object.values(visible).filter(Boolean).length, 1)
    assert.equal(visible[value], true)
    assert.equal(state.navigation, 'review')
  }
  assert.equal(workbenchPanel(state), 'normal')
})

test('split width is bounded and restoring default changes no page or panel choice', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'auxiliary', page: 'profile' })
  state = workbenchReducer(state, { type: 'split', value: 2 })
  assert.equal(state.splitRatio, 0.75)
  state = workbenchReducer(state, { type: 'split', value: -1 })
  assert.equal(state.splitRatio, 0.35)
  state = workbenchReducer(state, { type: 'split', value: defaultSplitRatio })
  assert.equal(state.splitRatio, 0.58)
  assert.equal(state.auxiliaryPage, 'profile')
  assert.equal(state.navigation, 'home')
  assert.equal(workbenchPanel(state), 'normal')
})

test('resizing a smaller viewport keeps both minimum pane widths and retains the saved preference', () => {
  for (const available of [680, 748, 1004, 1164, 1700]) {
    for (const preferred of [0.35, defaultSplitRatio, 0.75]) {
      const actual = renderedSplitRatio(preferred, available)
      assert.ok(actual * available >= 360 - 0.001)
      assert.ok((1 - actual) * available >= 320 - 0.001)
      assert.ok(actual >= splitBounds(available).min && actual <= splitBounds(available).max)
    }
  }
  assert.equal(clampSplitRatio(NaN), defaultSplitRatio)
  assert.equal(clampSplitRatio(Infinity), defaultSplitRatio)
})

test('width preferences survive valid storage and tolerate missing, corrupt or unavailable storage', () => {
  for (const [raw, expected] of [['0.64', 0.64], ['2', 0.75], ['oops', 0.58], ['', 0.58], [null, 0.58]]) {
    assert.equal(readSplitRatio({ getItem: () => raw }), expected)
  }
  assert.equal(readSplitRatio({ getItem: () => { throw new Error('blocked') } }), 0.58)
})

test('unknown primary page, auxiliary page, size or mobile surface cannot corrupt state', () => {
  for (const action of [{ type: 'navigate', page: 'settings' }, { type: 'auxiliary', page: 'home' }, { type: 'panel', value: 'huge' }, { type: 'mobile', value: 'all' }, { type: 'unknown' }]) {
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

test('inactive tools remain mounted and primary calendar hides the chat and auxiliary controls', () => {
  const html = renderShell(workbenchReducer(initialWorkbench, { type: 'navigate', page: 'schedule' }))
  assert.match(html, /id="v2-chat"[^>]*hidden="" inert=""/)
  assert.match(html, /id="v2-page-schedule"[^>]*data-placement="primary"[^>]*role="main"/)
  assert.match(html, /id="v2-page-review"[^>]*hidden="" inert=""/)
  assert.match(html, /id="v2-page-profile"[^>]*hidden="" inert=""/)
  assert.ok(html.includes('恢复辅助栏'))
})

test('desktop home exposes a bounded keyboard accessible separator and reset action', () => {
  const html = renderShell(initialWorkbench)
  assert.match(html, /role="separator"[^>]*tabindex="0"[^>]*aria-orientation="vertical"/)
  assert.ok(html.includes('恢复默认宽度'))
  const tool = renderShell(workbenchReducer(initialWorkbench, { type: 'navigate', page: 'review' }))
  assert.match(tool, /class="v2-resizer"[^>]*hidden="" inert=""/)
})

test('a tool open in primary and auxiliary shows a reference instead of a second form', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'profile' })
  state = workbenchReducer(state, { type: 'auxiliary', page: 'profile' })
  const html = renderShell(state)
  assert.ok(html.includes('档案已在主体显示。'))
  assert.equal((html.match(/id="v2-page-profile"/g) || []).length, 1)
  assert.equal((html.match(/>PROFILE</g) || []).length, 1)
})
