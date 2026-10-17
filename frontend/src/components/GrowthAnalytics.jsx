import { useEffect, useState } from 'react'
import { getGrowthStatistics } from '../api.js'
import { chartBars, minutesText, percentText, signedText } from '../analytics.js'
import { progressPercent } from '../workbench.js'

export function WeeklyChart({ weekly, metric, title, unit }) {
  const bars = chartBars(weekly, metric)
  return <figure className="analytics-chart"><figcaption>{title}（{unit}）</figcaption>
    <svg viewBox="0 0 700 210" role="img" aria-labelledby={`analytics-${metric}-title`}>
      <title id={`analytics-${metric}-title`}>{title}，按北京时间周一开始；详细数据见下方表格</title>
      <line x1="32" x2="680" y1="160" y2="160" stroke="currentColor" opacity=".3" />
      {bars.map(({ row, value, x, width, height, incomplete }) => <g key={row.start_date} tabIndex="0" aria-label={`${row.start_date}周：${value === null ? '耗时未知或无反馈' : `${incomplete ? '已知至少' : ''}${value}${unit}`}${row.data_state === 'no_records' ? '，无安排或反馈记录' : ''}`}>
        <title>{row.start_date} 周 · {value === null ? '无完整耗时数据' : `${incomplete ? '已知 ' : ''}${value} ${unit}`} · {row.feedback_count} 条有效反馈，{row.unknown_actual_count} 条耗时缺失</title>
        {value !== null && <rect x={x} y={160 - height} width={width} height={height} rx="3" className={metric === 'completed_count' ? 'analytics-count-bar' : 'analytics-time-bar'} stroke={incomplete ? 'currentColor' : 'none'} strokeDasharray={incomplete ? '3 2' : undefined} />}
        <text x={x + width / 2} y={value === null ? 145 : Math.max(20, 151 - height)} textAnchor="middle" className="analytics-value">{value === null ? '—' : `${incomplete ? '≥' : ''}${value}`}</text>
        <text x={x + width / 2} y="185" textAnchor="middle">{row.start_date.slice(5)}</text>
      </g>)}
    </svg>
  </figure>
}

export function AnalyticsContent({ data, parentTasks = [] }) {
  const week = data.overview, estimate = data.estimation
  const cards = [
    ['计划任务', `${week.planned_task_count} 项`], ['确认完成', `${week.completed_count} 项`],
    ['当前已取消（全库）', `${data.current_cancelled_task_count} 项`], ['计划时间', `${week.planned_minutes} 分钟`],
    ['反馈实际投入', minutesText(week.actual_minutes, week.known_actual_minutes, week.unknown_actual_count)], ['历史完成率', '暂无可靠分母'],
  ]
  return <>
    <section className="growth-section" aria-label="成长统计概览">
      <h3>{week.start_date} 周概览</h3><div className="analytics-metrics">{cards.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
      <p className="helper">仅统计可执行任务。周取消事件数未知；“当前已取消”是查询时状态。完成率缺少固定周初任务集，不由当前状态反推。</p>
      {week.unknown_actual_count > 0 && <p className="analytics-note">本周 {week.unknown_actual_count} 条有效反馈未记录耗时，已知小计 {week.known_actual_minutes} 分钟；未知不等于0。</p>}
    </section>
    <section className="growth-section" aria-label="跨周成长趋势">
      <h3>最近 {data.weeks} 周趋势</h3><p className="helper">{data.start_date} 至 {data.end_date_exclusive}（结束日不含），北京时间。图表可横向滚动；“≥”表示仅有已知小计，“—”表示未知或无反馈。完整数据见表格。</p>
      {data.totals.data_state === 'no_records' && <p className="growth-empty">此范围没有可统计的安排或执行反馈。添加任务不会自动产生执行数据。</p>}
      <div className="analytics-charts"><WeeklyChart weekly={data.weekly} metric="completed_count" title="每周确认完成" unit="项" /><WeeklyChart weekly={data.weekly} metric="actual_minutes" title="每周反馈投入" unit="分钟" /></div>
      <details><summary>查看每周数据与缺失情况</summary><div className="analytics-table-wrap"><table><caption>每周真实记录（时间先后顺序）</caption><thead><tr><th>周一</th><th>计划任务</th><th>完成</th><th>计划分钟</th><th>实际投入</th><th>记录情况</th></tr></thead><tbody>{data.weekly.map(row => <tr key={row.start_date}><th scope="row">{row.start_date}</th><td>{row.planned_task_count}</td><td>{row.completed_count}</td><td>{row.planned_minutes}</td><td>{minutesText(row.actual_minutes, row.known_actual_minutes, row.unknown_actual_count)}</td><td>{row.data_state === 'no_records' ? '无安排/反馈记录' : `${row.feedback_count}条反馈，${row.unknown_actual_count}条缺耗时`}</td></tr>)}</tbody></table></div></details>
    </section>
    <section className="growth-section" aria-label="任务类别分布">
      <h3>类别投入 · 所选 {data.weeks} 周</h3><p className="helper">归属按反馈当时的类别标识，名称显示当前名称或历史快照。“占比”只比较已知分钟，未知部分不在分母。</p>
      {!data.categories.length ? <p className="growth-empty">暂无类别执行记录。</p> : <div className="analytics-table-wrap"><table><caption>类别投入与确认完成</caption><thead><tr><th>类别</th><th>实际投入</th><th>确认完成</th><th>占已知分钟</th></tr></thead><tbody>{data.categories.map(category => <tr key={category.key}><th scope="row">{category.name}</th><td>{minutesText(category.actual_minutes, category.known_actual_minutes, category.unknown_actual_count)}{category.unknown_actual_count > 0 && <small> · {category.unknown_actual_count}条缺耗时</small>}</td><td>{category.completed_count} 项</td><td>{percentText(category.known_time_share)}{category.known_time_share !== null && <progress max="100" value={category.known_time_share * 100} aria-label={`${category.name}占已知投入比例`} />}</td></tr>)}</tbody></table></div>}
    </section>
    <section className="growth-section" aria-label="估时偏差">
      <h3>原始估时与实际耗时</h3><p>有效配对 {estimate.sample_count} 项 · 原始预计 {estimate.estimated_minutes ?? '—'} 分钟 · 实际 {estimate.actual_minutes ?? '—'} 分钟 · 偏差 {signedText(estimate.difference_minutes)} 分钟（{percentText(estimate.deviation_ratio)}）</p>
      <p className="helper">仅比较已确认完成且全过程耗时完整的任务；实际包含更早周的有效投入。偏差比例 = 合计偏差 ÷ 原始估时合计，不用当前剩余时长。</p>
      {estimate.status === 'insufficient_data' && <p className="analytics-note">样本不足：至少 {estimate.minimum_samples} 项才描述类别规律；已有数值仅说明这些任务，不推断效率或未来趋势。</p>}
      {(estimate.excluded_unknown_time > 0 || estimate.excluded_incomparable_estimate > 0) && <p className="helper">已排除耗时不完整 {estimate.excluded_unknown_time} 项、原始估时不可比较 {estimate.excluded_incomparable_estimate} 项。</p>}
      {estimate.categories.length > 0 && <div className="analytics-table-wrap"><table><caption>各类别的可比较样本</caption><thead><tr><th>类别</th><th>有效样本</th><th>偏差分钟</th><th>偏差比例</th></tr></thead><tbody>{estimate.categories.map(category => <tr key={category.key}><th scope="row">{category.name}</th><td>{category.sample_count} 项{category.status === 'insufficient_data' ? '（样本不足）' : ''}</td><td>{signedText(category.difference_minutes)}</td><td>{percentText(category.deviation_ratio)}</td></tr>)}</tbody></table></div>}
      {estimate.categories.filter(category => category.observation).map(category => <p key={category.key} className="analytics-note">{category.name}：{category.observation}</p>)}
      {estimate.tasks.length > 0 && <details><summary>查看配对任务（最多 {estimate.task_detail_limit} 项，按超时分钟排序）</summary><div className="analytics-table-wrap"><table><caption>实际与原始估时对比</caption><thead><tr><th>任务</th><th>类别</th><th>原始分钟</th><th>实际分钟</th><th>差异分钟</th></tr></thead><tbody>{estimate.tasks.map(task => <tr key={task.task_id}><th scope="row">{task.title}</th><td>{task.category_name}</td><td>{task.estimated_minutes}</td><td>{task.actual_minutes}</td><td>{signedText(task.difference_minutes)}</td></tr>)}</tbody></table></div></details>}
    </section>
    <section className="growth-section" aria-label="长期目标实时进展">
      <h3>目标进展 · {week.start_date} 周</h3><p className="helper">次数/交付按完成子任务与普通任务ID计数；时间按有效反馈分钟。对照当前每周目标，不自动修改目标状态。</p>
      {!data.goals.length ? <p className="growth-empty">暂无目标。</p> : <div className="goal-list">{data.goals.map(goal => {
        const percent = progressPercent(goal.actual, goal.target)
        return <article className="goal-card" key={goal.goal_id}><div className="goal-card-top"><h4>{goal.goal_title}</h4><span className="badge">{goal.status === 'active' ? '进行中' : goal.status === 'paused' ? '已暂停' : goal.status === 'completed' ? '已完成' : '已归档'}</span></div>
          <p>本周确认进展：{goal.actual ?? '未知'} / {goal.target} {goal.unit_label}</p>
          {goal.actual === null && <p className="helper">已知小计 {goal.known_actual} 分钟，{goal.unknown_actual_count} 条缺耗时或尚无反馈；不能推断目标已达成。</p>}
          {percent !== null && <progress max="100" value={percent} aria-label={`${goal.goal_title}本周进展`} />}
          <p className="helper">当前关联 {goal.linked_task_count} 项可执行任务，其中已完成 {goal.linked_done_count} 项、已取消 {goal.linked_cancelled_count} 项；关联数不是周目标进度。</p>
        </article>
      })}</div>}
      {parentTasks.length > 0 && <details><summary>项目父容器当前进度</summary>{parentTasks.map(parent => <p key={parent.id}>{parent.title}：{parent.progress?.completed_children ?? 0} / {parent.progress?.total_children ?? 0} 项完成，{parent.progress?.cancelled_children ?? 0} 项取消</p>)}<p className="helper">沿用阶段2口径：已完成子任务 / 全部子任务，取消仍在分母。父容器不额外贡献工作量。</p></details>}
    </section>
    <details className="analytics-definitions"><summary>统计口径与数据质量</summary>{Object.entries(data.definitions).map(([key, definition]) => <p key={key}>{definition}</p>)}<p>已排除非法反馈 {data.excluded_invalid_feedback_count} 条；{data.legacy_completion_time_count} 条旧完成记录使用反馈发生时间归周。统计查询不调用AI，不改变任何正式数据。</p></details>
  </>
}

export function AnalyticsState({ loading, error, onRetry }) {
  if (loading) return <p role="status" className="state-box">正在汇总成长记录…</p>
  if (error) return <div role="alert" className="error-box">统计暂时无法加载：{error} <button type="button" className="button subtle" onClick={onRetry}>重试统计</button></div>
  return null
}

export default function GrowthAnalytics({ refreshVersion = 0, parentTasks = [], onRefresh }) {
  const [weeks, setWeeks] = useState(4), [data, setData] = useState(null), [loading, setLoading] = useState(true)
  const [error, setError] = useState(''), [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setData(null)
    getGrowthStatistics(weeks).then(result => { if (active) setData(result) }).catch(cause => { if (active) setError(cause.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [weeks, refreshVersion, retry])
  return <section className="growth-analytics" aria-labelledby="analytics-heading">
    <div className="growth-section-heading"><h3 id="analytics-heading">成长统计</h3><div className="analytics-controls"><label>统计范围<select value={weeks} onChange={event => setWeeks(Number(event.target.value))}>{[4, 8, 12].map(value => <option key={value} value={value}>最近 {value} 周</option>)}</select></label><button type="button" className="button subtle" disabled={loading} onClick={() => onRefresh ? onRefresh() : setRetry(value => value + 1)}>刷新统计</button></div></div>
    <AnalyticsState loading={loading || Boolean(data && data.weeks !== weeks)} error={error} onRetry={() => setRetry(value => value + 1)} />
    {!loading && data?.weeks === weeks && <AnalyticsContent data={data} parentTasks={parentTasks} />}
  </section>
}
