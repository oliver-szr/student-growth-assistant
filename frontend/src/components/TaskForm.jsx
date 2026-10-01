import { useState } from 'react'
import { toBackendDeadline, toDatetimeLocalValue } from '../datetime.js'

export default function TaskForm({ task, pending, disabled = false, onSubmit, onCancel }) {
  const [title, setTitle] = useState(task?.title ?? '')
  const [description, setDescription] = useState(task?.description ?? '')
  const [duration, setDuration] = useState(task?.duration_minutes ?? 30)
  const [deadline, setDeadline] = useState(toDatetimeLocalValue(task?.deadline))
  const [priority, setPriority] = useState(task?.priority ?? 'normal')
  const [formError, setFormError] = useState('')

  function submit(event) {
    event.preventDefault()
    if (pending || disabled) return
    setFormError('')
    try {
      onSubmit({
        title,
        description: description || null,
        duration_minutes: Number(duration),
        deadline: toBackendDeadline(deadline, task?.deadline),
        priority,
      })
    } catch (error) {
      setFormError(error.message)
    }
  }

  return (
    <form onSubmit={submit} className="editor">
      <div className="form-grid">
        <label className="span-two">Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label className="span-two">Description <span className="optional">optional</span>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows="2" disabled={pending || disabled} />
        </label>
        <label>Duration (minutes)
          <input type="number" min="30" step="30" value={duration} onChange={(event) => setDuration(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label>Deadline (Shanghai time)
          <input type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label>Priority
          <select value={priority} onChange={(event) => setPriority(event.target.value)} disabled={pending || disabled}>
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
          </select>
        </label>
      </div>
      {formError && <p className="error-box" role="alert">{formError}</p>}
      <div className="button-row">
        <button className="button primary" type="submit" disabled={pending || disabled}>{pending ? 'Saving...' : task ? 'Save task' : 'Create task'}</button>
        {onCancel && <button className="button subtle" type="button" onClick={onCancel} disabled={pending}>Cancel edit</button>}
      </div>
    </form>
  )
}
