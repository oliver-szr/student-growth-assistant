import { useState } from 'react'
import { WEEKDAYS } from '../constants.js'

export default function TimeRuleForm({ kind, rule, pending, onSubmit, onCancel }) {
  const [title, setTitle] = useState(rule?.title ?? '')
  const [recurrence, setRecurrence] = useState(kind === 'course' ? 'weekly' : rule?.recurrence ?? 'weekly')
  const [weekday, setWeekday] = useState(rule?.weekday?.toString() ?? '')
  const [date, setDate] = useState(rule?.date ?? '')
  const [startTime, setStartTime] = useState(rule?.start_time?.slice(0, 5) ?? '')
  const [endTime, setEndTime] = useState(rule?.end_time?.slice(0, 5) ?? '')

  function changeRecurrence(value) {
    setRecurrence(value)
    setWeekday('')
    setDate('')
  }

  function submit(event) {
    event.preventDefault()
    if (pending) return
    onSubmit({
      kind,
      title,
      recurrence: kind === 'course' ? 'weekly' : recurrence,
      weekday: recurrence === 'weekly' ? Number(weekday) : null,
      date: recurrence === 'once' ? date : null,
      start_time: rule && startTime === rule.start_time.slice(0, 5) ? rule.start_time : startTime,
      end_time: rule && endTime === rule.end_time.slice(0, 5) ? rule.end_time : endTime,
    })
  }

  return (
    <form className="editor" onSubmit={submit}>
      <div className="form-grid">
        <label className="span-two">Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} required disabled={pending} />
        </label>
        {kind === 'protected' && <label>Repeats
          <select value={recurrence} onChange={(event) => changeRecurrence(event.target.value)} disabled={pending}>
            <option value="weekly">Every week</option>
            <option value="once">Once</option>
          </select>
        </label>}
        {recurrence === 'weekly' ? <label>Weekday
          <select value={weekday} onChange={(event) => setWeekday(event.target.value)} required disabled={pending}>
            <option value="">Choose a day</option>
            {WEEKDAYS.map((day, index) => <option value={index + 1} key={day}>{day}</option>)}
          </select>
        </label> : <label>Date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required disabled={pending} />
        </label>}
        <label>Start time
          <input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} required disabled={pending} />
        </label>
        <label>End time
          <input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} required disabled={pending} />
        </label>
      </div>
      <div className="button-row">
        <button className="button primary" type="submit" disabled={pending}>{pending ? 'Saving...' : rule ? 'Save changes' : `Create ${kind === 'course' ? 'course' : 'protected time'}`}</button>
        <button className="button subtle" type="button" onClick={onCancel} disabled={pending}>Cancel</button>
      </div>
    </form>
  )
}
