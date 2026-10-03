import { useEffect, useRef, useState } from 'react'
import { confirmPlan, createCandidatePlan, getConfirmedPlan, getTasks } from '../api.js'
import { currentShanghaiMonday, displayDeadline, mondayOfDate } from '../datetime.js'
import { sameTaskSelection } from '../planning.js'
import PlanPreview from '../components/PlanPreview.jsx'
import { PRIORITY_LABELS } from '../localization.js'

export default function WeeklyPlanPage({ active }) {
  const [weekStart, setWeekStart] = useState(currentShanghaiMonday)
  const [weekError, setWeekError] = useState('')
  const [tasks, setTasks] = useState([])
  const [selectedTaskIds, setSelectedTaskIds] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksError, setTasksError] = useState('')
  const [confirmedPlan, setConfirmedPlan] = useState(null)
  const [confirmedLoading, setConfirmedLoading] = useState(false)
  const [confirmedError, setConfirmedError] = useState('')
  const [candidatePlan, setCandidatePlan] = useState(null)
  const [outdated, setOutdated] = useState(false)
  const [confirmBlocked, setConfirmBlocked] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [generationError, setGenerationError] = useState(null)
  const [confirmError, setConfirmError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshVersion, setRefreshVersion] = useState(0)
  const operationPending = useRef(false)
  const busy = generating || confirming
  const selectionChanged = Boolean(candidatePlan) && !sameTaskSelection(selectedTaskIds, candidatePlan.task_ids)
  const todoTasks = tasks.filter((task) => task.status === 'todo')

  useEffect(() => {
    if (!active) return
    let current = true
    setTasksLoading(true)
    setTasksError('')
    getTasks()
      .then((items) => {
        if (!current) return
        setTasks(items)
        const todoIds = new Set(items.filter((task) => task.status === 'todo').map((task) => task.id))
        setSelectedTaskIds((ids) => ids.filter((id) => todoIds.has(id)))
      })
      .catch((error) => { if (current) setTasksError(error.message) })
      .finally(() => { if (current) setTasksLoading(false) })
    return () => { current = false }
  }, [active, refreshVersion])

  useEffect(() => {
    if (!active || !weekStart) return
    let current = true
    setConfirmedLoading(true)
    setConfirmedError('')
    getConfirmedPlan(weekStart)
      .then((plan) => { if (current) setConfirmedPlan(plan) })
      .catch((error) => {
        if (!current) return
        if (error.status === 404 && error.code === 'PLAN_NOT_FOUND') setConfirmedPlan(null)
        else setConfirmedError(error.message)
      })
      .finally(() => { if (current) setConfirmedLoading(false) })
    return () => { current = false }
  }, [active, weekStart, refreshVersion])

  function changeWeek(value) {
    if (operationPending.current) return
    let next = ''
    try {
      if (value) next = mondayOfDate(value)
      setWeekError(next ? '' : '请选择周日期。')
    } catch (error) {
      setWeekError(error.message)
    }
    if (next === weekStart) return
    setWeekStart(next)
    setSelectedTaskIds([])
    setCandidatePlan(null)
    setConfirmedPlan(null)
    setConfirmedError('')
    setConfirmedLoading(false)
    setOutdated(false)
    setConfirmBlocked(false)
    setGenerationError(null)
    setConfirmError('')
    setNotice('')
  }

  function selectTask(id, checked) {
    setSelectedTaskIds((ids) => checked ? [...ids, id] : ids.filter((selected) => selected !== id))
  }

  async function generate(event) {
    event.preventDefault()
    if (operationPending.current) return
    if (!weekStart) { setWeekError('请选择周日期。'); return }
    if (selectedTaskIds.length === 0) {
      setGenerationError({ message: '请至少选择一个任务。' })
      return
    }
    operationPending.current = true
    setGenerating(true)
    setGenerationError(null)
    setConfirmError('')
    setNotice('')
    try {
      const result = await createCandidatePlan({ week_start: weekStart, task_ids: selectedTaskIds })
      setCandidatePlan(result.candidate)
      setOutdated(false)
      setConfirmBlocked(false)
    } catch (error) {
      setGenerationError(error)
    } finally {
      operationPending.current = false
      setGenerating(false)
    }
  }

  async function confirm() {
    if (operationPending.current || !candidatePlan || outdated || confirmBlocked || selectionChanged) return
    operationPending.current = true
    setConfirming(true)
    setConfirmError('')
    setNotice('')
    try {
      const confirmed = await confirmPlan(candidatePlan.id)
      setConfirmedPlan(confirmed)
      setCandidatePlan(null)
      setOutdated(false)
      setConfirmBlocked(false)
      setGenerationError(null)
      setNotice(`计划 #${confirmed.id} 已确认为正式计划。`)
      // Reload official state; a failed reload retains the successful POST response.
      setRefreshVersion((version) => version + 1)
    } catch (error) {
      if (error.code === 'STALE_CANDIDATE') {
        setOutdated(true)
        setConfirmError('候选计划已过期：任务、时间规则或正式计划发生了变化。请重新生成后再确认。')
      } else {
        if (error.code === 'PLAN_NOT_CANDIDATE') setConfirmBlocked(true)
        setConfirmError(error.message)
      }
    } finally {
      operationPending.current = false
      setConfirming(false)
    }
  }

  const unscheduledTasks = generationError?.code === 'UNSCHEDULABLE' ? generationError.detail.unscheduled_tasks : []
  const canReload = !busy && !tasksLoading && !confirmedLoading

  return (
    <section aria-labelledby="weekly-plan-heading">
      <div className="section-heading">
        <div><p className="eyebrow">安排与确认</p><h2 id="weekly-plan-heading">周计划</h2></div>
        <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>重新加载任务和正式计划</button>
      </div>
      <form className="panel" onSubmit={generate}>
        <label className="week-selector">选择周日期
          <input type="date" value={weekStart} required disabled={busy} onChange={(event) => changeWeek(event.target.value)} />
        </label>
        <p className="helper">选择任意日期，将切换到该周的周一。所有时间按北京时间显示。</p>
        {weekStart && <h3>本周起始日：{weekStart}</h3>}
        {weekError && <p className="error-box" role="alert">{weekError}</p>}
        <h3>选择要安排的任务</h3>
        {tasksLoading && <p role="status">正在加载任务…</p>}
        {tasksError && <div className="error-box" role="alert">无法加载任务。 {tasksError} <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>重试</button></div>}
        {!tasksLoading && !tasksError && todoTasks.length === 0 && <p className="helper">没有待完成任务，请先在“任务”页面添加。</p>}
        <div className="task-selection">
          {todoTasks.map((task) => (
            <label className="task-option" key={task.id}>
              <input type="checkbox" checked={selectedTaskIds.includes(task.id)} disabled={busy || tasksLoading || Boolean(tasksError)} onChange={(event) => selectTask(task.id, event.target.checked)} />
              <span><strong>{task.title}</strong><span className="helper">{task.duration_minutes} 分钟 · {displayDeadline(task.deadline)} （北京时间） · 优先级：{PRIORITY_LABELS[task.priority]}</span></span>
            </label>
          ))}
        </div>
        <div className="button-row"><button className="button primary" type="submit" disabled={busy || tasksLoading || Boolean(tasksError) || !weekStart}>{generating ? '正在生成候选计划…' : '生成候选计划'}</button></div>
      </form>
      {generationError && <div className="error-box" role="alert">
        <p>{generationError.code === 'UNSCHEDULABLE' ? '当前排程规则未找到完整方案。请减少任务或调整截止时间、保留时间后重试。' : generationError.message}</p>
        {unscheduledTasks?.length > 0 && <ul>{unscheduledTasks.map((item) => <li key={item.task_id}><strong>{tasks.find((task) => task.id === item.task_id)?.title || `任务 #${item.task_id}`}</strong> （任务 #{item.task_id}）：未找到截止前的连续可用时段。</li>)}</ul>}
      </div>}
      {confirmError && <p className="error-box" role="alert">{confirmError}</p>}
      {notice && <p className="success-box" role="status">{notice}</p>}
      {generating && <p role="status">正在生成候选计划…</p>}
      {confirming && <p role="status">正在确认候选计划…</p>}
      {confirmedLoading && <p role="status">正在加载正式计划…</p>}
      {confirmedError && <div className="error-box" role="alert">无法加载正式计划。 {confirmedError} <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>重试</button></div>}
      <div className="plan-columns">
        <PlanPreview plan={confirmedPlan} emptyText={!weekStart ? '请选择周日期。' : confirmedLoading ? '正在加载正式计划…' : confirmedError ? '正式计划加载失败，请点击上方“重试”。' : '本周还没有正式计划。'} />
        <PlanPreview plan={candidatePlan} candidate outdated={outdated} blocked={confirmBlocked} selectionChanged={selectionChanged} busy={busy || confirmedLoading} onConfirm={confirm} />
      </div>
    </section>
  )
}
