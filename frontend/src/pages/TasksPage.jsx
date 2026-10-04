import { useEffect, useRef, useState } from 'react'
import { STATUS_LABELS, PRIORITY_LABELS } from '../localization.js'
import {
  createTask, finishWorkSession, getCurrentWorkSession, getDurationAdvice,
  getTaskCategories, getTaskFeedback, getTaskGrowthContext, getTasks, pauseWorkSession,
  resumeWorkSession, saveTaskGrowthContext, startWorkSession, submitTaskFeedback,
  updateTask,
} from '../api.js'
import { displayDeadline } from '../datetime.js'
import TaskForm from '../components/TaskForm.jsx'

const freshFeedback = { outcome: 'completed', actual_minutes: '', remaining_minutes: '30', family: 'other', difficulty: 'expected', reason: '' }

function timerSeconds(session, now) {
  const base = session?.accumulated_seconds || 0
  return session?.status === 'running' && session.segment_started_at ? base + Math.max(0, Math.floor((now - Date.parse(session.segment_started_at)) / 1000)) : base
}

function formatTimer(total) {
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export default function TasksPage({ onAdjustTask }) {
  const [tasks, setTasks] = useState([])
  const [categories, setCategories] = useState([])
  const [contexts, setContexts] = useState({})
  const [sessions, setSessions] = useState({})
  const [feedbacks, setFeedbacks] = useState({})
  const [advice, setAdvice] = useState({})
  const [feedbackForms, setFeedbackForms] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [recordingId, setRecordingId] = useState(null)
  const [pending, setPending] = useState(false)
  const [formVersion, setFormVersion] = useState(0)
  const [tick, setTick] = useState(Date.now())
  const actionIds = useRef({})

  async function load() {
    setLoading(true); setLoadError('')
    try {
      const [items, categoryData] = await Promise.all([getTasks(), getTaskCategories()])
      setTasks(items)
      setCategories(categoryData.categories || [])
      const details = await Promise.all(items.map(async (task) => {
        const [context, work, history, estimate] = await Promise.all([
          getTaskGrowthContext(task.id), getCurrentWorkSession(task.id), getTaskFeedback(task.id), getDurationAdvice(task.id),
        ])
        return [task.id, { context, session: work.session, feedback: history.entries, advice: estimate }]
      }))
      const byId = Object.fromEntries(details)
      setContexts(Object.fromEntries(Object.entries(byId).map(([id, row]) => [id, row.context])))
      setSessions(Object.fromEntries(Object.entries(byId).filter(([, row]) => row.session).map(([id, row]) => [id, row.session])))
      setFeedbacks(Object.fromEntries(Object.entries(byId).map(([id, row]) => [id, row.feedback])))
      setAdvice(Object.fromEntries(Object.entries(byId).map(([id, row]) => [id, row.advice])))
    } catch (error) { setLoadError(error.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const timer = setInterval(() => setTick(Date.now()), 1000); return () => clearInterval(timer) }, [])

  async function save(data, id = null) {
    if (pending) return
    setPending(true); setActionError('')
    try {
      if (id === null) { await createTask(data); setFormVersion((value) => value + 1) }
      else { await updateTask(id, data); setEditingId(null) }
      await load()
    } catch (error) { setActionError(error.message) }
    finally { setPending(false) }
  }

  async function setStatus(task, status) {
    if (pending) return
    setPending(true); setActionError('')
    try { await updateTask(task.id, { status }); await load() }
    catch (error) { setActionError(error.message) }
    finally { setPending(false) }
  }

  function formFor(task) {
    return feedbackForms[task.id] || { ...freshFeedback, family: contexts[task.id]?.family || 'other' }
  }

  async function submitFeedback(task) {
    if (pending) return
    const form = formFor(task)
    const key = `${task.id}:${form.outcome}`
    actionIds.current[key] ||= crypto.randomUUID()
    const payload = { client_action_id: actionIds.current[key], outcome: form.outcome, family: form.family, difficulty: form.difficulty, reason: form.reason || undefined }
    if (form.actual_minutes) payload.actual_minutes = Number(form.actual_minutes)
    if (form.outcome === 'partial') payload.remaining_minutes = Number(form.remaining_minutes)
    setPending(true); setActionError('')
    try { await submitTaskFeedback(task.id, payload); delete actionIds.current[key]; setRecordingId(null); await load() }
    catch (error) { setActionError(error.message) }
    finally { setPending(false) }
  }

  async function timerAction(task, action) {
    if (pending) return
    setPending(true); setActionError('')
    try {
      let session = sessions[task.id]
      let result
      if (action === 'start') result = await startWorkSession({ task_id: task.id, client_action_id: crypto.randomUUID() })
      else if (action === 'pause') result = await pauseWorkSession(session.id)
      else if (action === 'resume') result = await resumeWorkSession(session.id)
      else result = await finishWorkSession(session.id)
      if (action === 'finish') {
        if (result.suggested_minutes > 0 && result.suggested_minutes <= 1440) setFeedbackForms((current) => ({ ...current, [task.id]: { ...formFor(task), actual_minutes: String(result.suggested_minutes) } }))
        setRecordingId(task.id)
      }
      await load()
    } catch (error) { setActionError(error.message) }
    finally { setPending(false) }
  }

  async function saveFamily(task, value) {
    const context = contexts[task.id] || {}
    setPending(true); setActionError('')
    try { await saveTaskGrowthContext(task.id, { family: value, goal_id: context.goal_id || null, deadline_source: context.deadline_source || 'external' }); await load() }
    catch (error) { setActionError(error.message) }
    finally { setPending(false) }
  }

  return (
    <section aria-labelledby="tasks-heading" className="task-execution-page">
      <div className="section-heading"><div><p className="eyebrow">真实执行会让建议越来越贴合你</p><h2 id="tasks-heading">任务与执行记录</h2></div></div>
      <div className="panel"><h3>添加任务</h3><p className="helper">截止时间按北京时间（UTC+08:00）填写和显示。</p><TaskForm key={formVersion} pending={pending} disabled={loading || Boolean(loadError)} onSubmit={(data) => save(data)} /></div>
      {actionError && <p className="error-box" role="alert">{actionError}</p>}
      {loading ? <p className="state-box" role="status">正在加载任务和执行历史…</p> : loadError ? <div className="error-box" role="alert">无法加载任务。 {loadError} <button className="button subtle" onClick={load} type="button">重试</button></div> : !tasks.length ? <p className="state-box">还没有任务，请先添加。</p> : <div className="card-list">
        {tasks.map((task) => {
          const context = contexts[task.id] || {}
          const session = sessions[task.id]
          const taskAdvice = advice[task.id]
          const form = formFor(task)
          return <article className="item-card task-execution-card" key={task.id}>
            <div className="item-top"><div><h4>{task.title}</h4><span className="task-context-label">{context.goal_id ? '已关联成长目标' : '未关联目标'}{context.family_confirmed ? ` · ${categories.find((item) => item.key === context.family)?.name || context.family}` : ' · 类型待确认'}</span></div><span className={`badge status-${task.status}`}>{STATUS_LABELS[task.status]}</span></div>
            {task.description && <p className="description">{task.description}</p>}
            <dl className="details"><div><dt>预计还需</dt><dd>{task.duration_minutes} 分钟</dd></div><div><dt>截止时间</dt><dd>{displayDeadline(task.deadline)}（北京时间）</dd></div><div><dt>重要程度</dt><dd>{PRIORITY_LABELS[task.priority]}</dd></div><div><dt>初始估时</dt><dd>{context.initial_estimate_minutes || task.duration_minutes} 分钟</dd></div></dl>
            {task.status === 'todo' && <>
              <div className="task-context-controls"><label>用于比较同类任务<select value={context.family || 'other'} disabled={pending} onChange={(e) => saveFamily(task, e.target.value)}>{categories.filter((item) => item.active || item.key === context.family).map((item) => <option key={item.key} value={item.key}>{item.name}{item.active ? '' : '（已停用）'}</option>)}</select></label><span>只有你确认的类型和实际耗时会进入学习统计。</span></div>
              {taskAdvice?.status === 'suggested' && <div className="duration-suggestion"><strong>估时建议：{taskAdvice.current_minutes} → {taskAdvice.suggested_minutes} 分钟</strong><p>来自 {taskAdvice.evidence.sample_count} 条不同任务、{taskAdvice.evidence.active_days} 个日期的有效记录；最多缩短 25%。</p><button className="button subtle" disabled={pending} onClick={() => onAdjustTask?.({ taskId: task.id, title: task.title, durationMinutes: taskAdvice.suggested_minutes })}>生成待确认方案</button></div>}
              <div className="work-timer-row">{session ? <><strong>{formatTimer(timerSeconds(session, tick))}</strong><span>{session.status === 'running' ? '正在计时' : session.status === 'paused' ? '已暂停' : '已结束，可手动记录'}</span>{session.status === 'running' && <button className="button subtle" disabled={pending} onClick={() => timerAction(task, 'pause')}>暂停</button>}{session.status === 'paused' && <button className="button subtle" disabled={pending} onClick={() => timerAction(task, 'resume')}>继续</button>}{session.status !== 'stopped' && <button className="button subtle" disabled={pending} onClick={() => timerAction(task, 'finish')}>结束计时并填写反馈</button>}</> : <button className="button subtle" disabled={pending} onClick={() => timerAction(task, 'start')}>可选：开始计时</button>}</div>
              <div className="button-row"><button className="button subtle" type="button" disabled={pending} onClick={() => { setActionError(''); setEditingId(task.id) }}>编辑任务</button><button className="button secondary" type="button" disabled={pending} onClick={() => setRecordingId(recordingId === task.id ? null : task.id)}>记录进度 / 完成</button><button className="button subtle" type="button" disabled={pending} onClick={() => setStatus(task, 'cancelled')}>取消任务</button></div>
              {recordingId === task.id && <form className="feedback-form" onSubmit={(event) => { event.preventDefault(); submitFeedback(task) }}><h5>保存本次执行情况</h5><label>本次结果<select value={form.outcome} onChange={(e) => setFeedbackForms((current) => ({ ...current, [task.id]: { ...form, outcome: e.target.value } }))}><option value="completed">完成</option><option value="partial">部分完成</option><option value="postponed">暂缓</option></select></label><label>实际投入分钟（可留空）<input type="number" min="1" max="1440" value={form.actual_minutes} onChange={(e) => setFeedbackForms((current) => ({ ...current, [task.id]: { ...form, actual_minutes: e.target.value } }))} /></label>{form.outcome === 'partial' && <label>预计还需要分钟<input type="number" min="30" max="1440" step="30" value={form.remaining_minutes} onChange={(e) => setFeedbackForms((current) => ({ ...current, [task.id]: { ...form, remaining_minutes: e.target.value } }))} /></label>}<label>难度感受<select value={form.difficulty} onChange={(e) => setFeedbackForms((current) => ({ ...current, [task.id]: { ...form, difficulty: e.target.value } }))}><option value="easy">比预期容易</option><option value="expected">和预期差不多</option><option value="hard">比预期困难</option></select></label><label>遇到什么情况（可选）<input maxLength="500" value={form.reason} onChange={(e) => setFeedbackForms((current) => ({ ...current, [task.id]: { ...form, reason: e.target.value } }))} placeholder="例如：临时被打断、工作量增加" /></label><p className="helper">计时器仅帮助填写耗时；本次反馈需你确认后保存。</p><div className="button-row"><button className="button primary" disabled={pending}>确认并保存反馈</button><button className="button subtle" type="button" onClick={() => setRecordingId(null)}>暂不记录</button></div></form>}
              {editingId === task.id && <TaskForm key={task.id} task={task} pending={pending} onSubmit={(data) => save(data, task.id)} onCancel={() => setEditingId(null)} />}
            </>}
            {feedbacks[task.id]?.length > 0 && <details className="feedback-history"><summary>执行记录（{feedbacks[task.id].length}）</summary>{feedbacks[task.id].map((row) => <p key={row.id}>{row.outcome === 'completed' ? '完成' : row.outcome === 'partial' ? '部分完成' : '暂缓'} · {row.actual_minutes ? `投入 ${row.actual_minutes} 分钟` : '未记录耗时'}{row.reason ? ` · ${row.reason}` : ''}{row.superseded ? '（已更正）' : ''}</p>)}</details>}
          </article>
        })}
      </div>}
    </section>
  )
}
