import { useEffect, useRef, useState } from 'react'
import { confirmPlan, createCandidatePlan, getConfirmedPlan, getTasks } from '../api.js'
import { currentShanghaiMonday, displayDeadline, mondayOfDate } from '../datetime.js'
import { sameTaskSelection } from '../planning.js'
import PlanPreview from '../components/PlanPreview.jsx'

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
      setWeekError(next ? '' : 'Choose a week date.')
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
    if (!weekStart) { setWeekError('Choose a week date.'); return }
    if (selectedTaskIds.length === 0) {
      setGenerationError({ message: 'Select at least one task.' })
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
      setNotice(`Plan #${confirmed.id} confirmed.`)
      // Reload official state; a failed reload retains the successful POST response.
      setRefreshVersion((version) => version + 1)
    } catch (error) {
      if (error.code === 'STALE_CANDIDATE') {
        setOutdated(true)
        setConfirmError('STALE_CANDIDATE: This candidate is outdated because tasks, time rules, or confirmed plans changed. Generate a new candidate before confirming.')
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
        <div><p className="eyebrow">Plan and review</p><h2 id="weekly-plan-heading">Weekly Plan</h2></div>
        <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>Reload tasks &amp; confirmed plan</button>
      </div>
      <form className="panel" onSubmit={generate}>
        <label className="week-selector">Week date
          <input type="date" value={weekStart} required disabled={busy} onChange={(event) => changeWeek(event.target.value)} />
        </label>
        <p className="helper">Any date selects its Monday. Times are shown in Shanghai (UTC+08:00).</p>
        {weekStart && <h3>Week of {weekStart}</h3>}
        {weekError && <p className="error-box" role="alert">{weekError}</p>}
        <h3>Tasks to schedule</h3>
        {tasksLoading && <p role="status">Loading tasks...</p>}
        {tasksError && <div className="error-box" role="alert">Could not load tasks. {tasksError} <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>Retry</button></div>}
        {!tasksLoading && !tasksError && todoTasks.length === 0 && <p className="helper">No todo tasks. Add a task in Tasks to start planning.</p>}
        <div className="task-selection">
          {todoTasks.map((task) => (
            <label className="task-option" key={task.id}>
              <input type="checkbox" checked={selectedTaskIds.includes(task.id)} disabled={busy || tasksLoading || Boolean(tasksError)} onChange={(event) => selectTask(task.id, event.target.checked)} />
              <span><strong>{task.title}</strong><span className="helper">{task.duration_minutes} min · {displayDeadline(task.deadline)} (Shanghai) · {task.priority} priority</span></span>
            </label>
          ))}
        </div>
        <div className="button-row"><button className="button primary" type="submit" disabled={busy || tasksLoading || Boolean(tasksError) || !weekStart}>{generating ? 'Generating candidate...' : 'Generate Candidate'}</button></div>
      </form>
      {generationError && <div className="error-box" role="alert">
        <p>{generationError.code === 'UNSCHEDULABLE' ? 'UNSCHEDULABLE: Could not generate a complete plan under the current scheduling rules.' : generationError.message}</p>
        {unscheduledTasks?.length > 0 && <ul>{unscheduledTasks.map((item) => <li key={item.task_id}><strong>{tasks.find((task) => task.id === item.task_id)?.title || `Task #${item.task_id}`}</strong> (Task #{item.task_id}): {item.message || item.reason_code}</li>)}</ul>}
      </div>}
      {confirmError && <p className="error-box" role="alert">{confirmError}</p>}
      {notice && <p className="success-box" role="status">{notice}</p>}
      {generating && <p role="status">Generating candidate...</p>}
      {confirming && <p role="status">Confirming candidate...</p>}
      {confirmedLoading && <p role="status">Loading confirmed plan...</p>}
      {confirmedError && <div className="error-box" role="alert">Could not load confirmed plan. {confirmedError} <button className="button subtle" type="button" disabled={!canReload} onClick={() => setRefreshVersion((version) => version + 1)}>Retry</button></div>}
      <div className="plan-columns">
        <PlanPreview plan={confirmedPlan} emptyText={!weekStart ? 'Choose a week date.' : confirmedLoading ? 'Loading confirmed plan...' : confirmedError ? 'Confirmed plan could not be loaded. Retry above.' : 'No confirmed plan for this week.'} />
        <PlanPreview plan={candidatePlan} candidate outdated={outdated} blocked={confirmBlocked} selectionChanged={selectionChanged} busy={busy || confirmedLoading} onConfirm={confirm} />
      </div>
    </section>
  )
}
