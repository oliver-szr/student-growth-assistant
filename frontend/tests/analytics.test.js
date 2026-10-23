import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithEsbuild } from 'vite'
import { chartBars, minutesText, percentText, signedText } from '../src/analytics.js'
import { getGrowthStatistics } from '../src/api.js'

const path = new URL('../src/components/GrowthAnalytics.jsx', import.meta.url)
const source = await readFile(path, 'utf8')
const imports = source.replace(/from '(\.\.\/[^']+)'/g, (_, relative) => `from '${new URL(relative, path).href}'`).replace("from 'react'", `from '${import.meta.resolve('react')}'`)
const compiled = await transformWithEsbuild(`import React from '${import.meta.resolve('react')}';\n${imports}`, 'GrowthAnalytics.jsx', { jsx: 'transform', jsxFactory: 'React.createElement' })
const { default: GrowthAnalytics, AnalyticsContent, AnalyticsState, WeeklyChart } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`)
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props))
const week = { start_date: '2026-12-28', end_date_exclusive: '2027-01-04', planned_task_count: 2, planned_minutes: 120, completed_count: 1, partial_task_count: 0, feedback_count: 1, known_actual_minutes: 90, actual_minutes: 90, unknown_actual_count: 0, completion_rate: null, cancelled_event_count: null, data_state: 'complete' }
const estimation = { sample_count: 1, minimum_samples: 3, status: 'insufficient_data', estimated_minutes: 60, actual_minutes: 90, difference_minutes: 30, deviation_ratio: .5, overrun_count: 1, completed_candidates: 1, excluded_unknown_time: 0, excluded_incomparable_estimate: 0, categories: [], tasks: [], task_detail_limit: 20 }
const data = { weeks: 4, start_date: '2026-12-07', end_date_exclusive: '2027-01-04', overview: week, totals: week, weekly: [week], categories: [{ key: 'custom-1', name: '自定义工程', completed_count: 1, feedback_count: 1, known_actual_minutes: 90, actual_minutes: 90, unknown_actual_count: 0, known_time_share: 1 }], estimation, goals: [], current_cancelled_task_count: 1, excluded_invalid_feedback_count: 0, legacy_completion_time_count: 0, definitions: { effort: '不重复累计计时器' } }

test('overview, trends and category tables render API values with units and explicit limits', () => {
  const html = render(AnalyticsContent, { data })
  for (const text of ['计划任务', '2 项', '确认完成', '1 项', '120 分钟', '90 分钟', '当前已取消（全库）', '暂无可靠分母', '最近 4 周趋势', '自定义工程', '100.0%', '北京时间', '结束日不含', '每周真实记录', '不重复累计计时器']) assert.ok(html.includes(text), text)
  assert.ok(html.includes('<svg'))
  assert.ok(html.includes('<caption>类别投入与确认完成</caption>'))
})

test('unknown, partial coverage and legitimate zero never share the same display', () => {
  assert.equal(minutesText(0), '0 分钟')
  assert.equal(minutesText(null, 0, 1), '耗时未知')
  assert.equal(minutesText(null), '尚无反馈')
  assert.equal(minutesText(null, 30, 1), '已知 30 分钟（不完整）')
  const changed = { ...data, overview: { ...week, actual_minutes: null, unknown_actual_count: 1, known_actual_minutes: 30 } }
  const html = render(AnalyticsContent, { data: changed })
  assert.ok(html.includes('未知不等于0'))
  assert.ok(html.includes('已知 30 分钟（不完整）'))
})

test('no history and insufficient paired samples show explicit empty and evidence states', () => {
  const empty = { ...week, completed_count: 0, feedback_count: 0, planned_task_count: 0, actual_minutes: null, known_actual_minutes: 0, planned_minutes: 0, data_state: 'no_records' }
  const html = render(AnalyticsContent, { data: { ...data, overview: empty, totals: empty, weekly: [empty], categories: [] } })
  for (const text of ['没有可统计的安排或执行反馈', '暂无类别执行记录', '样本不足', '至少 3 项', '不推断效率或未来趋势']) assert.ok(html.includes(text), text)
})

test('estimation uses supplied paired task facts and signed weighted deviation', () => {
  const task = { task_id: 4, title: '子任务实现', category_name: '工程', estimated_minutes: 90, actual_minutes: 110, difference_minutes: 20 }
  const html = render(AnalyticsContent, { data: { ...data, estimation: { ...estimation, estimated_minutes: 90, actual_minutes: 110, difference_minutes: 20, deviation_ratio: 20 / 90, tasks: [task], excluded_unknown_time: 2 } } })
  for (const text of ['子任务实现', '+20 分钟', '22.2%', '全过程耗时完整', '包含更早周', '合计偏差 ÷ 原始估时合计', '耗时不完整 2 项', '最多 20 项']) assert.ok(html.includes(text), text)
  assert.equal(signedText(0), '0'); assert.equal(signedText(-5), '-5'); assert.equal(signedText(null), '—')
  assert.equal(percentText(null), '—')
})

test('goals distinguish minutes from counts and preserve cancelled children in parent denominator', () => {
  const goals = [{ goal_id: 1, goal_title: '每周项目交付', metric_kind: 'deliverable', actual: 1, known_actual: 1, target: 3, unit_label: '项', status: 'active', linked_task_count: 3, linked_done_count: 1, linked_cancelled_count: 1 }, { goal_id: 2, goal_title: '阅读时间', metric_kind: 'time', actual: null, known_actual: 40, unknown_actual_count: 1, target: 120, unit_label: '分钟', status: 'active', linked_task_count: 1, linked_done_count: 0, linked_cancelled_count: 0 }]
  const parentTasks = [{ id: 9, title: '项目容器', progress: { completed_children: 1, total_children: 3, cancelled_children: 1 } }]
  const html = render(AnalyticsContent, { data: { ...data, goals }, parentTasks })
  for (const text of ['1 / 3 项', '未知 / 120 分钟', '已知小计 40 分钟', '项目容器', '取消仍在分母', '父容器不额外贡献工作量']) assert.ok(html.includes(text), text)
  assert.equal((html.match(/aria-label="阅读时间本周进展"/g) || []).length, 0)
})

test('loading and server failure have distinct accessible states and retry action', () => {
  assert.ok(render(AnalyticsState, { loading: true }).includes('role="status"'))
  const error = render(AnalyticsState, { loading: false, error: '无法连接后端', onRetry: () => {} })
  assert.ok(error.includes('role="alert"') && error.includes('重试统计') && error.includes('无法连接后端'))
})

test('range selector exposes 4/8/12 weeks without triggering AI', () => {
  const html = render(GrowthAnalytics, {})
  for (const weeks of [4, 8, 12]) assert.ok(html.includes(`最近 ${weeks} 周`))
  assert.ok(html.includes('刷新统计') && html.includes('正在汇总成长记录'))
  assert.ok(!html.includes('生成复盘'))
})

test('range API sends bounded query fields through shared request wrapper', async context => {
  const urls = []
  context.mock.method(globalThis, 'fetch', async url => { urls.push(url); return new Response(JSON.stringify(data)) })
  await getGrowthStatistics(); await getGrowthStatistics(8); await getGrowthStatistics(12, '2026-12-28')
  assert.deepEqual(urls.map(url => new URL(url).search), ['?weeks=4', '?weeks=8', '?weeks=12&end_week=2026-12-28'])
  assert.ok(urls.every(url => new URL(url).pathname === '/api/growth/statistics'))
})

test('invalid ranges and backend failure retain readable feedback', async context => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: { code: 'INVALID_STATISTICS_RANGE' } }), { status: 422 }))
  await assert.rejects(() => getGrowthStatistics(6), e => e.code === 'INVALID_STATISTICS_RANGE' && e.message.includes('周一'))
  context.mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline') })
  await assert.rejects(() => getGrowthStatistics(), /无法连接后端/)
})

test('chart gaps, zero and incomplete known effort are truthful and keyboard accessible', () => {
  const unknown = { ...week, start_date: '2027-01-04', actual_minutes: null, known_actual_minutes: 0, unknown_actual_count: 1 }
  const partial = { ...unknown, start_date: '2027-01-11', known_actual_minutes: 30 }
  const bars = chartBars([week, unknown, partial, { ...week, actual_minutes: 0 }], 'actual_minutes')
  assert.deepEqual(bars.map(bar => bar.value), [90, null, 30, 0])
  const html = render(WeeklyChart, { weekly: [week, unknown, partial], metric: 'actual_minutes', title: '实际投入', unit: '分钟' })
  for (const text of ['role="img"', 'tabindex="0"', '<title>', '≥30', '—', '2027-01-04', 'stroke-dasharray="3 2"']) assert.ok(html.includes(text), text)
})

test('chart calendar labels and values remain identical in different browser timezones', () => {
  const script = `import {chartBars} from '${new URL('../src/analytics.js', import.meta.url).href}';console.log(JSON.stringify(chartBars(${JSON.stringify([week])},'completed_count')))`
  const outputs = ['UTC', 'Asia/Shanghai', 'America/Los_Angeles'].map(TZ => {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { env: { ...process.env, TZ }, encoding: 'utf8' })
    assert.equal(result.status, 0, result.stderr)
    return result.stdout
  })
  assert.equal(outputs[0], outputs[1]); assert.equal(outputs[1], outputs[2])
})
