import { useEffect, useRef, useState } from 'react'
import { createConversation, deleteConversation, getConversations, updateConversation } from '../api.js'
import { editKey, readEdit, requestGate, writeEdit } from '../workbench.js'
import ConversationChat from './ConversationChat.jsx'
import WorkspaceChat from './WorkspaceChat.jsx'
import ConversationMenu, { ConversationRow } from './ConversationMenu.jsx'

export default function ConversationManager({ workspace, onOpen, children, active, onNavigate, onBusinessSaved, onAdjustTask, today }) {
  const [selected, setSelected] = useState(null), [target, setTarget] = useState(null), [ready, setReady] = useState(false)
  const [rows, setRows] = useState([]), [next, setNext] = useState(null), [query, setQuery] = useState(''), [search, setSearch] = useState(''), [archive, setArchive] = useState('active')
  const [revision, setRevision] = useState(0), [detailVersion, setDetailVersion] = useState(0)
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [storageWarning, setStorageWarning] = useState('')
  const [rename, setRename] = useState(null), [remove, setRemove] = useState(null)
  const [menu, setMenu] = useState(null)
  const renameInput = useRef(null), deleteConfirm = useRef(null), pendingFocus = useRef(null), listIdentity = useRef(null)
  const [intent,setIntent]=useState(null)
  const gate = useRef(requestGate()), lock = useRef(false), createKey = useRef(null)
  useEffect(() => { setMenu(null) }, [search, archive, revision, active])
  useEffect(() => { if (rename) { renameInput.current?.focus(); renameInput.current?.select() } }, [rename?.id])
  useEffect(() => { if (remove) deleteConfirm.current?.focus() }, [remove?.id])
  useEffect(() => {
    if (loading || !pendingFocus.current) return
    const target = document.getElementById(`conversation-more-${pendingFocus.current}`) || document.querySelector('.conversation-filters [aria-pressed=true]')
    pendingFocus.current = null
    if (target && !target.closest('[hidden],[inert]')) target.focus({ preventScroll: true })
  }, [rows, loading])
  function closeMenu(restore = true) {
    const anchor = menu?.anchor
    setMenu(null)
    if (restore && anchor?.isConnected && !anchor.closest('[hidden],[inert]')) anchor.focus({ preventScroll: true })
  }
  function restoreRowFocus(id) {
    const target = document.getElementById(`conversation-more-${id}`)
    if (target) target.focus({ preventScroll: true })
  }
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
    const identity = JSON.stringify([workspace,search,archive])
    setLoading(true); setNext(null)
    if (listIdentity.current !== identity) { setRows([]); listIdentity.current = identity }
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
    const focusId = document.activeElement?.closest('.conversation-row')?.dataset.conversationId
    const focusReturn = () => focusId && (document.activeElement === document.body || document.activeElement?.closest('.conversation-row')?.dataset.conversationId === focusId) ? focusId : null
    lock.current = true; setBusy(true); setError('')
    try { await operation(); pendingFocus.current = focusReturn(); setLoading(true); setRevision(value => value + 1); setDetailVersion(value => value + 1) }
    catch (cause) { setError(cause.message); if (cause.code === 'CONVERSATION_VERSION_CONFLICT') { pendingFocus.current = focusReturn(); setLoading(true); setRevision(value => value + 1); setDetailVersion(value => value + 1) } }
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
  const currentMenu = rows.find(row => row.id === menu?.id)
  const menuItems = currentMenu ? [
    { key: 'rename', label: '重命名', select: () => setRename({ id: currentMenu.id, version: currentMenu.version, title: currentMenu.title }) },
    { key: 'pin', label: currentMenu.pinned_at ? '取消置顶' : '置顶', select: () => action(() => updateConversation(currentMenu.id, { expected_version: currentMenu.version, pinned: !currentMenu.pinned_at })) },
    { key: 'archive', label: currentMenu.archived_at ? '恢复会话' : '归档会话', select: () => action(() => updateConversation(currentMenu.id, { expected_version: currentMenu.version, archived: !currentMenu.archived_at })) },
    { key: 'delete', label: '删除会话', danger: true, select: () => setRemove(currentMenu) },
    ...(currentMenu.message_matches || []).map(match => ({ key: `match-${match.message_id}`, label: `查看匹配：${match.snippet}`, match: true, select: () => open(currentMenu.id, match.message_id) })),
  ] : []
  const sidebar = <div className="conversation-list">
    <div className="conversation-toolbar"><button className="button secondary conversation-new" disabled={busy || !ready} onClick={fresh}>＋ 新对话</button>
    <form className="conversation-search" role="search" aria-label="搜索会话" onSubmit={event => { event.preventDefault(); setSearch(query.trim()); setError('') }}>
      <input aria-label="搜索会话" type="search" placeholder="搜索会话" title="搜索标题或正文" maxLength={100} value={query} onChange={event => setQuery(event.target.value)} />
      <button type="submit" className="button subtle">搜索</button>
    </form>
    <div className="conversation-filters"><button className="button subtle" aria-pressed={!search && archive === 'active'} onClick={() => { setArchive('active'); setSearch(''); setQuery('') }}>最近</button><button className="button subtle" aria-pressed={!search && archive === 'archived'} onClick={() => { setArchive('archived'); setSearch(''); setQuery('') }}>归档</button><button className="button subtle conversation-refresh" aria-label="刷新列表" title="刷新列表" onClick={() => { setRevision(value => value + 1); setDetailVersion(value => value + 1) }}>↻</button></div>
    {search && <button type="button" className="button subtle conversation-clear" onClick={() => { setQuery(''); setSearch('') }}>清除搜索</button>}</div>
    {storageWarning && <p role="status" className="helper">{storageWarning}</p>}
    {error && <p role="alert" className="error-box">{error}</p>}
    {rename && <form className="conversation-rename" onSubmit={event => { event.preventDefault(); action(async () => {
      const current = rows.find(row => row.id === rename.id)
      await updateConversation(rename.id, { expected_version: current?.version || rename.version, title: rename.title.trim() }); setRename(null)
    }) }}><label>会话标题<input ref={renameInput} value={rename.title} required maxLength={160} onChange={event => setRename({ ...rename, title: event.target.value })} /></label><button className="button secondary" disabled={busy}>保存标题</button><button type="button" className="button subtle" onClick={() => { restoreRowFocus(rename.id); setRename(null) }}>取消改名</button></form>}
    {remove && <section className="recovery-note" aria-label="删除会话确认"><p>删除“{remove.title}”？这是软删除：会话会被隐藏，正文仍在本地和整库备份中；正式任务、日程、目标和反馈不会删除。</p><button ref={deleteConfirm} className="button secondary" disabled={busy || loading} onClick={() => action(async () => { await deleteConversation(remove.id, rows.find(row=>row.id===remove.id)?.version||remove.version); setRemove(null) })}>确认删除会话</button><button className="button subtle" onClick={() => { restoreRowFocus(remove.id); setRemove(null) }}>取消删除</button></section>}
    <div className="conversation-groups" aria-label="会话列表">
    {['置顶', search ? '搜索结果' : archive === 'archived' ? '已归档' : '最近会话'].map((group, index) => {
      const groupRows = rows.filter(row => Boolean(row.pinned_at) === (index === 0))
      return groupRows.length > 0 && <section key={group} aria-label={group}><h2>{group}</h2>{groupRows.map(row => <ConversationRow key={row.id} row={row} selected={selected === row.id} expanded={menu?.id === row.id} disabled={busy || loading}
        onOpen={() => open(row.id, search && !row.title_match ? row.message_matches?.[0]?.message_id : null)} onMenu={(anchor, last = false) => setMenu(menu?.id === row.id ? null : { id: row.id, anchor, last })} />)}</section>
    })}
    {loading && <p role="status">正在读取会话列表…</p>}{!loading && !rows.length && <p className="helper">没有符合条件的会话。</p>}
    {next !== null && <button className="button subtle" disabled={loading} onClick={more}>加载更多会话</button>}
    </div>
    <button className="button subtle conversation-planning" aria-current={selected === 'planning' ? 'true' : undefined} onClick={() => open('planning')}>本周规划入口</button>
    {currentMenu && menu && <ConversationMenu anchor={menu.anchor} last={menu.last} items={menuItems} onClose={closeMenu} />}
  </div>
  return children({ sidebar, discussReview:discuss, planning: selected === 'planning', openPlanning: () => open('planning'), openConversation: open,
    chat: ready && Number.isSafeInteger(selected) ? <ConversationChat onLocate={messageId=>{setTarget(messageId);setDetailVersion(value=>value+1)}} today={today} intent={intent} active={active} onNavigate={onNavigate} key={`${workspace}:${selected}`} workspace={workspace} id={selected} target={target} revision={detailVersion} onChanged={() => setRevision(value => value + 1)} /> : selected?.startsWith?.('tool-') ? <WorkspaceChat workspace={workspace} key={selected} scope={selected.slice(5)} observe={active} onAdjustTask={onAdjustTask} onDraftConfirmed={onBusinessSaved}/> : <section className="workspace-chat conversation-start"><h2>从一件事开始</h2><p>从一个想法开始，自由交流或查看已有记录。</p><button className="button primary" disabled={busy} onClick={fresh}>开始新对话</button></section>, openBusiness: scope => open('tool-'+scope) })
}
