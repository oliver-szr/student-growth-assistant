import { useEffect, useRef, useState } from 'react'
import { parseConstraint } from '../api.js'
import { parsingNotice, proposalDay, proposalToFormRule } from '../timeRules.js'
import TimeRuleForm from './TimeRuleForm.jsx'
import { RECURRENCE_LABELS } from '../localization.js'

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
      <h3 id="natural-language-heading">自然语言添加</h3>
      <p className="helper">描述一段课程或保留时间，AI 会生成提案，供你检查和修改。</p>
      <form onSubmit={parse}>
        <label htmlFor="constraint-text">描述你的时间安排</label>
        <textarea id="constraint-text" rows={3} maxLength={4000} value={text} disabled={parsing || saving}
          placeholder="每周三下午 2 点到 4 点是实验课。"
          onChange={(event) => { setText(event.target.value); setResult({ status: 'idle' }); setSaved(false); setApplyError('') }} />
        <div className="button-row"><button className="button secondary" type="submit" disabled={parsing || saving || !text.trim()}>{parsing ? '正在解析…' : '用 AI 解析'}</button></div>
      </form>
      <div aria-live="polite">
        {parsing && <p role="status">正在解析你的描述…</p>}
        {notice && <div className="state-box ai-result"><h4>{notice.heading}</h4><p>{notice.message}</p><p className="helper">修改或补充描述后重新解析。</p></div>}
        {result.status === 'error' && <div className="error-box ai-result" role="alert">AI 解析暂不可用，仍可在下方手动添加课程和保留时间。</div>}
        {saved && <p className="success-box">时间规则已添加，可在下方列表中查看。</p>}
      </div>
      {proposal && <div className="ai-result">
        <h4>AI 提案</h4>
        <p className="helper">请检查并修改下方内容；只有点击“应用时间规则”后才会保存。</p>
        <dl className="details">
          <div><dt>类型</dt><dd>{proposal.kind === 'course' ? '课程' : '保留时间'}</dd></div>
          <div><dt>标题</dt><dd>{proposal.title}</dd></div>
          <div><dt>重复方式</dt><dd>{RECURRENCE_LABELS[proposal.recurrence]}</dd></div>
          <div><dt>{proposal.recurrence === 'weekly' ? '星期' : '日期'}</dt><dd>{proposalDay(proposal)}</dd></div>
          <div><dt>开始时间</dt><dd>{proposal.start_time}</dd></div>
          <div><dt>结束时间</dt><dd>{proposal.end_time}</dd></div>
        </dl>
        {applyError && <p className="error-box" role="alert">{applyError}</p>}
        <TimeRuleForm key={proposalVersion} kind={proposal.kind} rule={proposal} pending={saving || manualPending}
          onSubmit={apply} onCancel={() => { setResult({ status: 'idle' }); setApplyError('') }}
          submitLabel="应用时间规则" cancelLabel="放弃提案" />
      </div>}
    </section>
  )
}
