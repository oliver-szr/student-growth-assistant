import { useEffect, useRef, useState } from 'react'
import { createTaskBreakdown, getTaskBreakdowns, getTaskBreakdown, editTaskBreakdown, confirmTaskBreakdown, discardTaskBreakdown, getGoals } from '../api.js'
import { toBackendDeadline } from '../datetime.js'
import { breakdownPayload, breakdownTotals, editableContent, MAX_CHILDREN, moveChild } from '../taskHierarchy.js'

export function BreakdownEditor({ content, expected, disabled, onChange }) {
  const { total, difference } = breakdownTotals(content.children, expected)
  const parent = (field, value) => onChange({ ...content, parent: { ...content.parent, [field]: value } })
  const child = (index, field, value) => onChange({ ...content, children: content.children.map((item, i) => i === index ? { ...item, [field]: value } : item) })
  return <fieldset className="breakdown-fields" disabled={disabled}>
    <legend>审核拆解草案</legend>
    <div className="form-grid"><label>父任务标题<input required maxLength="200" value={content.parent.title} onChange={e => parent('title', e.target.value)} /></label><label>父任务截止时间<input type="datetime-local" required value={content.parent.deadline} onChange={e => parent('deadline', e.target.value)} /></label><label className="span-two">父任务说明<textarea maxLength="4000" value={content.parent.description || ''} onChange={e => parent('description', e.target.value)} /></label></div>
    <p className="breakdown-total" aria-live="polite">原始预期 {expected} 分钟 · 子任务合计 {total} 分钟{difference !== 0 && <strong> · 相差 {difference > 0 ? '+' : ''}{difference} 分钟，请核对</strong>}</p>
    <p className="helper">建议顺序仅供参考，排程不强制前后依赖。父任务只汇总进度，不占用日程。</p>
    {!content.children.length && <p className="state-box">还没有子任务，请至少添加一项后确认。</p>}
    <ol className="breakdown-children">{content.children.map((item, index) => <li key={index} className="item-card">
      <h5>子任务 {index + 1}</h5><div className="form-grid"><label>子任务标题<input aria-label={`子任务 ${index + 1} 标题`} required maxLength="200" value={item.title} onChange={e => child(index, 'title', e.target.value)} /></label><label>预计时长（分钟）<input aria-label={`子任务 ${index + 1} 预计分钟`} required type="number" min="5" max="10080" step="5" value={item.duration_minutes} onChange={e => child(index, 'duration_minutes', e.target.value)} /></label><label>建议截止时间<input aria-label={`子任务 ${index + 1} 截止时间`} type="datetime-local" required value={item.deadline} onChange={e => child(index, 'deadline', e.target.value)} /></label><label>说明<input maxLength="4000" value={item.description || ''} onChange={e => child(index, 'description', e.target.value)} /></label></div>
      <div className="button-row"><button type="button" className="button subtle" aria-label={`上移子任务 ${index + 1}`} disabled={index === 0} onClick={() => onChange({ ...content, children: moveChild(content.children, index, -1) })}>上移</button><button type="button" className="button subtle" aria-label={`下移子任务 ${index + 1}`} disabled={index === content.children.length - 1} onClick={() => onChange({ ...content, children: moveChild(content.children, index, 1) })}>下移</button><button type="button" className="button subtle" aria-label={`删除子任务 ${index + 1}`} onClick={() => onChange({ ...content, children: content.children.filter((_, i) => i !== index) })}>删除建议</button></div>
    </li>)}</ol>
    <button type="button" className="button secondary" disabled={content.children.length >= MAX_CHILDREN} onClick={() => onChange({ ...content, children: [...content.children, { title: '', description: null, duration_minutes: 30, deadline: content.parent.deadline, sort_order: content.children.length }] })}>增加手动子任务</button>
  </fieldset>
}

export default function TaskBreakdown({ onCreated }) {
  const [open, setOpen] = useState(false), [drafts, setDrafts] = useState([]), [goals, setGoals] = useState([])
  const [draft, setDraft] = useState(null), [content, setContent] = useState(null)
  const [pending, setPending] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [dirty, setDirty] = useState(false)
  const [form, setForm] = useState({ title: '', text: '', deadline: '', expected: '180', goal_id: '' })
  const requestKey = useRef(null), busy = useRef(false)

  async function reload() { const rows = await getTaskBreakdowns(); setDrafts(rows); return rows }
  function select(row) { setDraft(row); setContent(editableContent(row.content)); setDirty(false); setOpen(true); setError(''); setNotice('已读取服务器草案，刷新后可以继续。') }
  useEffect(() => { reload().catch(e => setError(e.message)); getGoals().then(data => setGoals(data.goals)).catch(e => setError(e.message)) }, [])

  async function act(action) {
    if (busy.current) return
    busy.current = true; setPending(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e.message) } finally { busy.current = false; setPending(false) }
  }
  async function persist() {
    if (!dirty) return draft
    const saved = await editTaskBreakdown(draft.id, { version: draft.version, content: breakdownPayload(content) })
    setDraft(saved); setDirty(false); setNotice('草案已保存，刷新后可以继续。'); return saved
  }
  function change(next) { setContent(next); setDirty(true); setError(''); setNotice('修改尚未保存') }
  // Only valid edits can be persisted. Failed saves retain the editor and offer retry.
  useEffect(() => {
    if (!dirty || pending || error || draft?.status !== 'ready') return
    const timer = setTimeout(() => act(persist), 1200)
    return () => clearTimeout(timer)
  }, [dirty, content, pending, error, draft?.id, draft?.version])

  async function generate(source) {
    requestKey.current ||= crypto.randomUUID()
    await act(async () => {
      const row = await createTaskBreakdown({ client_request_id: requestKey.current, source, text: form.text || form.title, title: form.title, deadline: toBackendDeadline(form.deadline), expected_duration_minutes: Number(form.expected), goal_id: form.goal_id ? Number(form.goal_id) : null })
      requestKey.current = null; select(row); await reload()
    })
  }
  function input(field, value) { requestKey.current = null; setForm({ ...form, [field]: value }) }
  async function adopt() {
    await act(async () => {
      const saved = await persist()
      const result = await confirmTaskBreakdown(saved.id, saved.version)
      setDraft(null); setContent(null); setDirty(false); await reload(); onCreated?.(result)
      setNotice(`已创建父任务和 ${result.created_task_ids.length - 1} 个子任务，可在下方任务与执行中查看并安排。`)
    })
  }
  async function cancel() {
    await act(async () => { await discardTaskBreakdown(draft.id, draft.version); setDraft(null); setContent(null); setDirty(false); await reload(); setNotice('拆解已取消，没有创建正式任务。') })
  }
  return <section className="task-breakdown panel" aria-labelledby="breakdown-heading">
    <div className="section-heading"><h3 id="breakdown-heading">复杂任务拆解</h3><button type="button" className="button secondary" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? '收起拆解' : 'AI 拆解任务 / 手动拆解'}</button></div>
    {error && <p className="error-box" role="alert">{error} <button type="button" disabled={pending} onClick={() => act(async () => { await reload(); if (draft) select(await getTaskBreakdown(draft.id)) })}>重新加载草案</button></p>}
    {notice && <p className="helper" role="status">{notice}</p>}
    {open && <>
      {drafts.length > 0 && <div className="breakdown-pending"><strong>待处理拆解草案</strong>{drafts.map(row => <button type="button" className="button subtle" disabled={pending || dirty} key={row.id} onClick={() => select(row)}>{row.content.parent.title} · {row.status === 'stale' ? '已过期，请取消后重建' : '继续编辑'}</button>)}</div>}
      {!draft ? <form onSubmit={e => { e.preventDefault(); generate('ai') }}><fieldset disabled={pending} className="breakdown-fields"><legend>输入复杂任务</legend><div className="form-grid"><label>任务名称<input required maxLength="200" value={form.title} onChange={e => input('title', e.target.value)} /></label><label>总体截止时间<input required type="datetime-local" value={form.deadline} onChange={e => input('deadline', e.target.value)} /></label><label>原始预期（分钟）<input required type="number" min="5" max="10080" step="5" value={form.expected} onChange={e => input('expected', e.target.value)} /></label><label>关联目标<select value={form.goal_id} onChange={e => input('goal_id', e.target.value)}><option value="">不关联</option>{goals.filter(g => g.status === 'active').map(g => <option key={g.id} value={g.id}>{g.title}</option>)}</select></label><label className="span-two">希望如何拆解（选填）<textarea maxLength="4000" value={form.text} onChange={e => input('text', e.target.value)} placeholder="例如：两周内完成 Software Engineering Project，包含需求、实现和测试" /></label></div><div className="button-row"><button type="submit" className="button primary">{pending ? '正在生成…' : 'AI 生成拆解草案'}</button><button type="button" className="button secondary" onClick={() => generate('manual')}>手动拆解（无需 AI）</button></div><p className="helper">AI 只生成建议。你审核确认后才创建任务，之后另行生成日程。</p></fieldset></form> : <form onSubmit={e => { e.preventDefault(); adopt() }}>
        <BreakdownEditor content={content} expected={draft.input.expected_duration_minutes} disabled={pending || draft.status !== 'ready'} onChange={change} />
        {draft.status === 'stale' && <p role="alert" className="error-box">任务、目标或计划已变化，或截止时间已过。请取消此草案，按最新资料重新生成。</p>}
        <div className="button-row"><button type="submit" className="button primary" disabled={pending || draft.status !== 'ready' || !content.children.length}>确认创建父子任务</button><button type="button" className="button secondary" disabled={pending || !dirty || draft.status !== 'ready'} onClick={() => act(persist)}>保存草案</button><button type="button" className="button subtle" disabled={pending} onClick={cancel}>取消拆解</button></div>
        <p className="helper">{dirty ? '有效修改会自动保存；若保存失败，请先修正或重试。' : '当前草案已保存。'}原始预期保留用于比较；只有你编辑的父任务截止时间会在确认后生效。</p>
      </form>}
    </>}
  </section>
}
