import { useEffect, useRef, useState } from 'react'
import { cancelAssistantRun, confirmGrowthDraft, createAssistantRun, discardGrowthDraft, getAssistantRun, getAssistantSession, getAssistantSettings, openWorkspaceSession, retryAssistantRun } from '../api.js'
import { UI_COPY } from '../uiCopy.js'
import ChatMessages from './ChatMessages.jsx'
import SafeMessage from './SafeMessage.jsx'
import EditRecovery, { useEditRecovery } from './EditRecovery.jsx'
const labels = { profile: '档案助手', review: '复盘助手' }

export default function WorkspaceChat({ scope, weekStart, onAdjustTask, onDraftConfirmed, observe = true, workspace }) {
  const [session, setSession] = useState(null)
  const [data, setData] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [run, setRun] = useState(null)
  const [confirmedDraft, setConfirmedDraft] = useState(null)
  const [workspaceId, setWorkspaceId] = useState('')
  const [legacyInput, setLegacyInput] = useState('')
  const active = useRef(true)
  const observing = useRef(observe)
  observing.current = observe
  const initialization=useRef(null), pollGeneration=useRef(0)
  const requestId = useRef(null)
  const recovery = useEditRecovery({ workspace: workspaceId, resource: `tool:${session?.id}:input`, base: data ? scope : undefined,
    value: {text, requestId: requestId.current}, dirty: Boolean(text), automatic: true,
    restore: value => {setText(value.text);requestId.current=value.requestId||null} })
  useEffect(()=>{
    if(!workspaceId||!data)return
    try{setLegacyInput(localStorage.getItem(`growth-workspace-input-${workspaceId}-${scope}`)||'')}catch{/* current recovery displays storage limitations */}
  },[workspaceId,scope,Boolean(data)])

  async function refresh(id) {
    const result = await getAssistantSession(id)
    setData(result)
    const current = result.runs?.find((item) => item.status === 'running')
    if (current && observing.current) { setRun(current); setBusy(true); poll(current.id, id) }
    return result
  }

  useEffect(() => {
    active.current = true
    let cancelled=false
    const key=`${scope}:${weekStart}`
    if(initialization.current?.key!==key)initialization.current={key,promise:Promise.all([workspace?Promise.resolve({workspace_id:workspace}):getAssistantSettings(),openWorkspaceSession(scope,weekStart)])}
    initialization.current.promise.then(async ([settings, opened]) => {
      if (cancelled) return
      setWorkspaceId(settings.workspace_id)
      setSession(opened)
      await refresh(opened.id)
    }).catch((cause) => !cancelled && setError(cause.message))
    return () => { cancelled=true;active.current = false;pollGeneration.current++ }
  }, [scope, weekStart])
  useEffect(() => { pollGeneration.current++;if (observe && session) refresh(session.id).catch(cause=>setError(cause.message)) }, [observe])

  async function poll(runId, sessionId = session?.id) {
    const generation=++pollGeneration.current
    try {
      let result = await getAssistantRun(runId)
      while (result.status === 'running' && active.current && observing.current && generation===pollGeneration.current) {
        await new Promise((resolve) => setTimeout(resolve, 800))
        if (!active.current || !observing.current || generation!==pollGeneration.current) return result
        result = await getAssistantRun(runId)
      }
      if (!active.current || generation!==pollGeneration.current || !observing.current) return result
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
    try { const next = await retryAssistantRun(run.id); setRun(next); const result=await poll(next.id, session.id); if(result?.status==='completed'){setText('');requestId.current=null} }
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

  return <><section className="workspace-chat" aria-label={`${labels[scope]}聊天`}>
    <EditRecovery recovery={recovery} label="业务助手输入"/>
    {legacyInput&&<section className="recovery-note" aria-label="旧版输入对照"><p>检测到只按业务类型记录的旧版输入，请核对归属后手动带入；原缓存继续保留。</p><details><summary>查看旧版输入</summary><pre>{legacyInput}</pre></details><button className="button subtle" disabled={Boolean(text)} onClick={()=>{setText(legacyInput);setLegacyInput('')}}>带入旧版输入</button></section>}
    <div className="workspace-chat-heading"><div><h3>{labels[scope]}</h3></div></div>
    <ChatMessages className="workspace-chat-messages" revision={data?.messages?.at(-1)?.id}>
      {!data?.messages?.length && <p className="growth-empty">{placeholder}</p>}
      {data?.messages?.map((message) => <article key={message.id} className={`workspace-message ${message.role}`}><strong>{message.role === 'user' ? '我' : labels[scope]}</strong><SafeMessage text={message.text} /></article>)}
    </ChatMessages>
    {run?.status === 'running' && <div className="workspace-run-status" role="status"><span>{phaseText}</span><button type="button" className="button subtle" disabled={!run?.id} onClick={cancel}>取消</button></div>}
    {run?.status === 'failed' && <div className="workspace-run-status error" role="status"><span>处理未完成，输入仍保留。</span><button type="button" className="button subtle" onClick={retry}>重试</button></div>}
    {error && run?.status !== 'failed' && <p className="error-message" role="alert">{error}</p>}
    <form className="workspace-chat-input" onSubmit={send}><textarea value={text} onChange={(event) => { requestId.current=null; setText(event.target.value) }} rows={2} aria-label={scope==='profile'?'修改目标或偏好':'记录执行或询问进展'} placeholder={scope==='profile'?'修改目标或偏好':'记录执行或询问进展'} disabled={busy || !session} /><button className="button primary" disabled={busy || !text.trim() || !session}>发送</button></form>
  </section>
    {data?.draft && <div className="workspace-draft"><div className="draft-heading"><strong>{scope==='profile'?'修改待保存':'记录待保存'}</strong></div>
      {(data.draft.changes || []).map((change, index) => <article className="draft-change" key={`${change.title}-${index}`}><strong>{change.title}</strong><div><span>修改前：{change.before || '无'}</span><span>修改后：{change.after || '未提供'}</span></div><small>{change.impact}</small></article>)}
      {(data.draft.questions || []).map((question, index) => <p className="draft-question" key={index}>{question}</p>)}
      <div className="button-row"><button className="button primary" disabled={busy} onClick={confirmDraft}>{scope==='profile'?UI_COPY.saveProfile:UI_COPY.saveFeedback}</button><button className="button subtle" disabled={busy} onClick={() => act(() => discardGrowthDraft(data.draft.id))}>放弃</button></div>

    </div>}
    {confirmedDraft && <div className="workspace-confirmed"><strong>已保存</strong><button className="button secondary" onClick={() => onAdjustTask?.({ text: '根据刚确认的档案或执行记录，重新评估本周安排。' })}>{UI_COPY.adjust}</button></div>}
  </>
}
