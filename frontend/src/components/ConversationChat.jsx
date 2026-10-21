import { useEffect, useRef, useState } from 'react'
import { getConversation, getConversationMessages, getConversationRuns, getConversationRun, startConversationRun, stopConversationRun, retryConversationRun } from '../api.js'
import { applyReply, mergeMessages, requestGate } from '../workbench.js'
import { localizedError } from '../localization.js'
import EditRecovery, { useEditRecovery } from './EditRecovery.jsx'
import ChatMessages from './ChatMessages.jsx'
import SafeMessage from './SafeMessage.jsx'

const statuses = { completed: '回复已完成', failed: '回复未完成', cancelled: '已停止生成', interrupted: '回复已中断，可重试' }

export default function ConversationChat({ workspace, id, target, revision, onChanged, active = true, onNavigate }) {
  const [meta, setMeta] = useState(null), [messages, setMessages] = useState([]), [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [run, setRun] = useState(null), [observing, setObserving] = useState(true), [reload, setReload] = useState(0)
  const [unavailable, setUnavailable] = useState(false), [input, setInput] = useState({ text: '', requestId: null })
  const gate = useRef(requestGate()), alive = useRef(true), locked = useRef(false), cursor = useRef({})
  const recovery = useEditRecovery({ workspace, resource: `conversation:${id}:input`, base: meta ? `${id}:${meta.scope}` : undefined,
    value: input, dirty: Boolean(input.text), restore: value => setInput({ text: typeof value.text === 'string' ? value.text : '', requestId: value.requestId || null }), automatic: true })
  useEffect(() => { alive.current = true; return () => { alive.current = false; gate.current.next() } }, [])
  function receive(response) {
    cursor.current = { id: response.id, attempt: response.attempt, after: response.next_cursor }
    setMessages(current => applyReply(current, response)); setRun(response); setError('')
  }
  useEffect(()=>{
    if(input.requestId && run?.client_message_id===input.requestId) setInput({text:'',requestId:null})
  },[input.requestId,run?.client_message_id])
  useEffect(() => {
    if (!active) return
    const token = gate.current.next()
    setLoading(true); setError(''); setUnavailable(false)
    ;(async () => {
      const current = await getConversation(id)
      const [page, runs] = await Promise.all([
        getConversationMessages(id, { after_id: target ? Math.max(0, target - 1) : 0, limit: 30 }),
        current.scope === 'conversation' ? getConversationRuns(id) : Promise.resolve({ items: [] }),
      ])
      if (!alive.current || !gate.current.current(token)) return
      setMeta(current); setMessages(page.items); setNext(page.next_after_id)
      const latest = runs.items[0]
      if (latest) receive(latest)
      else setRun(null)
      setObserving(true)
    })().catch(cause => {
      if (!alive.current || !gate.current.current(token)) return
      setError(cause.message); setUnavailable([404, 410].includes(cause.status))
    }).finally(() => { if (alive.current && gate.current.current(token)) setLoading(false) })
    return () => { gate.current.next() }
  }, [id, target, revision, active, reload])
  useEffect(() => {
    if (!active || !observing || loading || run?.status !== 'running') return
    let cancelled = false, timer
    async function poll() {
      try {
        const known = cursor.current
        const response = await getConversationRun(id, run.id, known.id === run.id ? known.after : 0, known.attempt)
        if (cancelled || !alive.current) return
        receive(response)
        if (response.status === 'running') timer = setTimeout(poll, 300)
        else onChanged()
      } catch (cause) {
        if (!cancelled && alive.current) { setError(cause.message); setObserving(false) }
      }
    }
    timer = setTimeout(poll, 120)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [active, observing, loading, run?.id, run?.attempt, run?.status])
  useEffect(() => {
    if (!loading && target && active) document.getElementById(`conversation-message-${id}-${target}`)?.scrollIntoView({ block: 'center' })
  }, [loading, target, id, active])
  async function loadMore(before = false) {
    if (locked.current || loading || unavailable) return
    locked.current = true; setBusy(true); setError('')
    const token = gate.current.next()
    try {
      const page = await getConversationMessages(id, before ? { before_id: messages[0]?.id, limit: 30 } : { after_id: next, limit: 30 })
      if (!alive.current || !gate.current.current(token)) return
      setMessages(current => mergeMessages(current, page.items))
      if (!before) setNext(page.next_after_id)
    } catch (cause) { if (alive.current && gate.current.current(token)) setError(cause.message) }
    finally { locked.current = false; if (alive.current) setBusy(false) }
  }
  async function action(operation) {
    if (locked.current) return
    locked.current = true; setBusy(true); setError('')
    try { await operation() }
    catch (cause) { if (alive.current) {
      setError(cause.message)
      if ([404, 410].includes(cause.status)) setUnavailable(true)
      if (cause.code === 'CONVERSATION_ARCHIVED') setMeta(current=>({...current,archived_at:'unavailable'}))
    } }
    finally { locked.current = false; if (alive.current) setBusy(false) }
  }
  function send(event) {
    event.preventDefault()
    if (!input.text.trim() || !meta || unavailable || meta.archived_at || meta.scope !== 'conversation' || run?.status === 'running') return
    const payload = { client_message_id: input.requestId || crypto.randomUUID(), text: input.text }
    setInput({ text: input.text, requestId: payload.client_message_id })
    action(async () => {
      const response = await startConversationRun(id, payload)
      if (!alive.current) return
      setMessages(current => mergeMessages(current, [{ id: response.user_message_id, session_id: id, role: 'user', text: payload.text }]))
      receive(response); setObserving(true)
      setInput(current => current.text === payload.text ? { text: '', requestId: null } : current)
      onChanged()
    })
  }
  return <section className="workspace-chat conversation-chat" aria-label="持久会话">
    <div className="workspace-chat-heading"><h2>{meta?.title || '读取会话'}</h2></div>
    <p className="helper">{meta?.scope && meta.scope !== 'conversation' ? '历史工具会话只读；业务草案请从对应入口处理。' : '可以自由交流；业务变更需打开相应入口并由你确认。相关历史与所需记录会发送给配置的模型服务。'}</p>
    <div className="button-row" aria-label="聊天业务入口">
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'schedule', kind: 'schedule' })}>日程与任务</button>
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'review', kind: 'review' })}>查看复盘</button>
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'profile', kind: 'profile' })}>目标与档案</button>
    </div>
    {loading && <p role="status">正在读取会话…</p>}
    {error && <p className="error-box" role="alert">{error}<button className="button subtle" onClick={() => setReload(value => value + 1)}>重新读取</button></p>}
    {meta?.archived_at && !unavailable && <p role="status">当前会话已归档，请在会话栏恢复后再发送。</p>}
    <EditRecovery recovery={recovery} label="聊天输入" />
    <ChatMessages revision={`${messages.at(-1)?.id}:${messages.at(-1)?.text?.length}`}>
      {!unavailable && <>
        {messages.length > 0 && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore(true)}>加载更早消息</button>}
        {messages.map(message => <article tabIndex={-1} id={`conversation-message-${id}-${message.id}`} key={message.id} className={`workspace-message ${message.role} ${target === message.id ? 'search-match' : ''}`}>
          <strong>{message.role === 'user' ? '我' : '成长助手'}</strong><SafeMessage text={message.text} />
          {message.content?.status && message.content.status !== 'completed' && <small>{statuses[message.content.status] || '正在生成…'}</small>}
          <div className="button-row">{(Array.isArray(message.content?.links)?message.content.links:[]).filter(link=>link&&typeof link.label==='string'&&['schedule','review','profile'].includes(link.page)).map((link, i) => <button className="button subtle" key={i} onClick={() => onNavigate?.({...link,conversationId:id,messageId:message.id})}>{link.label}</button>)}</div>
        </article>)}
        {next !== null && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore()}>加载后续消息</button>}
        {!loading && !messages.length && <p className="growth-empty">还没有消息。</p>}
      </>}
    </ChatMessages>
    {run && <section aria-label="回复状态" className="reply-status">
      <p role="status">{run.status === 'running' ? run.delivery === 'full' ? '服务使用完整回复模式，正在等待结果…' : run.delivery === 'streaming' ? '正在接收回复…' : '正在理解并读取必要上下文…' : statuses[run.status]}</p>
      {run.error_code && <p role="alert">{localizedError(503, { code: run.error_code })}</p>}
      {run.status === 'running' && <><button className="button subtle" disabled={busy} onClick={() => action(async () => { const response = await stopConversationRun(id, run.id, run.attempt); if (alive.current) receive(response) })}>停止生成</button>
        <button className="button subtle" onClick={() => setObserving(value => !value)}>{observing ? '停止等待' : '继续读取'}</button></>}
      {['failed', 'cancelled', 'interrupted'].includes(run.status) && <button className="button secondary" disabled={busy} onClick={() => action(async () => { const response = await retryConversationRun(id, run.id, run.attempt); if (alive.current) { receive(response); setObserving(true) } })}>重试回复</button>}
      {!observing && run.status === 'running' && <p className="helper">已停止此界面的观察，后台回复可能继续；点击继续读取恢复。</p>}
    </section>}
    <form className="workspace-chat-input" onSubmit={send}>
      <label>会话输入<textarea aria-label="会话输入" value={input.text} maxLength={2000} disabled={busy || loading || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation'} onChange={event => setInput({ text: event.target.value, requestId: null })} /></label>
      <button className="button primary" disabled={busy || loading || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation' || !input.text.trim() || run?.status === 'running'}>发送</button>
    </form>
  </section>
}
