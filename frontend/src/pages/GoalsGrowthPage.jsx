import { useEffect, useMemo, useState } from 'react'
import {
  acceptGrowthInsight, analyzeGrowthInsights, createGrowthReview, editGrowthInsight, getDurationAdvice, getGoals, getGrowthAttention, getGrowthInsights,
  getGrowthReviews, getTaskCategories, getTaskGrowthContext, getTasks, ignoreGrowthInsight,
} from '../api.js'
import WorkspaceChat from '../components/WorkspaceChat.jsx'

const METRIC_LABELS = { time: '投入时间', count: '完成次数', deliverable: '明确交付' }
const PRIORITY_LABELS = { 1: '最优先', 2: '重要', 3: '保持推进' }

export default function ReviewPage({ onAdjustTask }) {
  const [goals, setGoals] = useState([])
  const [tasks, setTasks] = useState([])
  const [categories, setCategories] = useState([])
  const [contexts, setContexts] = useState({})
  const [suggestions, setSuggestions] = useState([])
  const [insights, setInsights] = useState([])
  const [analysisMessage, setAnalysisMessage] = useState('')
  const [weekStart, setWeekStart] = useState('')
  const [review, setReview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function refresh() {
    const [goalData, taskData, focusData, insightData, categoryData] = await Promise.all([
      getGoals(), getTasks(), getGrowthAttention(), getGrowthInsights(), getTaskCategories(),
    ])
    const reviewData = await getGrowthReviews(focusData.week_start)
    setGoals(goalData.goals)
    setCategories(categoryData.categories || [])
    setTasks(taskData.filter((item) => item.status === 'todo'))
    setWeekStart(focusData.week_start)
    setReview(reviewData.reviews[0] || null)
    setInsights(insightData.insights || [])
    const pairs = await Promise.all(taskData.filter((task) => task.status === 'todo').map(async (task) => [task.id, await getTaskGrowthContext(task.id)]))
    const contextByTask = Object.fromEntries(pairs)
    setContexts(contextByTask)
    const advice = await Promise.all(taskData.filter((task) => task.status === 'todo').map(async (task) => {
      const context = contextByTask[task.id] || {}
      return { task, context, advice: await getDurationAdvice(task.id) }
    }))
    setSuggestions(advice.filter((entry) => entry.advice.status === 'suggested'))
  }

  function afterChatDraftConfirmed(draft) {
    refresh().catch((cause) => setError(cause.message))
    if (draft?.operations?.some((operation) => operation.op === 'record_feedback')) {
      setNotice('执行记录已保存，正在按最新记录更新本周复盘…')
      createGrowthReview(weekStart).then((next) => {
        setReview(next)
        return refresh()
      }).then(() => setNotice('执行记录、目标进展和本周复盘已更新。')).catch((cause) => setError(cause.message))
    }
  }

  useEffect(() => { refresh().catch((e) => setError(e.message)) }, [])

  async function generateReview() {
    setBusy(true); setError(''); setNotice('')
    try { const next = await createGrowthReview(weekStart); setReview(next); setNotice('复盘已根据本周确认过的完成记录生成。') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function analyzeInsights() {
    setBusy(true); setError(''); setNotice(''); setAnalysisMessage('正在依据已确认的执行记录整理观察…')
    try { const result = await analyzeGrowthInsights(); setAnalysisMessage(result.message || ''); await refresh() }
    catch (e) { setError(e.message); setAnalysisMessage('') }
    finally { setBusy(false) }
  }

  async function reviewInsight(id, action) {
    setBusy(true); setError(''); setNotice('')
    try {
      if (action === 'accept') { await acceptGrowthInsight(id); setNotice('建议已采用并保存为长期偏好。') }
      else await ignoreGrowthInsight(id)
      await refresh()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function changeInsightWindow(id, timeWindow) {
    setBusy(true); setError('')
    try { await editGrowthInsight(id, timeWindow); await refresh() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const reviewProgress = useMemo(() => Object.fromEntries((review?.facts?.goal_progress || []).map((item) => [item.goal_id, item])), [review])
  const priorityText = (value) => PRIORITY_LABELS[value] || '重要'

  return <section className="growth-page" aria-labelledby="growth-heading">
    <div className="growth-page-heading">
      <div><p className="eyebrow">回看进展，调整下一步</p><h2 id="growth-heading">复盘</h2><p>目标由你设定；这里汇总目标进展、真实执行记录和可确认的成长建议。</p></div>
      <button className="button primary" type="button" disabled={busy} onClick={generateReview}>生成本周复盘</button>
    </div>
    <WorkspaceChat scope="review" weekStart={weekStart || undefined} onAdjustTask={onAdjustTask} onDraftConfirmed={afterChatDraftConfirmed} />
    {error && <p className="error-box" role="alert">{error}</p>}{notice && <p className="success-box" role="status">{notice}</p>}

    <section className="growth-section">
      <div className="growth-section-heading"><div><p className="eyebrow">持续行动</p><h3>目标进展</h3></div><span className="count">{goals.filter((g) => g.status === 'active').length} 项进行中</span></div>
      {!goals.length ? <p className="growth-empty">还没有目标。先写下你希望持续推进的一件事。</p> : <div className="goal-list">{goals.map((goal) => {
        const progress = reviewProgress[goal.id]
        return <article className={`goal-card ${goal.status !== 'active' ? 'goal-inactive' : ''}`} key={goal.id}>
          <div className="goal-card-top"><div><span className="goal-priority">{priorityText(goal.priority)}</span><h4>{goal.title}</h4></div><span className={`badge status-${goal.status === 'active' ? 'active' : 'inactive'}`}>{goal.status === 'active' ? '进行中' : goal.status === 'paused' ? '已暂停' : goal.status === 'completed' ? '已完成' : '已归档'}</span></div>
          {goal.motivation && <p>{goal.motivation}</p>}
          <div className="goal-metric"><span>{METRIC_LABELS[goal.metric_kind]}：每周 {goal.weekly_target} {goal.unit_label}</span><span>优先级版本 v{goal.version}</span>{goal.due_date && <span>目标日期：{goal.due_date}</span>}</div>
          {progress ? <p className="goal-progress">本周确认进展：<strong>{progress.actual} / {progress.target} {progress.unit_label}</strong>{progress.remaining ? `，还差 ${progress.remaining}` : '，已达到设定目标'}</p> : <p className="goal-progress muted">本周记录不足，完成后可在复盘中查看进展。</p>}
        </article>
      })}</div>}
    </section>

    <section className="growth-section">
      <div className="growth-section-heading"><div><p className="eyebrow">只根据真实反馈</p><h3>耗时建议</h3><p>建议来自近 28 天已确认的同类任务记录；采纳后仍需经规划助手生成候选方案。</p></div></div>
      {!suggestions.length ? <p className="growth-empty">目前没有满足样本要求的估时建议。完成任务时记录实际投入，之后这里会用有效记录估算。</p> : <div className="insight-list">{suggestions.map(({ task, context, advice }) => <article className="insight-card" key={task.id}><div><span className="insight-label">待你确认 · {categories.find((item) => item.key === context.family)?.name || context.family || '其他'}</span><h4>{task.title}</h4></div><p>最近 28 天有 <strong>{advice.evidence.sample_count} 项不同任务</strong>、分布在 {advice.evidence.active_days} 天的有效记录。</p><p>这次预计时长可以从 <strong>{advice.current_minutes} 分钟</strong>尝试调整为 <strong>{advice.suggested_minutes} 分钟</strong>。这是估计建议，不代表任务已完成。</p><button className="button secondary" disabled={busy} onClick={() => onAdjustTask?.({ taskId: task.id, title: task.title, durationMinutes: advice.suggested_minutes })}>让助手生成候选方案</button></article>)}</div>}
    </section>

    <section className="growth-section">
      <div className="growth-section-heading"><div><p className="eyebrow">计时记录形成的候选习惯</p><h3>AI 观察</h3><p>模型只整理程序统计出的记录规律；采用前不会影响长期偏好或日程。</p></div><button className="button secondary" disabled={busy} onClick={analyzeInsights}>分析我的记录</button></div>
      {analysisMessage && <p className="success-box" role="status">{analysisMessage}</p>}
      {!insights.some((item) => item.status === 'draft') ? <p className="growth-empty">当前没有待确认的习惯建议。需要同类任务有至少 5 条计时记录，并分布在 3 天以上。</p> : <div className="insight-list">{insights.filter((item) => item.status === 'draft').map((item) => {
        const window = item.proposed_rule?.start === '08:00' ? 'morning' : item.proposed_rule?.start === '12:00' ? 'afternoon' : 'evening'
        return <article className="insight-card" key={item.id}><span className="insight-label">AI 观察草案 · 待你确认</span><h4>{item.observation}</h4><p>{item.suggestion}</p><p className="insight-evidence">证据：{item.evidence.sample_count} 个不同任务，分布在 {item.evidence.active_days} 天。记录反映的是计时开始时间，不代表效率高低。</p><label>调整建议时段<select value={window} disabled={busy} onChange={(e) => changeInsightWindow(item.id, e.target.value)}><option value="morning">上午 08:00–12:00</option><option value="afternoon">下午 12:00–18:00</option><option value="evening">晚上 18:00–22:00</option></select></label><div className="button-row"><button className="button primary" disabled={busy} onClick={() => reviewInsight(item.id, 'accept')}>确认采用</button><button className="button subtle" disabled={busy} onClick={() => reviewInsight(item.id, 'ignore')}>暂不采用</button></div></article>
      })}</div>}
      {insights.some((item) => item.status !== 'draft') && <details className="insight-history"><summary>已处理的建议</summary>{insights.filter((item) => item.status !== 'draft').map((item) => <p key={item.id}>{item.status === 'accepted' ? '已采用' : '已忽略'}：{item.suggestion}</p>)}</details>}
    </section>

    <section className="growth-section">
      <div className="growth-section-heading"><div><p className="eyebrow">根据确认过的记录</p><h3>本周复盘</h3></div></div>
      {!review ? <p className="growth-empty">尚未生成本周复盘。系统不会把排进日程的任务自动算作完成。</p> : <div className="review-card"><h4>{review.facts.week_start} 这一周 · 复盘 v{review.version}</h4>{review.narrative && <p className="review-narrative">{review.narrative}</p>}<p>确认完成 <strong>{review.facts.completed_count}</strong> 项任务，确认投入 <strong>{review.facts.confirmed_actual_minutes}</strong> 分钟；已确认计划共 <strong>{review.facts.planned_minutes}</strong> 分钟。</p>{review.summary_mode === 'facts_only' && <p className="helper">AI 复盘暂不可用；上面的说明由程序按记录生成。</p>}<p className="helper">{review.facts.data_quality_note}</p>{review.facts.goal_progress?.map((item) => <p key={item.goal_id}>目标「{item.goal_title}」：{item.actual} / {item.target} {item.unit_label}</p>)}{review.facts.blockers?.length > 0 && <details><summary>查看记录过的阻碍</summary>{review.facts.blockers.map((item, index) => <p key={index}>{item.task_title}：{item.reason}</p>)}</details>}</div>}
    </section>
  </section>
}
