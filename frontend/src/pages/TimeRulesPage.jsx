import { useEffect, useState } from 'react'
import { createTimeRule, getTimeRules, updateTimeRule } from '../api.js'
import TimeRuleForm from '../components/TimeRuleForm.jsx'
import NaturalLanguageTimeRule from '../components/NaturalLanguageTimeRule.jsx'
import { WEEKDAYS } from '../constants.js'
import { RECURRENCE_LABELS } from '../localization.js'

function describeRule(rule) {
  return rule.recurrence === 'weekly' ? `每${WEEKDAYS[rule.weekday - 1]}` : rule.date
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

  async function applyProposal(data) {
    const created = await createTimeRule(data)
    setRules((current) => [...current, created].sort((a, b) => a.id - b.id))
  }

  function section(kind, heading, emptyText) {
    const items = rules.filter((rule) => rule.kind === kind)
    const selectedRule = form?.id === null ? null : items.find((rule) => rule.id === form?.id)
    return (
      <section className="rule-section" aria-label={heading}>
        <div className="list-heading"><h3>{heading}</h3><span className="count">{items.length}</span></div>
        {form?.kind === kind ? (
          <div className="panel">
            <h4>{form.id === null ? `添加${kind === 'course' ? '课程' : '保留时间'}` : '编辑时间规则'}</h4>
            <TimeRuleForm key={`${kind}-${form.id ?? 'new'}`} kind={kind} rule={selectedRule} pending={pending} onSubmit={save} onCancel={() => setForm(null)} />
          </div>
        ) : <button className="button primary add-button" type="button" disabled={pending} onClick={() => { setActionError(''); setForm({ kind, id: null }) }}>添加{kind === 'course' ? '课程' : '保留时间'}</button>}
        {items.length === 0 ? <p className="state-box">{emptyText}</p> : (
          <div className="card-list">
            {items.map((rule) => (
              <article key={rule.id} className={`item-card ${rule.active ? '' : 'inactive'}`}>
                <div className="item-top"><h4>{rule.title}</h4><span className={`badge ${rule.active ? 'status-active' : 'status-inactive'}`}>{rule.active ? '已启用' : '已停用'}</span></div>
                <dl className="details">
                  <div><dt>日期</dt><dd>{describeRule(rule)}</dd></div>
                  <div><dt>时间</dt><dd>{rule.start_time.slice(0, 5)}–{rule.end_time.slice(0, 5)} （北京时间）</dd></div>
                  <div><dt>重复方式</dt><dd>{RECURRENCE_LABELS[rule.recurrence]}</dd></div>
                </dl>
                <div className="button-row">
                  <button className="button subtle" type="button" disabled={pending} onClick={() => { setActionError(''); setForm({ kind, id: rule.id }) }}>编辑</button>
                  {rule.active && <button className="button subtle" type="button" disabled={pending} onClick={() => deactivate(rule)}>停用</button>}
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
      <div className="section-heading"><div><p className="eyebrow">我的固定安排</p><h2 id="rules-heading">课程与保留时间</h2></div></div>
      <p className="helper">日期和时间均按北京时间填写；已停用的规则仍保留在列表中。</p>
      {actionError && <p className="error-box" role="alert">{actionError}</p>}
      {loading ? <p className="state-box" role="status">正在加载时间规则…</p> : loadError ? (
        <div className="error-box" role="alert">无法加载时间规则。 {loadError} <button className="button subtle" onClick={load} type="button">重试</button></div>
      ) : <>
        <NaturalLanguageTimeRule onApply={applyProposal} manualPending={pending} />
        {section('course', '课程', '还没有课程，请先添加。')}
        {section('protected', '保留时间', '还没有保留时间，请先添加。')}
      </>}
    </section>
  )
}
