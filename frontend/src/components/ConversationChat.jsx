import { useEffect, useRef, useState,lazy,Suspense } from 'react'
import { getConversation, getConversationMessages, getConversationRuns, getConversationRun, startConversationRun, stopConversationRun, retryConversationRun, createReviewDraft, getWorkspaceDraft } from '../api.js'
import { applyReply, mergeMessages, requestGate, visibleChatMessages, toolNotices } from '../workbench.js'
import { localizedError } from '../localization.js'
import EditRecovery, { useEditRecovery } from './EditRecovery.jsx'
import ChatMessages from './ChatMessages.jsx'
import { coordinateDrafts } from '../draftCoordination.js'
import { DraftCard, draftEvent } from './WorkspaceDraft.jsx'
import { reviewRange } from '../calendar.js'
import ConversationSummary from './ConversationSummary.jsx'
const MemoryCard=lazy(()=>import('./MemoryPanel.jsx').then(module=>({default:module.MemoryCard})))
import SafeMessage from './SafeMessage.jsx'

const statuses = { completed: '回复已完成', failed: '回复未正常结束，内容可能不完整', cancelled: '已停止生成', interrupted: '回复已中断，可重试' }

export default function ConversationChat({ workspace, id, target, revision, onChanged, active = true, onNavigate, today, intent,onLocate }) {
  const [meta, setMeta] = useState(null), [messages, setMessages] = useState([]), [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [run, setRun] = useState(null), [observing, setObserving] = useState(true), [reload, setReload] = useState(0)
  const [unavailable, setUnavailable] = useState(false), [input, setInput] = useState({ text: '', requestId: null })
  const [reviewDates,setReviewDates]=useState(()=>{const [start,end]=reviewRange(today||new Date().toISOString().slice(0,10),'week');return {start_date:start,end_date:end,period:'week'}})
  const [reviewOpen,setReviewOpen]=useState(false),[intentPending,setIntentPending]=useState(null)
  const [summaryTarget,setSummaryTarget]=useState(null)
  const reviewRequest=useRef(null),seenIntent=useRef(null)
  useEffect(()=>{
    if(!intent||seenIntent.current===intent.key)return
    seenIntent.current=intent.key
    setReviewDates({start_date:intent.range.start,end_date:intent.range.end,period:intent.range.period})
    setIntentPending(intent)
  },[intent])
  const reviewRecovery=useEditRecovery({workspace,resource:`conversation:${id}:review-preview`,base:meta?`review-preview:${id}`:undefined,
    value:{dates:reviewDates,request:reviewRequest.current,open:reviewOpen},dirty:reviewOpen||Boolean(reviewRequest.current),automatic:true,
    restore:value=>{setReviewDates(value.dates);reviewRequest.current=value.request;setReviewOpen(Boolean(value.open))}})
  const toolSignature=useRef('')
  const gate = useRef(requestGate()), alive = useRef(true), locked = useRef(false), cursor = useRef({})
  const recovery = useEditRecovery({ workspace, resource: `conversation:${id}:input`, base: meta ? `${id}:${meta.scope}` : undefined,
    value: input, dirty: Boolean(input.text), restore: value => setInput({ text: typeof value.text === 'string' ? value.text : '', requestId: value.requestId || null }), automatic: true })
  useEffect(() => { alive.current = true; return () => { alive.current = false; gate.current.next() } }, [])
  function receive(response) {
    const signature=JSON.stringify(response.content?.tools||[])
    if(signature!==toolSignature.current){toolSignature.current=signature;draftEvent()}
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
      let anchor=null;try{anchor=JSON.parse(sessionStorage.getItem(`sga-chat-scroll:${workspace}:${id}`))?.first_id}catch{/* optional scroll preference */}
      const [page, runs] = await Promise.all([
        getConversationMessages(id, target?{after_id:Math.max(0,target-1),limit:30}:Number.isSafeInteger(anchor)&&anchor>0?{after_id:anchor-1,limit:30}:{latest:true,limit:30}),
        current.scope === 'conversation' ? getConversationRuns(id) : Promise.resolve({ items: [] }),
      ])
      if (!alive.current || !gate.current.current(token)) return
      setMeta(current); setMessages(page.items);setWindowStart(0); setNext(page.next_after_id)
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
    if (!loading && target && active){const item=document.getElementById(`conversation-message-${id}-${target}`);item?.scrollIntoView({ block: 'center' });item?.focus({preventScroll:true})}
  }, [loading, target, id, active])
  const [windowStart,setWindowStart]=useState(0)
  const displayMessages=visibleChatMessages(messages)
  const visibleMessages=displayMessages.slice(windowStart,windowStart+120)
  async function loadMore(before = false) {
    if (locked.current || loading || unavailable) return
    locked.current = true; setBusy(true); setError('')
    const token = gate.current.next()
    try {
      const page = await getConversationMessages(id, before ? { before_id: messages[0]?.id, limit: 30 } : { after_id: next, limit: 30 })
      if (!alive.current || !gate.current.current(token)) return
      setMessages(current => mergeMessages(current, page.items));if(before)setWindowStart(0)
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
      const draft_versions=await coordinateDrafts()
      // Read visible persisted cards after editors settle. This supplies an
      // optimistic version even when the user continues directly in chat.
      const known=new Set(draft_versions.map(ref=>`${ref.kind}:${ref.id}`))
      const cards=[...new Map(messages.flatMap(message=>(message.content?.tools||[]).filter(result=>result.draft).map(result=>[`${result.draft.kind}:${result.draft.id}`,result.draft]))).values()].slice(-10)
      for(const ref of cards){
        if(known.has(`${ref.kind}:${ref.id}`))continue
        const latest=await getWorkspaceDraft(ref.kind,ref.id)
        if(!['applied','discarded','superseded','stale'].includes(latest.status))draft_versions.push({kind:latest.kind,id:latest.id,version:latest.version})
      }
      const response = await startConversationRun(id, {...payload,draft_versions,review_range:{start:reviewDates.start_date,end:reviewDates.end_date}})
      if (!alive.current) return
      setMessages(current => mergeMessages(current, [{ id: response.user_message_id, session_id: id, role: 'user', text: payload.text }]))
      receive(response); setObserving(true)
      setWindowStart(current=>Math.max(current,displayMessages.length-118))
      setInput(current => current.text === payload.text ? { text: '', requestId: null } : current)
      onChanged()
    })
  }
  return <section className="workspace-chat conversation-chat" aria-label="持久会话">
    <div className="workspace-chat-heading"><h2 title={meta?.title}>{meta?.title || '读取会话'}</h2><div className="conversation-summary-trigger" ref={setSummaryTarget}/></div>
    <p className="helper conversation-intro" title="相关历史与所需资料会发送给你配置的模型服务。">{meta?.scope && meta.scope !== 'conversation' ? '历史工具会话只读；业务草案请从对应入口处理。' : '从一个想法开始，重要修改由你确认。'}</p>
    <div className="button-row conversation-shortcuts" role="group" aria-label="聊天业务入口">
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'schedule', kind: 'schedule' })}>日程与任务</button>
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'review', kind: 'review' })}>查看复盘</button>
      <button className="button subtle" onClick={() => onNavigate?.({ page: 'profile', kind: 'profile' })}>目标与档案</button>
    </div>
    {intentPending&&<section className="recovery-note"><p>从回顾带入的讨论：{intentPending.text}</p><button className="button secondary" disabled={Boolean(input.text)} onClick={()=>{setInput({text:intentPending.text,requestId:null});setIntentPending(null)}}>填入聊天（不会自动发送）</button><button className="button subtle" onClick={()=>setIntentPending(null)}>保留当前输入</button></section>}
    {loading && <p role="status">正在读取会话…</p>}
    {error && <p className="error-box" role="alert">{error}<button className="button subtle" onClick={() => setReload(value => value + 1)}>重新读取</button></p>}
    {meta?.archived_at && !unavailable && <p role="status">当前会话已归档，请在会话栏恢复后再发送。</p>}
    <EditRecovery recovery={recovery} label="聊天输入" /><EditRecovery recovery={reviewRecovery} label="复盘整理请求" />
    <ConversationSummary workspace={workspace} id={id} active={active} unavailable={unavailable||meta?.scope!=='conversation'} onLocate={onLocate} triggerTarget={summaryTarget}/>
    <ChatMessages storageKey={workspace?`sga-chat-scroll:${workspace}:${id}`:null} revision={`${windowStart}:${messages[0]?.id}:${messages.length}:${messages.at(-1)?.id}:${messages.at(-1)?.text?.length}`}>
      {!unavailable && <>
        {messages.length > 0 && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore(true)}>加载更早消息</button>}
        {windowStart>0&&<button className="button subtle" onClick={()=>setWindowStart(Math.max(0,windowStart-100))}>显示前一段已加载消息</button>}
        {visibleMessages.map(message => <article tabIndex={-1} id={`conversation-message-${id}-${message.id}`} key={message.id} className={`workspace-message ${message.role} ${target === message.id ? 'search-match' : ''}`}>
          <strong>{message.role === 'user' ? '我' : '成长助手'}</strong><SafeMessage text={message.text} />
          {message.content?.status && message.content.status !== 'completed' && message.id!==run?.assistant_message_id && <small>{statuses[message.content.status] || '正在生成…'}</small>}
          {(message.content?.tools||[]).filter(result=>result.memory||result.draft).map((result,index)=>result.memory?<Suspense key={index} fallback={<p role="status">正在读取记忆建议…</p>}><MemoryCard id={result.memory.id} active={active} onOpen={onNavigate}/></Suspense>:<DraftCard key={index} reference={result.draft} active={active} onOpen={link=>onNavigate?.({...link,conversationId:id,messageId:message.id})}/>)}
          {toolNotices(message.content?.tools,message.content?.questions).map(notice=><p className="helper" key={notice}>{notice}</p>)}
          <div className="button-row">{(Array.isArray(message.content?.links)?message.content.links:[]).filter(link=>link&&typeof link.label==='string'&&['schedule','review','profile'].includes(link.page)).map((link, i) => <button className="button subtle" key={i} onClick={() => onNavigate?.({...link,conversationId:id,messageId:message.id})}>{link.label}</button>)}</div>
        </article>)}
        {windowStart+120<displayMessages.length&&<button className="button subtle" onClick={()=>setWindowStart(Math.max(0,displayMessages.length-120))}>显示最新已加载消息</button>}
        {next !== null && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore()}>加载后续消息</button>}
        {!loading && !error && !messages.length && (meta?.scope==='conversation' ? <div className="conversation-welcome"><h3>想先聊些什么？</h3><p>说说眼前的事，或一起看看接下来的安排。</p></div> : <p className="growth-empty">还没有消息。</p>)}
      </>}
    </ChatMessages>
    {run && <section aria-label="回复状态" className="reply-status">
      <p role="status">{run.status === 'running' ? run.phase==='querying'?'正在查询正式记录…':run.phase==='calculating'?'正在计算待审核草案…':run.delivery === 'full' ? '服务使用完整回复模式，正在等待结果…' : run.delivery === 'streaming' ? '正在接收回复…' : '正在理解并读取必要上下文…' : run.status==='failed'&&run.content?.tools?.some(result=>result.draft)?'草案已生成；文字回复未正常结束，可重试':statuses[run.status]}</p>
      {run.error_code && <p role="alert">{run.content?.tools?.some(result=>result.draft)?'已保存的初稿与查询结果仍可查看；本次AI文字回复失败，重试不会重复创建正式任务。':localizedError(503, { code: run.error_code })}</p>}
      {run.status === 'running' && <><button className="button subtle" disabled={busy} onClick={() => action(async () => { const response = await stopConversationRun(id, run.id, run.attempt); if (alive.current) receive(response) })}>停止生成</button>
        <button className="button subtle" onClick={() => setObserving(value => !value)}>{observing ? '停止等待' : '继续读取'}</button></>}
      {['failed', 'cancelled', 'interrupted'].includes(run.status) && <button className="button secondary" disabled={busy} onClick={() => action(async () => { const response = await retryConversationRun(id, run.id, run.attempt); if (alive.current) { receive(response); setObserving(true) } })}>重试回复</button>}
      {!observing && run.status === 'running' && <p className="helper">已停止此界面的观察，后台回复可能继续；点击继续读取恢复。</p>}
    </section>}
    {meta?.scope==='conversation'&&<><button className="button subtle conversation-review-action" aria-expanded={reviewOpen} disabled={busy||loading||unavailable||Boolean(meta.archived_at)||run?.status==='running'} onClick={()=>setReviewOpen(!reviewOpen)}>整理为复盘记录</button>
    {reviewOpen&&<form className="review-preview-form" onSubmit={event=>{event.preventDefault();action(async()=>{
      reviewRequest.current ||= {...reviewDates,client_request_id:crypto.randomUUID(),message_id:messages.at(-1)?.id}
      const result=await createReviewDraft(id,reviewRequest.current)
      reviewRequest.current=null;setReviewOpen(false);setReload(v=>v+1)
      onNavigate?.({page:'review',kind:'review_record',id:result.id,conversationId:id})
    })}}><p className="helper">仅整理指定范围和当前讨论为可编辑草案，确认后才保存复盘，不会创建任务。</p><label>开始日期<input required type="date" value={reviewDates.start_date} onChange={e=>{reviewRequest.current=null;setReviewDates({...reviewDates,start_date:e.target.value})}}/></label><label>结束日期（不含）<input required type="date" value={reviewDates.end_date} onChange={e=>{reviewRequest.current=null;setReviewDates({...reviewDates,end_date:e.target.value})}}/></label><label>记录周期<select value={reviewDates.period} onChange={e=>{reviewRequest.current=null;setReviewDates({...reviewDates,period:e.target.value})}}><option value="day">日</option><option value="week">周</option><option value="month">月</option></select></label><button className="button secondary" disabled={busy}>生成可编辑预览</button></form>}</>}
    <form className="workspace-chat-input" onSubmit={send}>
      <label>会话输入<textarea aria-label="会话输入" value={input.text} maxLength={2000} disabled={busy || loading || !recovery.ready || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation'} onChange={event => setInput({ text: event.target.value, requestId: null })} /></label>
      <button className="button primary" disabled={busy || loading || !recovery.ready || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation' || !input.text.trim() || run?.status === 'running'}>发送</button>
    </form>
  </section>
}
