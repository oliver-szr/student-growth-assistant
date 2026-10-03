import { useEffect, useState } from 'react'
import { STATUS_LABELS, PRIORITY_LABELS } from '../localization.js'
import { createTask, getTasks, updateTask } from '../api.js'
import { displayDeadline } from '../datetime.js'
import TaskForm from '../components/TaskForm.jsx'

export default function TasksPage() {
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [pending, setPending] = useState(false)
  const [formVersion, setFormVersion] = useState(0)

  async function load() {
    setLoading(true)
    setLoadError('')
    try {
      setTasks(await getTasks())
    } catch (error) {
      setLoadError(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    getTasks()
      .then((items) => { if (active) setTasks(items) })
      .catch((error) => { if (active) setLoadError(error.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  async function save(data, id = null) {
    if (pending) return
    setPending(true)
    setActionError('')
    try {
      if (id === null) {
        const created = await createTask(data)
        setTasks((current) => [...current, created].sort((a, b) => a.id - b.id))
        setFormVersion((value) => value + 1)
      } else {
        const updated = await updateTask(id, data)
        setTasks((current) => current.map((item) => item.id === id ? updated : item))
        setEditingId(null)
      }
    } catch (error) {
      setActionError(error.message)
    } finally {
      setPending(false)
    }
  }

  async function setStatus(task, status) {
    if (pending) return
    setPending(true)
    setActionError('')
    try {
      const updated = await updateTask(task.id, { status })
      setTasks((current) => current.map((item) => item.id === task.id ? updated : item))
    } catch (error) {
      setActionError(error.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <section aria-labelledby="tasks-heading">
      <div className="section-heading"><div><p className="eyebrow">我的任务</p><h2 id="tasks-heading">任务</h2></div></div>
      <div className="panel">
        <h3>添加任务</h3>
        <p className="helper">截止时间按北京时间（UTC+08:00）填写和显示。</p>
        <TaskForm key={formVersion} pending={pending} disabled={loading || Boolean(loadError)} onSubmit={(data) => save(data)} />
      </div>
      {actionError && <p className="error-box" role="alert">{actionError}</p>}
      <div className="list-heading"><h3>全部任务</h3><span className="count">{tasks.length}</span></div>
      {loading ? <p className="state-box" role="status">正在加载任务…</p> : loadError ? (
        <div className="error-box" role="alert">无法加载任务。 {loadError} <button className="button subtle" onClick={load} type="button">重试</button></div>
      ) : tasks.length === 0 ? <p className="state-box">还没有任务，请先添加。</p> : (
        <div className="card-list">
          {tasks.map((task) => (
            <article className="item-card" key={task.id}>
              <div className="item-top"><h4>{task.title}</h4><span className={`badge status-${task.status}`}>{STATUS_LABELS[task.status]}</span></div>
              {task.description && <p className="description">{task.description}</p>}
              <dl className="details">
                <div><dt>预计时长</dt><dd>{task.duration_minutes} 分钟</dd></div>
                <div><dt>截止时间</dt><dd>{displayDeadline(task.deadline)} （北京时间）</dd></div>
                <div><dt>优先级</dt><dd>{PRIORITY_LABELS[task.priority]}</dd></div>
              </dl>
              {editingId === task.id ? (
                <TaskForm key={task.id} task={task} pending={pending} onSubmit={(data) => save(data, task.id)} onCancel={() => setEditingId(null)} />
              ) : task.status === 'todo' && (
                <div className="button-row">
                  <button className="button subtle" type="button" disabled={pending} onClick={() => { setActionError(''); setEditingId(task.id) }}>编辑</button>
                  <button className="button secondary" type="button" disabled={pending} onClick={() => setStatus(task, 'done')}>标记完成</button>
                  <button className="button subtle" type="button" disabled={pending} onClick={() => setStatus(task, 'cancelled')}>取消任务</button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
