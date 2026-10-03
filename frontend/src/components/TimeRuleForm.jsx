import { useState } from 'react'
import { WEEKDAYS } from '../constants.js'
import { timeRuleFormPayload } from '../timeRules.js'

export default function TimeRuleForm({ kind, rule, pending, onSubmit, onCancel, submitLabel, cancelLabel = '取消' }) {
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
    onSubmit(timeRuleFormPayload({ kind, title, recurrence, weekday, date, startTime, endTime }, rule))
  }

  return (
    <form className="editor" onSubmit={submit}>
      <div className="form-grid">
        <label className="span-two">标题
          <input value={title} onChange={(event) => setTitle(event.target.value)} required disabled={pending} />
        </label>
        {kind === 'protected' && <label>重复方式
          <select value={recurrence} onChange={(event) => changeRecurrence(event.target.value)} disabled={pending}>
            <option value="weekly">每周</option>
            <option value="once">仅一次</option>
          </select>
        </label>}
        {recurrence === 'weekly' ? <label>星期
          <select value={weekday} onChange={(event) => setWeekday(event.target.value)} required disabled={pending}>
            <option value="">请选择星期</option>
            {WEEKDAYS.map((day, index) => <option value={index + 1} key={day}>{day}</option>)}
          </select>
        </label> : <label>日期
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required disabled={pending} />
        </label>}
        <label>开始时间
          <input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} required disabled={pending} />
        </label>
        <label>结束时间
          <input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} required disabled={pending} />
        </label>
      </div>
      <div className="button-row">
        <button className="button primary" type="submit" disabled={pending}>{pending ? '正在保存…' : submitLabel || (rule ? '保存修改' : `添加${kind === 'course' ? '课程' : '保留时间'}`)}</button>
        <button className="button subtle" type="button" onClick={onCancel} disabled={pending}>{cancelLabel}</button>
      </div>
    </form>
  )
}
