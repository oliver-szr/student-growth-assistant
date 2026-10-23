import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  getReviewFacts, getReviewContext, acceptGrowthInsight, analyzeGrowthInsights,
  createGrowthReview, editGrowthInsight, ignoreGrowthInsight,
} from '../api.js'
import ReviewWorkspace from '../components/ReviewWorkspace.jsx'
import GrowthAnalytics from '../components/GrowthAnalytics.jsx'
import '../analytics.css'
import SafeMessage from '../components/SafeMessage.jsx'
import { reviewRange } from '../calendar.js'


export default function ReviewPage({ onAdjustTask, active = true, refreshVersion = 0, auxiliaryTarget = null, onDataChanged, onBusinessChat, onReturnChat, workspace, today, onDiscuss, resource, onOpenTask, primaryActive=active }) {
  const [statisticsMounted,setStatisticsMounted]=useState(false)
  const [parentTasks, setParentTasks] = useState([])
  const [analyticsVersion, setAnalyticsVersion] = useState(0)
  const [overview, setOverview] = useState(null)
  const [auxFacts,setAuxFacts]=useState(null)
  const [overviewError, setOverviewError] = useState('')
  const [categories, setCategories] = useState([])
  const [insufficient,setInsufficient]=useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [insights, setInsights] = useState([])
  const [analysisMessage, setAnalysisMessage] = useState('')
  const [weekStart, setWeekStart] = useState('')
  const [review, setReview] = useState(null)
  const [operation,setOperation]=useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(()=>{
    if(!auxiliaryTarget||!today)return
    let valid=true;const [start,end]=reviewRange(today,'week')
    getReviewFacts(start,end).then(value=>{if(valid){setAuxFacts(value);setOverviewError('')}}).catch(cause=>{if(valid)setOverviewError(cause.message)})
    return()=>{valid=false}
  },[auxiliaryTarget,today,refreshVersion])
  async function refresh() {
    const snapshot=await getReviewContext()
    setCategories(snapshot.categories);setParentTasks(snapshot.tasks.filter(task=>task.task_kind==='container'));setAnalyticsVersion(value=>value+1)
    setWeekStart(snapshot.week_start);setReview(snapshot.reviews[0]||null);setInsights(snapshot.insights)
    setInsufficient(Object.values(snapshot.advice).some(item=>item.status==='insufficient_data'||item.status==='needs_task_type'))
    setSuggestions(snapshot.tasks.filter(task=>task.status==='todo').map(task=>({task,context:snapshot.contexts[task.id],advice:snapshot.advice[task.id]})).filter(entry=>entry.advice.status==='suggested'))

  }

  useEffect(() => { if (active&&statisticsMounted) refresh().catch((e) => setError(e.message)) }, [active, refreshVersion,statisticsMounted])

  async function generateReview() {
    setOperation('review'); setBusy(true); setError(''); setNotice('')
    try { const next = await createGrowthReview(weekStart); setReview(next); setNotice('复盘已根据本周确认过的完成记录生成。'); onDataChanged?.() }
    catch (e) { setError(e.message) } finally { setBusy(false);setOperation('') }
  }

  async function analyzeInsights() {
    setOperation('analysis'); setBusy(true); setError(''); setNotice(''); setAnalysisMessage('')
    try { const result = await analyzeGrowthInsights(); setAnalysisMessage(result.message || ''); await refresh() }
    catch (e) { setError(e.message); setAnalysisMessage('') }
    finally { setBusy(false);setOperation('') }
  }

  async function reviewInsight(id, action) {
    setBusy(true); setError(''); setNotice('')
    try {
      if (action === 'accept') { await acceptGrowthInsight(id); setNotice('建议已采用并保存为长期偏好。') }
      else await ignoreGrowthInsight(id)
      await refresh()
      onDataChanged?.()
    } catch (e) { setError(e.message) } finally { setBusy(false);setOperation('') }
  }

  async function changeInsightWindow(id, timeWindow) {
    setBusy(true); setError('')
    try { await editGrowthInsight(id, timeWindow); await refresh() }
    catch (e) { setError(e.message) } finally { setBusy(false);setOperation('') }
  }

  return <><section className="growth-page" aria-label="回顾与成长">
    {onReturnChat&&<button className="button subtle" onClick={onReturnChat}>返回相关对话</button>}
    {today&&<ReviewWorkspace workspace={workspace} today={today} active={primaryActive} refreshVersion={refreshVersion} onDiscuss={onDiscuss} onSaved={onDataChanged} resource={resource} onOpenTask={onOpenTask}/>}
    <details className="review-statistics" onToggle={e=>{if(e.currentTarget.open)setStatisticsMounted(true)}}><summary>统计与习惯建议</summary>{statisticsMounted&&<>
    <div className="growth-page-heading">
      <div><h2 id="growth-heading">复盘</h2></div><span className="review-week muted">{weekStart} 周</span>
      <button className="button primary" type="button" disabled={busy} onClick={generateReview}>{operation==='review'?'生成中…':'生成复盘'}</button>{onBusinessChat&&<button className="button secondary" onClick={onBusinessChat}>用 AI 整理执行记录</button>}
    </div>
    {error && <p className="error-box" role="alert">{error}</p>}{notice && <p className="success-box" role="status">{notice}</p>}

    <GrowthAnalytics refreshVersion={analyticsVersion} parentTasks={parentTasks} onOverview={setOverview} onOverviewError={setOverviewError} onRefresh={()=>refresh().catch(cause=>setError(cause.message))} />
    <section className="growth-section">
      <div className="growth-section-heading"><div><h3>保存的周复盘说明</h3></div></div>
      <p className="helper">以下是已保存的复盘版本；上方图表基于当前有效记录。更正反馈后可重新生成复盘说明。</p>
      {!review ? <p className="growth-empty">尚未生成复盘。</p> : <div className="review-card">{review.narrative && <div className="review-narrative"><SafeMessage text={review.narrative}/></div>}{review.summary_mode === 'facts_only' && <p className="helper">AI 暂不可用，已显示记录摘要。</p>}<details><summary>分析依据</summary><p>{review.facts.data_quality_note}</p><p>复盘 v{review.version}</p></details>{review.facts.blockers?.length > 0 && <details><summary>查看记录过的阻碍</summary>{review.facts.blockers.map((item, index) => <p key={index}>{item.task_title}：{item.reason}</p>)}</details>}</div>}
    </section>
    <section className="growth-section">
      <div className="growth-section-heading"><div><h3>待确认建议</h3><h4>耗时建议</h4></div></div>{insufficient && <div className="muted">记录不足。<details><summary>分析依据</summary>同类任务至少 5 项，分布在至少 3 天；仅使用已确认的有效执行记录。</details></div>}
      {!suggestions.length ? <p className="growth-empty">暂无建议。</p> : <div className="insight-list">{suggestions.map(({ task, context, advice }) => <article className="insight-card" key={task.id}><div><span className="insight-label">待你确认 · {categories.find((item) => item.key === context.family)?.name || context.family || '其他'}</span><h4>{task.title}</h4></div><details><summary>分析依据</summary><p>最近 28 天有 <strong>{advice.evidence.sample_count} 项不同任务</strong>、分布在 {advice.evidence.active_days} 天的有效记录。</p></details><p><strong>{advice.current_minutes} → {advice.suggested_minutes} 分钟</strong></p><button className="button secondary" disabled={busy} onClick={() => onAdjustTask?.({ taskId: task.id, title: task.title, durationMinutes: advice.suggested_minutes })}>调整安排</button></article>)}</div>}
      <div className="growth-section-heading"><div><h3>习惯建议</h3></div><button className="button secondary" disabled={busy} onClick={analyzeInsights}>{operation==='analysis'?'分析中…':'分析记录'}</button></div>
      {analysisMessage && <p className="success-box" role="status">{analysisMessage}</p>}
      {!insights.some((item) => item.status === 'draft') ? <p className="growth-empty">暂无建议。</p> : <div className="insight-list">{insights.filter((item) => item.status === 'draft').map((item) => {
        const window = item.proposed_rule?.start === '08:00' ? 'morning' : item.proposed_rule?.start === '12:00' ? 'afternoon' : 'evening'
        return <article className="insight-card" key={item.id}><span className="insight-label">AI 观察草案 · 待你确认</span><h4>{item.observation}</h4><p>{item.suggestion}</p><details><summary>分析依据</summary><p className="insight-evidence">证据：{item.evidence.sample_count} 个不同任务，分布在 {item.evidence.active_days} 天。记录反映的是计时开始时间，不代表效率高低。</p></details><label>调整建议时段<select value={window} disabled={busy} onChange={(e) => changeInsightWindow(item.id, e.target.value)}><option value="morning">上午 08:00–12:00</option><option value="afternoon">下午 12:00–18:00</option><option value="evening">晚上 18:00–22:00</option></select></label><div className="button-row"><button className="button primary" disabled={busy} onClick={() => reviewInsight(item.id, 'accept')}>确认采用</button><button className="button subtle" disabled={busy} onClick={() => reviewInsight(item.id, 'ignore')}>暂不采用</button></div></article>
      })}</div>}
      {insights.some((item) => item.status !== 'draft') && <details className="insight-history"><summary>已处理的建议</summary>{insights.filter((item) => item.status !== 'draft').map((item) => <p key={item.id}>{item.status === 'accepted' ? '已采用' : '已忽略'}：{item.suggestion}</p>)}</details>}
    </section>


    </>}
    </details>
  </section>
    {auxiliaryTarget && createPortal(<section className="v2-readonly-summary" aria-label="复盘辅助视图">
      <h3>本周回顾</h3>
      {overviewError && <p role="status">摘要暂时无法更新{overview ? '，以下为上次读取的记录。' : '。'}</p>}
      {auxFacts ? <><p className="muted">{auxFacts.start_date} 起的一周</p><dl>
        <div><dt>已确认完成</dt><dd>{auxFacts.completed_count} 项</dd></div>
        <div><dt>已记录投入</dt><dd>{`${auxFacts.known_minutes} 分钟${auxFacts.unknown_count?'（另有未知）':''}`}</dd></div>
        <div><dt>有效反馈</dt><dd>{auxFacts.feedback_ids.length} 条</dd></div>
      </dl></> : !overviewError && <p role="status">正在读取本周记录…</p>}
    </section>, auxiliaryTarget)}
  </>
}
