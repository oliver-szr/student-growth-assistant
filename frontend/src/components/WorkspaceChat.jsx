import { useEffect, useRef, useState } from 'react'
import { cancelAssistantRun, confirmGrowthDraft, createAssistantRun, discardGrowthDraft, getAssistantRun, getAssistantSession, getAssistantSettings, openWorkspaceSession, retryAssistantRun } from '../api.js'
import SafeMessage from './SafeMessage.jsx'

const labels = { profile: '档案助手', review: '复盘助手' }

export default function WorkspaceChat({ scope, weekStart, onAdjustTask, onDraftConfirmed }) {
  const [session, setSession] = useState(null)
  const [data, setData] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [run, setRun] = useState(null)
  const [confirmedDraft, setConfirmedDraft] = useState(null)
  const [workspaceId, setWorkspaceId] = useState('')
  const active = useRef(true)
  const requestId = useRef(null)
  useEffect(() => { if (workspaceId) localStorage.setItem(`growth-workspace-input-${workspaceId}-${scope}`, text) }, [workspaceId, scope, text])

  async function refresh(id) {
    const result = await getAssistantSession(id)
    setData(result)
    const current = result.runs?.find((item) => item.status === 'running')
    if (current) { setRun(current); setBusy(true); poll(current.id, id) }
    return result
  }

  useEffect(() => {
    active.current = true
    Promise.all([getAssistantSettings(), openWorkspaceSession(scope, weekStart)]).then(async ([settings, opened]) => {
      if (!active.current) return
      setWorkspaceId(settings.workspace_id)
      const savedInput = localStorage.getItem(`growth-workspace-input-${settings.workspace_id}-${scope}`)
      if (savedInput) setText(savedInput)
      sessionStorage.setItem(`growth-workspace-${settings.workspace_id}-${scope}-${opened.week_start}`, String(opened.id))
      setSession(opened)
      await refresh(opened.id)
    }).catch((cause) => active.current && setError(cause.message))
    return () => { active.current = false }
  }, [scope, weekStart])

  async function poll(runId, sessionId = session?.id) {
    try {
      let result = await getAssistantRun(runId)
      while (result.status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 800))
        result = await getAssistantRun(runId)
      }
      if (!active.current) return result
      setRun(result)
      if (result.status === 'failed') setError(result.error_code === 'AI_UNAVAILABLE' ? 'AI 暂时不可用，输入已保留；可以重试或稍后再试。' : '本轮没有完成，输入已保留。请检查资料或重试。')
      if (result.status === 'completed' && sessionId) await refreshMessages(sessionId)
      setBusy(false)
      return result
    } catch (cause) {
      if (active.current) { setBusy(false); setError(cause.message) }
      return null
    }
  }

  async function refreshMessages(id) {
    const result = await getAssistantSession(id)
    if (active.current) setData(result)
  }

  async function send(event) {
    event.preventDefault()
    if (!session || !text.trim() || busy) return
    const message = text.trim()
    requestId.current ||= crypto.randomUUID()
    setError(''); setBusy(true); setConfirmedDraft(null); setRun({ status: 'running', phase: 'understanding' })
    try {
      const started = await createAssistantRun(session.id, { client_message_id: requestId.current, text: message })
      setRun(started)
      const result = await poll(started.id, session.id)
      if (result?.status === 'completed') { setText(''); requestId.current = null }
    } catch (cause) { setError(cause.message); setBusy(false) }
  }

  async function cancel() {
    if (!run?.id) return
    try { const next = await cancelAssistantRun(run.id); setRun(next); setBusy(false) }
    catch (cause) { setError(cause.message) }
  }

  async function retry() {
    if (!run?.id) return
    setBusy(true); setError('')
    try { const next = await retryAssistantRun(run.id); setRun(next); await poll(next.id, session.id) }
    catch (cause) { setBusy(false); setError(cause.message) }
  }

  async function act(action) {
    if (!session || busy) return false
    setBusy(true); setError('')
    try { await action(); await refreshMessages(session.id); return true }
    catch (cause) { setError(cause.message); return false }
    finally { setBusy(false) }
  }

  async function confirmDraft() {
    if (!data?.draft) return
    const draft = data.draft
    const saved = await act(() => confirmGrowthDraft(draft.id))
    if (saved) {
      setConfirmedDraft(draft)
      setError('')
      await onDraftConfirmed?.(draft)
    }
  }

  const placeholder = scope === 'profile'
    ? '例如：新增编程类别，编程尽量安排在下午；阅读目标改成每周两篇。'
    : '例如：报告今天完成了，实际用了90分钟；阅读因为临时开会暂缓。'
  const phaseText = run?.phase === 'understanding' ? '正在理解你的表达…' : run?.phase === 'arranging' ? '正在核对资料和生成修改草案…' : run?.phase === 'recommending' ? '正在整理回复…' : '正在处理…'

  return <section className="workspace-chat" aria-label={`${labels[scope]}聊天`}>
    <div className="workspace-chat-heading"><div><p className="eyebrow">独立对话 · 修改先预览</p><h3>{labels[scope]}</h3></div><span className="version-pill">{scope === 'profile' ? '长期档案' : `${weekStart || data?.week_start || ''} 周`}</span></div>
    <div className="workspace-chat-messages" aria-live="polite">
      {!data?.messages?.length && <p className="growth-empty">{placeholder}<br />AI 会先确认理解；涉及档案或执行记录的修改，需要你确认后才保存。</p>}
      {data?.messages?.map((message) => <article key={message.id} className={`workspace-message ${message.role}`}><strong>{message.role === 'user' ? '我' : labels[scope]}</strong><SafeMessage text={message.text} /></article>)}
    </div>
    {run?.status === 'running' && <div className="workspace-run-status" role="status"><span>{phaseText}</span><button type="button" className="button subtle" onClick={cancel}>取消</button></div>}
    {run?.status === 'failed' && <div className="workspace-run-status error" role="status"><span>处理未完成，输入仍保留。</span><button type="button" className="button subtle" onClick={retry}>重试</button></div>}
    {data?.draft && <div className="workspace-draft"><div className="draft-heading"><strong>待确认修改</strong><span>正式档案尚未改变</span></div>
      {(data.draft.changes || []).map((change, index) => <article className="draft-change" key={`${change.title}-${index}`}><strong>{change.title}</strong><div><span>修改前：{change.before || '无'}</span><span>修改后：{change.after || '未提供'}</span></div><small>{change.impact}</small></article>)}
      {(data.draft.questions || []).map((question, index) => <p className="draft-question" key={index}>{question}</p>)}
      <div className="button-row"><button className="button primary" disabled={busy} onClick={confirmDraft}>确认保存</button><button className="button subtle" disabled={busy} onClick={() => act(() => discardGrowthDraft(data.draft.id))}>放弃草案</button></div>
      <p className="helper">确认档案或执行记录后，规划仍需单独生成并采用日程方案。</p>
    </div>}
    {confirmedDraft && <div className="workspace-confirmed"><strong>已确认并保存</strong><p>修改已写入档案或执行记录。接下来可以让规划助手据此重新评估本周安排。</p><button className="button secondary" onClick={() => onAdjustTask?.({ text: '根据刚确认的档案或执行记录，重新评估本周安排。' })}>据此调整本周安排</button></div>}
    {error && <p className="error-message" role="alert">{error}</p>}
    <form className="workspace-chat-input" onSubmit={send}><textarea value={text} onChange={(event) => setText(event.target.value)} rows={2} placeholder={placeholder} disabled={busy || !session} /><button className="button primary" disabled={busy || !text.trim() || !session}>{busy ? '处理中…' : '发送'}</button></form>
  </section>
}
