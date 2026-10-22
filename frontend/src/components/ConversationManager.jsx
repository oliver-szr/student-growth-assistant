import { useEffect, useRef, useState } from 'react'
import { createConversation, deleteConversation, getConversations, updateConversation } from '../api.js'
import { editKey, readEdit, requestGate, writeEdit } from '../workbench.js'
import ConversationChat from './ConversationChat.jsx'
import WorkspaceChat from './WorkspaceChat.jsx'

export default function ConversationManager({ workspace, onOpen, children, active, onNavigate, onBusinessSaved, onAdjustTask, today }) {
  const [selected, setSelected] = useState(null), [target, setTarget] = useState(null), [ready, setReady] = useState(false)
  const [rows, setRows] = useState([]), [next, setNext] = useState(null), [query, setQuery] = useState(''), [search, setSearch] = useState(''), [archive, setArchive] = useState('active')
  const [revision, setRevision] = useState(0), [detailVersion, setDetailVersion] = useState(0)
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [storageWarning, setStorageWarning] = useState('')
  const [rename, setRename] = useState(null), [remove, setRemove] = useState(null)
  const [intent,setIntent]=useState(null)
  const gate = useRef(requestGate()), lock = useRef(false), createKey = useRef(null)
  useEffect(() => {
    if (!workspace) return
    try {
      const saved = readEdit(sessionStorage, editKey(workspace, 'selection'))?.value
      if (['planning', 'tool-profile', 'tool-review'].includes(saved) || Number.isSafeInteger(saved) && saved > 0) setSelected(saved)
      createKey.current = readEdit(sessionStorage, editKey(workspace, 'create-request'))?.value || null
    } catch { setStorageWarning('浏览器存储不可用；当前选择和输入的刷新恢复可能不可用。') }
    setReady(true)
  }, [workspace])
  useEffect(() => {
    if (!workspace || !ready || selected === null) return
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
  async function discuss(range){
    if(Number.isSafeInteger(selected)){setIntent({key:crypto.randomUUID(),range,text:`请与我回顾${range.start}至${range.end}（不含）的实际记录。`});onOpen();return}
    action(async()=>{const row=await createConversation({client_request_id:crypto.randomUUID()});open(row.id);setIntent({key:crypto.randomUUID(),range,text:`请与我回顾${range.start}至${range.end}（不含）的实际记录。`})})
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
  return children({ sidebar, discussReview:discuss, planning: selected === 'planning', openPlanning: () => open('planning'), openConversation: open,
    chat: ready && Number.isSafeInteger(selected) ? <ConversationChat today={today} intent={intent} active={active} onNavigate={onNavigate} key={`${workspace}:${selected}`} workspace={workspace} id={selected} target={target} revision={detailVersion} onChanged={() => setRevision(value => value + 1)} /> : selected?.startsWith?.('tool-') ? <WorkspaceChat workspace={workspace} key={selected} scope={selected.slice(5)} observe={active} renderLayout={({chat,children})=><>{chat}{children}</>} onAdjustTask={onAdjustTask} onDraftConfirmed={onBusinessSaved}/> : <section className="workspace-chat"><p>从一个想法开始，自由交流或查看已有记录。</p><button className="button primary" disabled={busy} onClick={fresh}>开始新对话</button></section>, openBusiness: scope => open('tool-'+scope) })
}
