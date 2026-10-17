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
        <label className="span-two">标题
          <input value={title} onChange={(event) => setTitle(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label className="span-two">说明 <span className="optional">选填</span>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows="2" disabled={pending || disabled} />
        </label>
        <label>{task?.task_kind === 'container' ? '原始预期（分钟，仅用于比较）' : '剩余时长（分钟）'}
          <input type="number" min="5" step="5" value={duration} onChange={(event) => setDuration(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label>截止时间
          <input type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required disabled={pending || disabled} />
        </label>
        <label>重要程度
          <select value={priority} onChange={(event) => setPriority(event.target.value)} disabled={pending || disabled}>
            <option value="low">低</option>
            <option value="normal">普通</option>
            <option value="high">高</option>
          </select>
        </label>
      </div>
      {formError && <p className="error-box" role="alert">{formError}</p>}
      <div className="button-row">
        <button className="button primary" type="submit" disabled={pending || disabled}>{pending ? '正在保存…' : task ? '保存任务' : '添加任务'}</button>
        {onCancel && <button className="button subtle" type="button" onClick={onCancel} disabled={pending}>取消</button>}
      </div>
    </form>
  )
}
