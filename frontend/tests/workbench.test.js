import test from 'node:test'
import assert from 'node:assert/strict'
import { nearBottom, reviewMetrics, progressPercent, initialWorkbench, workbenchReducer, workbenchVisibility, workbenchPanel, toolPlacement, defaultSplitRatio, clampSplitRatio, readSplitRatio, renderedSplitRatio, splitBounds, workspaceClock, shiftPreviewDate } from '../src/workbench.js'
import { readFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
import {recordedTime,tabKeyboard} from '../src/workbench.js'
test('unknown-only feedback is not displayed as zero, while a known zero stays a fact',()=>{
  assert.equal(recordedTime(0,1,1),'耗时未知')
  assert.equal(recordedTime(0,0,1),'0 分钟')
  assert.equal(recordedTime(0,0,0),'暂无投入记录')
  assert.equal(recordedTime(30,1,2),'30 分钟（另有未知耗时）')
})
test('tab arrow keys move and activate a single tab, with Home and End support',()=>{
  const active=[];const tabs=Array.from({length:3},(_,i)=>({focus:()=>active.push(`focus${i}`),click:()=>active.push(`select${i}`)}))
  const event={currentTarget:{querySelectorAll:()=>tabs},target:tabs[0],key:'ArrowLeft',preventDefault:()=>{}}
  tabKeyboard(event);assert.deepEqual(active,['focus2','select2'])
  event.key='Home';tabKeyboard(event);assert.equal(active.at(-1),'select0')
})
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

test('all primary pages share the same auxiliary tab, mode and width preference', () => {
  for (const panel of ['normal', 'collapsed', 'expanded']) {
    let state = { ...initialWorkbench, panel, auxiliaryPage: 'profile', splitRatio: 0.35, conversations: false }
    for (const page of ['schedule', 'review', 'profile', 'home']) {
      state = workbenchReducer(state, { type: 'navigate', page })
      assert.equal(state.navigation, page)
      assert.equal(state.auxiliaryPage, 'profile')
      assert.equal(workbenchPanel(state), panel)
      assert.equal(state.splitRatio, 0.35)
      assert.equal(state.conversations, false)
      assert.equal(state.mobile, 'primary')
    }
  }
})

test('collapsing the shared auxiliary pane gives primary tools the available space without changing their state', () => {
  let state = { ...initialWorkbench, auxiliaryPage: 'review', splitRatio: 0.64 }
  for (const page of ['schedule', 'review', 'profile']) {
    state = workbenchReducer(state, { type: 'navigate', page })
    state = workbenchReducer(state, { type: 'panel', value: 'collapsed' })
    assert.equal(toolPlacement(state, page), 'primary')
    assert.deepEqual(workbenchVisibility(state, false), { conversations: false, primary: true, auxiliary: false })
    state = workbenchReducer(state, { type: 'panel', value: 'normal' })
    assert.equal(workbenchVisibility(state, false).auxiliary, true)
    assert.equal(state.splitRatio, 0.64)
    assert.equal(state.auxiliaryPage, 'review')
  }
})

test('same tool keeps one primary controller when the auxiliary tab matches', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'profile' })
  for (let i = 0; i < 3; i++) state = workbenchReducer(state, { type: 'auxiliary', page: 'profile' })
  assert.equal(toolPlacement(state, 'profile'), 'primary')
  assert.deepEqual(state.visited, ['schedule', 'profile'])
  state = workbenchReducer(state, { type: 'navigate', page: 'home' })
  assert.equal(toolPlacement(state, 'profile'), 'hidden')
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
const renderShell = state => renderToStaticMarkup(React.createElement(WorkspaceShell, { state, dispatch: () => {}, conversationContent: 'REAL_CONVERSATION_LIST', chat: 'CHAT', review: 'REVIEW', profile: 'PROFILE', clock: '演示 · 2026-10-14 18:00 北京时间' }, 'SCHEDULE'))

test('shell exposes exactly three linked tabs, real current conversation and honest unavailable controls', () => {
  const html = renderShell(initialWorkbench)
  assert.equal((html.match(/role="tab"/g) || []).length, 3)
  assert.equal((html.match(/role="tab"[^>]*aria-controls="v2-auxiliary-shared"/g) || []).length, 3)
  assert.ok(html.includes('REAL_CONVERSATION_LIST'))
  assert.ok(!html.includes('新建、搜索与归档将在后续开放'))
  assert.ok(!html.includes('layout=legacy'))
  assert.ok(!html.includes('旧版入口'))
  assert.ok(!html.includes('搜索会话" disabled=""'))
  assert.ok(!html.includes('登录'))
})

test('primary calendar hides chat while keeping the common auxiliary controls', () => {
  const html = renderShell(workbenchReducer(initialWorkbench, { type: 'navigate', page: 'schedule' }))
  assert.match(html, /id="v2-chat"[^>]*hidden="" inert=""/)
  assert.match(html, /id="v2-page-schedule"[^>]*data-placement="primary"[^>]*role="main"/)
  assert.match(html, /id="v2-page-review"[^>]*hidden="" inert=""/)
  assert.match(html, /id="v2-page-profile"[^>]*hidden="" inert=""/)
  assert.ok(html.includes('恢复默认宽度'))
})

test('a draft is mounted once in the auxiliary pane while the primary page remains selected',()=>{
  for(const navigation of ['home','schedule','review','profile']){
    const state={...initialWorkbench,navigation,auxiliaryPage:'schedule'}
    const html=renderToStaticMarkup(React.createElement(WorkspaceShell,{state,dispatch:()=>{},draftPage:'schedule',draftPanel:'SHARED_DRAFT_EDITOR',auxiliarySchedule:'DAY_PREVIEW'},'FULL_CALENDAR'))
    const auxiliary=html.slice(html.indexOf('id="v2-auxiliary-shared"'))
    assert.ok(auxiliary.includes('SHARED_DRAFT_EDITOR'))
    assert.equal((html.match(/SHARED_DRAFT_EDITOR/g)||[]).length,1)
    assert.match(auxiliary, /id="v2-draft-preview" tabindex="-1">SHARED_DRAFT_EDITOR/)
    assert.match(auxiliary, /<div hidden="" inert="">DAY_PREVIEW/)
    assert.ok(html.includes(`data-navigation="${navigation}"`))
  }
})

test('each desktop primary page exposes the same accessible width separator and reset control', () => {
  for (const page of ['home', 'schedule', 'review', 'profile']) {
    const html = renderShell(workbenchReducer(initialWorkbench, { type: 'navigate', page }))
    assert.match(html, /class="v2-resizer" role="separator" tabindex="0" aria-label="调整主体与辅助栏宽度" aria-orientation="vertical"/)
    assert.ok(html.includes('恢复默认宽度'))
    assert.equal((html.match(/aria-label="辅助栏页签"/g) || []).length, 1)
  }
})

test('matching calendar renders a second data projection rather than a reference placeholder', () => {
  const state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'schedule' })
  const html = renderToStaticMarkup(React.createElement(WorkspaceShell, { state, dispatch: () => {}, chat: 'CHAT', auxiliarySchedule: 'SHARED_CALENDAR_DATA' }, 'FULL_CALENDAR'))
  assert.ok(html.includes('SHARED_CALENDAR_DATA'))
  assert.ok(html.includes('FULL_CALENDAR'))
  assert.ok(!html.includes('已在主体显示'))
  assert.match(html, /id="v2-auxiliary-shared"[^>]*data-placement="auxiliary"/)
})

test('matching profile keeps only one complete editing instance and a shared auxiliary host', () => {
  let state = workbenchReducer(initialWorkbench, { type: 'navigate', page: 'profile' })
  state = workbenchReducer(state, { type: 'auxiliary', page: 'profile' })
  const html = renderShell(state)
  assert.equal((html.match(/id="v2-page-profile"/g) || []).length, 1)
  assert.equal((html.match(/>PROFILE</g) || []).length, 1)
  assert.equal((html.match(/id="v2-auxiliary-shared"/g) || []).length, 1)
  assert.ok(!html.includes('在主体编辑档案'))
})

test('width edits on every primary page remain shared after navigation and safe storage recovery', () => {
  let state = initialWorkbench
  for (const [index, page] of ['home', 'schedule', 'review', 'profile'].entries()) {
    state = workbenchReducer(state, { type: 'navigate', page })
    const value = 0.40 + index * 0.05
    state = workbenchReducer(state, { type: 'split', value })
    for (const next of ['home', 'schedule', 'review', 'profile']) {
      state = workbenchReducer(state, { type: 'navigate', page: next })
      assert.equal(state.splitRatio, value)
    }
    const reloaded = { ...initialWorkbench, splitRatio: readSplitRatio({ getItem: () => String(value) }) }
    assert.equal(reloaded.splitRatio, value)
  }
})


test('every main page has its own full tool and an always minimal auxiliary host', () => {
  for (const navigation of ['home', 'schedule', 'review', 'profile']) {
    const state = { ...initialWorkbench, navigation, auxiliaryPage: 'schedule' }
    const html = renderToStaticMarkup(React.createElement(WorkspaceShell, { state, dispatch: () => {}, auxiliarySchedule: 'SINGLE_DAY_PREVIEW' }, 'FULL_WEEK_CALENDAR'))
    assert.match(html, /id="v2-auxiliary-shared"[^>]*role="tabpanel"[^>]*aria-labelledby="v2-tab-schedule">/)
    assert.ok(html.includes('SINGLE_DAY_PREVIEW'))
    for (const page of ['schedule', 'review', 'profile']) {
      assert.equal(toolPlacement(state, page), navigation === page ? 'primary' : 'hidden')
      assert.ok(!html.includes(`id="v2-page-${page}" class="v2-tool-page" data-placement="auxiliary"`))
    }
  }
})

test('four main headings share one clock and only the auxiliary header owns collapse controls', () => {
  for (const page of ['home', 'schedule', 'review', 'profile']) {
    const html = renderShell({ ...initialWorkbench, navigation: page })
    assert.equal((html.match(/演示 · 2026-10-14 18:00 北京时间/g) || []).length, 4)
    assert.equal((html.match(/aria-label="收起辅助栏"/g) || []).length, 1)
    for (const [heading] of html.matchAll(/<header class="v2-primary-page-heading">.*?<\/header>/g)) assert.ok(!heading.includes('<button'))
  }
})

test('workspace navigation uses consistent decorative SVGs and leaves one home heading', () => {
  const html = renderShell(initialWorkbench)
  const navigation = html.match(/<nav class="v2-navigation".*?<\/nav>/s)[0]
  assert.equal((navigation.match(/<svg /g) || []).length, 4)
  assert.equal((navigation.match(/aria-hidden="true"/g) || []).length, 4)
  assert.ok(!html.includes('class="eyebrow"'))
  assert.match(html, /<header class="v2-chat-heading"><h1>首页<\/h1>/)
  for (const label of ['首页', '日程', '复盘', '档案']) assert.ok(navigation.includes(label))
})

test('shared workspace clock advances server time in Shanghai without losing the demo prefix', () => {
  const settings = { demo: true, now: '2026-10-14T15:59:30Z' }
  assert.equal(workspaceClock(settings), '演示 · 2026-10-14 23:59 北京时间')
  assert.equal(workspaceClock(settings, 31000), '演示 · 2026-10-15 00:00 北京时间')
  assert.equal(workspaceClock({ ...settings, demo: false }, 91000), '2026-10-15 00:01 北京时间')
  assert.equal(workspaceClock(null), '')
  assert.equal(workspaceClock({ now: 'invalid' }), '')
})

test('preview date changes are bounded and handle month boundaries', () => {
  assert.equal(shiftPreviewDate('2026-10-14', 1, '2026-10-12', '2026-10-25'), '2026-10-15')
  assert.equal(shiftPreviewDate('2026-10-12', -1, '2026-10-12', '2026-10-25'), '2026-10-12')
  assert.equal(shiftPreviewDate('2026-10-25', 1, '2026-10-12', '2026-10-25'), '2026-10-25')
  assert.equal(shiftPreviewDate('2026-10-31', 1, '2026-10-26', '2026-11-08'), '2026-11-01')
  assert.equal(shiftPreviewDate('bad', 1, '2026-10-12', '2026-10-25'), 'bad')
})
