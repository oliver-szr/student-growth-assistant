import { useEffect, useRef, useState } from 'react'
import { createConversation, deleteConversation, getConversation, getConversationMessages, getConversations, saveConversationMessage, updateConversation } from '../api.js'
import { editKey, mergeMessages, readEdit, requestGate, writeEdit } from '../workbench.js'
import EditRecovery, { useEditRecovery } from './EditRecovery.jsx'
import ChatMessages from './ChatMessages.jsx'
import SafeMessage from './SafeMessage.jsx'

export function ConversationChat({ workspace, id, target, revision, onChanged }) {
  const [meta, setMeta] = useState(null), [messages, setMessages] = useState([]), [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const [unavailable, setUnavailable] = useState(false), [input, setInput] = useState({ text: '', requestId: null })
  const gate = useRef(requestGate()), alive = useRef(true), sending = useRef(false), paging = useRef(false)
  const recovery = useEditRecovery({ workspace, resource: `conversation:${id}:input`, base: meta ? `${id}:${meta.scope}` : undefined,
    value: input, dirty: Boolean(input.text), restore: value => setInput({ text: typeof value.text === 'string' ? value.text : '', requestId: value.requestId || null }), automatic: true })
  useEffect(() => { alive.current = true; return () => { alive.current = false; gate.current.next() } }, [])
  useEffect(() => {
    const token = gate.current.next()
    setLoading(true); setError(''); setUnavailable(false)
    ;(async () => {
      const current = await getConversation(id)
      const page = await getConversationMessages(id, { after_id: target ? Math.max(0, target - 1) : 0, limit: 30 })
      if (!alive.current || !gate.current.current(token)) return
      setMeta(current); setMessages(page.items); setNext(page.next_after_id)
    })().catch(cause => {
      if (!alive.current || !gate.current.current(token)) return
      setError(cause.message); setUnavailable(true)
    }).finally(() => { if (alive.current && gate.current.current(token)) setLoading(false) })
  }, [id, target, revision])
  useEffect(() => {
    if (!loading && target) document.getElementById(`conversation-message-${id}-${target}`)?.scrollIntoView({ block: 'center' })
  }, [loading, target, id])
  async function loadMore(before = false) {
    if (paging.current || loading || unavailable) return
    paging.current = true; setBusy(true); setError('')
    const token = gate.current.next()
    try {
      const page = await getConversationMessages(id, before ? { before_id: messages[0]?.id, limit: 30 } : { after_id: next, limit: 30 })
      if (!alive.current || !gate.current.current(token)) return
      setMessages(current => mergeMessages(current, page.items))
      if (!before) setNext(page.next_after_id)
      if (before && !page.items.length) setNotice('已到会话开头。')
    } catch (cause) { if (alive.current && gate.current.current(token)) setError(cause.message) }
    finally { paging.current = false; if (alive.current) setBusy(false) }
  }
  async function send(event) {
    event.preventDefault()
    if (sending.current || !input.text.trim() || !meta || unavailable || meta.archived_at || meta.scope !== 'conversation') return
    sending.current = true; setBusy(true); setError(''); setNotice('')
    const payload = { client_message_id: input.requestId || crypto.randomUUID(), text: input.text }
    setInput({ text: input.text, requestId: payload.client_message_id })
    try {
      const message = await saveConversationMessage(id, payload)
      if (!alive.current) return
      setMessages(current => mergeMessages(current, [message])); setNotice('消息已保存；本阶段尚未接入 AI 回复。')
      setInput(current => current.text === payload.text ? { text: '', requestId: null } : current)
      onChanged()
    } catch (cause) {
      if (alive.current) {
        setError(cause.message)
        if ([404, 410].includes(cause.status)) setUnavailable(true)
        if (cause.code === 'CONVERSATION_ARCHIVED') setMeta(current => ({ ...current, archived_at: 'unavailable' }))
      }
    } finally { sending.current = false; if (alive.current) setBusy(false) }
  }
  return <section className="workspace-chat conversation-chat" aria-label="持久会话">
    <div className="workspace-chat-heading"><h2>{meta?.title || '读取会话'}</h2></div>
    <p className="helper">{meta?.scope && meta.scope !== 'conversation' ? '历史工具会话只读；规划和草案仍通过本周规划入口处理。' : '消息会保存到当前会话。统一 AI 回复将在 1B-2 接入。'}</p>
    {loading && <p role="status">正在读取会话…</p>}
    {error && <p className="error-box" role="alert">{error}</p>}
    {meta?.archived_at && !unavailable && <p role="status">当前会话已归档，请在会话栏恢复后再发送。</p>}
    <EditRecovery recovery={recovery} label="聊天输入" />
    <ChatMessages revision={messages.at(-1)?.id}>
      {!unavailable && <>
        {messages.length > 0 && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore(true)}>加载更早消息</button>}
        {messages.map(message => <article tabIndex={-1} id={`conversation-message-${id}-${message.id}`} key={message.id} className={`workspace-message ${message.role} ${target === message.id ? 'search-match' : ''}`}>
          <strong>{message.role === 'user' ? '我' : '历史助手消息'}</strong><SafeMessage text={message.text} />
        </article>)}
        {next !== null && <button className="button subtle" disabled={busy || loading} onClick={() => loadMore()}>加载后续消息</button>}
        {!loading && !messages.length && <p className="growth-empty">还没有消息。</p>}
      </>}
    </ChatMessages>
    {notice && <p role="status" className="helper">{notice}</p>}
    <form className="workspace-chat-input" onSubmit={send}>
      <label>会话输入<textarea aria-label="会话输入" value={input.text} maxLength={2000} disabled={busy || loading || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation'} onChange={event => setInput({ text: event.target.value, requestId: null })} /></label>
      <button className="button primary" disabled={busy || loading || unavailable || Boolean(meta?.archived_at) || meta?.scope !== 'conversation' || !input.text.trim()}>保存消息</button>
    </form>
  </section>
}

export default function ConversationManager({ workspace, onOpen, children }) {
  const [selected, setSelected] = useState('planning'), [target, setTarget] = useState(null), [ready, setReady] = useState(false)
  const [rows, setRows] = useState([]), [next, setNext] = useState(null), [query, setQuery] = useState(''), [search, setSearch] = useState(''), [archive, setArchive] = useState('active')
  const [revision, setRevision] = useState(0), [detailVersion, setDetailVersion] = useState(0)
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [storageWarning, setStorageWarning] = useState('')
  const [rename, setRename] = useState(null), [remove, setRemove] = useState(null)
  const gate = useRef(requestGate()), lock = useRef(false), createKey = useRef(null)
  useEffect(() => {
    if (!workspace) return
    try {
      const saved = readEdit(sessionStorage, editKey(workspace, 'selection'))?.value
      if (saved === 'planning' || Number.isSafeInteger(saved) && saved > 0) setSelected(saved)
      createKey.current = readEdit(sessionStorage, editKey(workspace, 'create-request'))?.value || null
    } catch { setStorageWarning('浏览器存储不可用；当前选择和输入的刷新恢复可能不可用。') }
    setReady(true)
  }, [workspace])
  useEffect(() => {
    if (!workspace || !ready) return
    try { writeEdit(sessionStorage, editKey(workspace, 'selection'), null, selected) }
    catch { setStorageWarning('浏览器无法保存当前会话选择；刷新后请重新打开。') }
  }, [workspace, ready, selected])
  useEffect(() => {
    if (!workspace) return
    const token = gate.current.next()
    setLoading(true); setRows([]); setNext(null)
    getConversations({ scope: 'all', q: search, archive: search ? 'all' : archive, limit: 30 }).then(page => {
      if (gate.current.current(token)) { setRows(page.items); setNext(page.next_offset) }
    }).catch(cause => { if (gate.current.current(token)) setError(cause.message) }).finally(() => { if (gate.current.current(token)) setLoading(false) })
    return () => { gate.current.next() }
  }, [workspace, search, archive, revision])
  function open(id, messageId = null) { setSelected(id); setTarget(messageId); onOpen() }
  async function more() {
    if (loading || next === null) return
    const token = gate.current.next(); setLoading(true)
    try {
      const page = await getConversations({ scope: 'all', q: search, archive: search ? 'all' : archive, offset: next, limit: 30 })
      if (gate.current.current(token)) { setRows(current => [...new Map([...current, ...page.items].map(row => [row.id, row])).values()]); setNext(page.next_offset) }
    } catch (cause) { if (gate.current.current(token)) setError(cause.message) }
    finally { if (gate.current.current(token)) setLoading(false) }
  }
  async function action(operation) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { await operation(); setRevision(value => value + 1); setDetailVersion(value => value + 1) }
    catch (cause) { setError(cause.message); if (cause.code === 'CONVERSATION_VERSION_CONFLICT') { setRevision(value => value + 1); setDetailVersion(value => value + 1) } }
    finally { lock.current = false; setBusy(false) }
  }
  function fresh() {
    action(async () => {
      createKey.current ||= crypto.randomUUID()
      try { writeEdit(sessionStorage, editKey(workspace, 'create-request'), null, createKey.current) } catch { setStorageWarning('无法保存新建重试标识；请确认结果后再刷新。') }
      const row = await createConversation({ client_request_id: createKey.current })
      createKey.current = null
      try { sessionStorage.removeItem(editKey(workspace, 'create-request')) } catch { /* same key only */ }
      open(row.id)
    })
  }
  const sidebar = <div className="conversation-list">
    <button className="button secondary" disabled={busy || !ready} onClick={fresh}>＋ 新对话</button>
    <button className="v2-current-conversation" aria-current={selected === 'planning' ? 'true' : undefined} onClick={() => open('planning')}>本周规划入口</button>
    <form onSubmit={event => { event.preventDefault(); setSearch(query.trim()); setError('') }}>
      <label className="v2-search">搜索会话<input type="search" placeholder="标题或正文" maxLength={100} value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="button-row"><button className="button subtle">搜索</button>{search && <button type="button" className="button subtle" onClick={() => { setQuery(''); setSearch('') }}>清除搜索</button>}</div>
    </form>
    <div className="button-row"><button className="button subtle" aria-pressed={archive === 'active'} onClick={() => setArchive('active')}>最近</button><button className="button subtle" aria-pressed={archive === 'archived'} onClick={() => setArchive('archived')}>归档</button><button className="button subtle" onClick={() => { setRevision(value => value + 1); setDetailVersion(value => value + 1) }}>刷新列表</button></div>
    {storageWarning && <p role="status" className="helper">{storageWarning}</p>}
    {error && <p role="alert" className="error-box">{error}</p>}
    {rename && <form className="conversation-rename" onSubmit={event => { event.preventDefault(); action(async () => {
      const current = rows.find(row => row.id === rename.id)
      await updateConversation(rename.id, { expected_version: current?.version || rename.version, title: rename.title.trim() }); setRename(null)
    }) }}><label>会话标题<input value={rename.title} required maxLength={160} onChange={event => setRename({ ...rename, title: event.target.value })} /></label><button className="button secondary" disabled={busy}>保存标题</button><button type="button" className="button subtle" onClick={() => setRename(null)}>取消改名</button></form>}
    {remove && <section className="recovery-note" aria-label="删除会话确认"><p>删除“{remove.title}”？会话会被隐藏，正文仍在本地和整库备份中；正式任务、日程、目标和反馈不会删除。</p><button className="button secondary" disabled={busy || loading} onClick={() => action(async () => { await deleteConversation(remove.id, rows.find(row=>row.id===remove.id)?.version||remove.version); setRemove(null) })}>确认删除会话</button><button className="button subtle" onClick={() => setRemove(null)}>取消删除</button></section>}
    {['置顶', search ? '搜索结果' : archive === 'archived' ? '已归档' : '最近会话'].map((group, index) => <section key={group} aria-label={group}><h2>{group}</h2>{rows.filter(row => Boolean(row.pinned_at) === (index === 0)).map(row => <article key={row.id} data-conversation-id={row.id} className="conversation-row">
      <button className="v2-current-conversation" aria-current={selected === row.id ? 'true' : undefined} onClick={() => open(row.id)}>{row.title}<small>{row.scope === 'conversation' ? row.archived_at ? '已归档' : '持久会话' : '历史工具 · 只读'}</small></button>
      {(row.message_matches || []).map(match => <button className="conversation-snippet" key={match.message_id} onClick={() => open(row.id, match.message_id)}>{match.snippet}</button>)}
      <details><summary>会话操作</summary><div className="conversation-actions">
        <button disabled={busy} onClick={() => setRename({ id: row.id, version: row.version, title: row.title })}>重命名</button>
        <button disabled={busy} onClick={() => action(() => updateConversation(row.id, { expected_version: row.version, pinned: !row.pinned_at }))}>{row.pinned_at ? '取消置顶' : '置顶'}</button>
        <button disabled={busy} onClick={() => action(() => updateConversation(row.id, { expected_version: row.version, archived: !row.archived_at }))}>{row.archived_at ? '恢复会话' : '归档会话'}</button>
        <button disabled={busy} onClick={() => setRemove(row)}>删除会话</button>
      </div></details>
    </article>)}</section>)}
    {loading && <p role="status">正在读取会话列表…</p>}{!loading && !rows.length && <p className="helper">没有符合条件的会话。</p>}
    {next !== null && <button className="button subtle" disabled={loading} onClick={more}>加载更多会话</button>}
  </div>
  return children({ sidebar, planning: selected === 'planning', openPlanning: () => open('planning'),
    chat: ready && selected !== 'planning' ? <ConversationChat key={`${workspace}:${selected}`} workspace={workspace} id={selected} target={target} revision={detailVersion} onChanged={() => setRevision(value => value + 1)} /> : null })
}
