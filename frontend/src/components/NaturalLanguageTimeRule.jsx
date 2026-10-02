import { useEffect, useRef, useState } from 'react'
import { parseConstraint } from '../api.js'
import { parsingNotice, proposalDay, proposalToFormRule } from '../timeRules.js'
import TimeRuleForm from './TimeRuleForm.jsx'

export default function NaturalLanguageTimeRule({ onApply, manualPending }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState({ status: 'idle' })
  const [proposalVersion, setProposalVersion] = useState(0)
  const [saving, setSaving] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [saved, setSaved] = useState(false)
  const busy = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  async function parse(event) {
    event.preventDefault()
    if (busy.current || !text.trim()) return
    busy.current = true
    setResult({ status: 'parsing' })
    setApplyError('')
    setSaved(false)
    try {
      const response = await parseConstraint(text.trim())
      if (mounted.current) {
        setResult(response)
        setProposalVersion((version) => version + 1)
      }
    } catch {
      if (mounted.current) setResult({ status: 'error' })
    } finally {
      busy.current = false
    }
  }

  async function apply(data) {
    if (busy.current || manualPending) return
    busy.current = true
    setSaving(true)
    setApplyError('')
    try {
      // The parent uses the same createTimeRule API as the manual form.
      await onApply(data)
      if (mounted.current) {
        setResult({ status: 'idle' })
        setSaved(true)
      }
    } catch (error) {
      if (mounted.current) setApplyError(error.message)
    } finally {
      busy.current = false
      if (mounted.current) setSaving(false)
    }
  }

  const parsing = result.status === 'parsing'
  const notice = parsingNotice(result)
  const proposal = result.status === 'parsed' ? proposalToFormRule(result.proposal) : null

  return (
    <section className="panel" aria-labelledby="natural-language-heading">
      <h3 id="natural-language-heading">Natural Language</h3>
      <p className="helper">Describe one course or protected interval. AI proposes a rule for you to review.</p>
      <form onSubmit={parse}>
        <label htmlFor="constraint-text">Describe your time rule</label>
        <textarea id="constraint-text" rows={3} maxLength={4000} value={text} disabled={parsing || saving}
          placeholder="Every Wednesday 2pm to 4pm is lab time."
          onChange={(event) => { setText(event.target.value); setResult({ status: 'idle' }); setSaved(false); setApplyError('') }} />
        <div className="button-row"><button className="button secondary" type="submit" disabled={parsing || saving || !text.trim()}>{parsing ? 'Parsing...' : 'Parse with AI'}</button></div>
      </form>
      <div aria-live="polite">
        {parsing && <p role="status">Parsing your description...</p>}
        {notice && <div className="state-box ai-result"><h4>{notice.heading}</h4><p>{notice.message}</p><p className="helper">Edit the description and parse again.</p></div>}
        {result.status === 'error' && <div className="error-box ai-result" role="alert">AI parsing is temporarily unavailable. Manual TimeRule creation remains available.</div>}
        {saved && <p className="success-box">Time rule applied. It is now visible in the list.</p>}
      </div>
      {proposal && <div className="ai-result">
        <h4>AI Proposal</h4>
        <p className="helper">Review before applying. You can edit the fields below. Nothing is saved until you click Apply time rule.</p>
        <dl className="details">
          <div><dt>Type</dt><dd>{proposal.kind === 'course' ? 'Course' : 'Protected time'}</dd></div>
          <div><dt>Title</dt><dd>{proposal.title}</dd></div>
          <div><dt>Recurrence</dt><dd>{proposal.recurrence}</dd></div>
          <div><dt>{proposal.recurrence === 'weekly' ? 'Weekday' : 'Date'}</dt><dd>{proposalDay(proposal)}</dd></div>
          <div><dt>Start</dt><dd>{proposal.start_time}</dd></div>
          <div><dt>End</dt><dd>{proposal.end_time}</dd></div>
        </dl>
        {applyError && <p className="error-box" role="alert">{applyError}</p>}
        <TimeRuleForm key={proposalVersion} kind={proposal.kind} rule={proposal} pending={saving || manualPending}
          onSubmit={apply} onCancel={() => { setResult({ status: 'idle' }); setApplyError('') }}
          submitLabel="Apply time rule" cancelLabel="Discard" />
      </div>}
    </section>
  )
}
