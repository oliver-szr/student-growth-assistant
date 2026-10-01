import { useEffect, useState } from 'react'
import { createTimeRule, getTimeRules, updateTimeRule } from '../api.js'
import TimeRuleForm from '../components/TimeRuleForm.jsx'
import { WEEKDAYS } from '../constants.js'

function describeRule(rule) {
  return rule.recurrence === 'weekly' ? `Every ${WEEKDAYS[rule.weekday - 1]}` : rule.date
}

export default function TimeRulesPage() {
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [form, setForm] = useState(null)
  const [pending, setPending] = useState(false)

  async function load() {
    setLoading(true)
    setLoadError('')
    try {
      setRules(await getTimeRules())
    } catch (error) {
      setLoadError(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    getTimeRules()
      .then((items) => { if (active) setRules(items) })
      .catch((error) => { if (active) setLoadError(error.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  async function save(data) {
    if (pending) return
    setPending(true)
    setActionError('')
    try {
      if (form.id === null) {
        const created = await createTimeRule(data)
        setRules((current) => [...current, created].sort((a, b) => a.id - b.id))
      } else {
        const updated = await updateTimeRule(form.id, data)
        setRules((current) => current.map((item) => item.id === form.id ? updated : item))
      }
      setForm(null)
    } catch (error) {
      setActionError(error.message)
    } finally {
      setPending(false)
    }
  }

  async function deactivate(rule) {
    if (pending) return
    setPending(true)
    setActionError('')
    try {
      const updated = await updateTimeRule(rule.id, { active: false })
      setRules((current) => current.map((item) => item.id === rule.id ? updated : item))
    } catch (error) {
      setActionError(error.message)
    } finally {
      setPending(false)
    }
  }

  function section(kind, heading, emptyText) {
    const items = rules.filter((rule) => rule.kind === kind)
    const selectedRule = form?.id === null ? null : items.find((rule) => rule.id === form?.id)
    return (
      <section className="rule-section" aria-label={heading}>
        <div className="list-heading"><h3>{heading}</h3><span className="count">{items.length}</span></div>
        {form?.kind === kind ? (
          <div className="panel">
            <h4>{form.id === null ? `Add ${kind === 'course' ? 'a course' : 'protected time'}` : 'Edit time rule'}</h4>
            <TimeRuleForm key={`${kind}-${form.id ?? 'new'}`} kind={kind} rule={selectedRule} pending={pending} onSubmit={save} onCancel={() => setForm(null)} />
          </div>
        ) : <button className="button primary add-button" type="button" disabled={pending} onClick={() => { setActionError(''); setForm({ kind, id: null }) }}>Add {kind === 'course' ? 'course' : 'protected time'}</button>}
        {items.length === 0 ? <p className="state-box">{emptyText}</p> : (
          <div className="card-list">
            {items.map((rule) => (
              <article key={rule.id} className={`item-card ${rule.active ? '' : 'inactive'}`}>
                <div className="item-top"><h4>{rule.title}</h4><span className={`badge ${rule.active ? 'status-active' : 'status-inactive'}`}>{rule.active ? 'ACTIVE' : 'INACTIVE'}</span></div>
                <dl className="details">
                  <div><dt>When</dt><dd>{describeRule(rule)}</dd></div>
                  <div><dt>Time</dt><dd>{rule.start_time.slice(0, 5)}–{rule.end_time.slice(0, 5)} (Shanghai)</dd></div>
                  <div><dt>Repeats</dt><dd>{rule.recurrence}</dd></div>
                </dl>
                <div className="button-row">
                  <button className="button subtle" type="button" disabled={pending} onClick={() => { setActionError(''); setForm({ kind, id: rule.id }) }}>Edit</button>
                  {rule.active && <button className="button subtle" type="button" disabled={pending} onClick={() => deactivate(rule)}>Deactivate</button>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    )
  }

  return (
    <section aria-labelledby="rules-heading">
      <div className="section-heading"><div><p className="eyebrow">Your commitments</p><h2 id="rules-heading">Courses &amp; Protected Time</h2></div></div>
      <p className="helper">Times and dates describe Shanghai local time. Inactive items stay visible.</p>
      {actionError && <p className="error-box" role="alert">{actionError}</p>}
      {loading ? <p className="state-box" role="status">Loading time rules...</p> : loadError ? (
        <div className="error-box" role="alert">Could not load time rules. {loadError} <button className="button subtle" onClick={load} type="button">Retry</button></div>
      ) : <>
        {section('course', 'Courses', 'No courses yet.')}
        {section('protected', 'Protected Time', 'No protected time yet.')}
      </>}
    </section>
  )
}
