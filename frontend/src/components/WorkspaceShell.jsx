import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { workbenchVisibility, workspacePages } from '../workbench.js'

const labels = { home: '首页', schedule: '日程', review: '复盘', profile: '档案' }

// A layout only: business data and unsaved forms stay in their original pages.
export default function WorkspaceShell({ state, dispatch, chat, children, review, profile, clock, conversation }) {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches)
  const root = useRef(null)
  const lastFocus = useRef(null)
  const visible = workbenchVisibility(state, narrow)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    change()
    return () => media.removeEventListener('change', change)
  }, [])
  useLayoutEffect(() => {
    const focused = root.current?.contains(document.activeElement) ? document.activeElement : lastFocus.current
    if (!root.current?.contains(focused) || !focused.closest('[hidden], [inert]')) return
    const target = narrow ? `[data-mobile="${state.mobile}"]`
      : state.panel === 'collapsed' ? '#v2-restore-workspace'
        : state.panel === 'expanded' ? '#v2-tab-' + state.page
          : !visible.conversations ? '#v2-toggle-conversations' : '#v2-tab-' + state.page
    root.current.querySelector(target)?.focus()
  }, [state, narrow, visible.conversations])

  function tabKey(event, page) {
    const index = workspacePages.indexOf(page)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2
      : event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : null
    if (next === null) return
    event.preventDefault()
    dispatch({ type: 'open', page: workspacePages[next] })
    root.current.querySelector('#v2-tab-' + workspacePages[next])?.focus()
  }

  return <div ref={root} onFocusCapture={event => { lastFocus.current = event.target }} className="app-shell compact-shell v2-shell" data-panel={state.panel} data-conversations={visible.conversations ? 'open' : 'closed'}>
    <a className="v2-skip" href="#v2-chat" onClick={() => { dispatch({ type: 'mobile', value: 'chat' }); requestAnimationFrame(() => root.current?.querySelector('#v2-chat')?.focus()) }}>跳到聊天</a>
    <div className="v2-mobile-switch" role="group" aria-label="手机工作台视图">
      {['conversations', 'chat', 'workspace'].map((surface, i) => <button key={surface} type="button" data-mobile={surface} aria-pressed={state.mobile === surface} aria-controls={'v2-' + surface} onClick={() => dispatch({ type: 'mobile', value: surface })}>{['会话', '聊天', '工作区'][i]}</button>)}
    </div>
    <div className="v2-grid">
      <nav className="v2-navigation" aria-label="主导航">
        <div className="v2-brand" title="个人成长助手" aria-label="个人成长助手">生长</div>
        {['home', ...workspacePages].map((page, i) => <button key={page} type="button" aria-current={state.navigation === page ? 'page' : undefined} onClick={() => { dispatch({ type: 'open', page }); if (page === 'home') requestAnimationFrame(() => root.current?.querySelector('#v2-chat')?.focus()) }}><span aria-hidden="true">{['⌂', '▦', '◷', '◇'][i]}</span>{labels[page]}</button>)}
        <div className="v2-nav-bottom"><a href="?layout=legacy" target="_blank" rel="noopener" title="在新标签页打开旧版">旧版入口</a><span className="v2-account" aria-label="账号区预留">账号预留</span></div>
      </nav>
      <aside id="v2-conversations" className="v2-conversations" aria-label="会话区域" hidden={(narrow && !visible.conversations) || (!narrow && state.panel === 'expanded')} inert={(narrow && !visible.conversations) || (!narrow && state.panel === 'expanded')}>
        <button id="v2-toggle-conversations" className="v2-list-toggle" type="button" aria-label={visible.conversations ? '收起会话列表' : '展开会话列表'} aria-expanded={visible.conversations} aria-controls="v2-conversation-content" onClick={() => dispatch({ type: 'conversations' })}>{visible.conversations ? '会话 ‹' : '›'}</button>
        <div id="v2-conversation-content" hidden={!visible.conversations} inert={!visible.conversations}>
          <button className="button secondary" type="button" disabled aria-describedby="v2-session-note">＋ 新对话</button>
          <label className="v2-search">搜索会话<input type="search" placeholder="搜索会话" disabled aria-describedby="v2-session-note" /></label>
          <p id="v2-session-note" className="helper">新建、搜索与归档将在后续开放。</p>
          <h2>当前对话</h2>
          {conversation ? <button type="button" className="v2-current-conversation" aria-current="true" onClick={() => dispatch({ type: 'mobile', value: 'chat' })}>本周规划对话<small>继续当前内容</small></button> : <p className="helper">正在读取对话…</p>}
          <p className="v2-session-empty">其他会话尚未接入</p>
        </div>
      </aside>
      <main id="v2-chat" className="v2-chat" tabIndex={-1} aria-label="主聊天" hidden={!visible.chat} inert={!visible.chat}>
        <header className="v2-chat-heading"><div><p className="eyebrow">个人成长助手</p><h1>从一件事开始</h1></div><span className="workspace-clock">{clock}</span></header>
        <p className="v2-chat-note">当前支持任务规划与调整，自由交流将在后续开放。</p>
        {chat}
      </main>
      <aside id="v2-workspace" className="v2-workspace" aria-label="工作区" hidden={narrow && !visible.workspace} inert={narrow && !visible.workspace}>
        <button id="v2-restore-workspace" className="v2-workspace-restore" type="button" hidden={visible.workspace} aria-label="恢复工作区" aria-expanded="false" onClick={() => { dispatch({ type: 'panel', value: 'normal' }); requestAnimationFrame(() => root.current?.querySelector('#v2-tab-' + state.page)?.focus()) }}>‹<span>工作区</span></button>
        <div className="v2-workspace-open" hidden={!visible.workspace} inert={!visible.workspace}>
          <header className="v2-workspace-heading">
            <div className="v2-workspace-tabs" role="tablist" aria-label="工作区页签">{workspacePages.map(page => <button key={page} id={'v2-tab-' + page} type="button" role="tab" aria-selected={state.page === page} aria-controls={'v2-page-' + page} tabIndex={state.page === page ? 0 : -1} onKeyDown={event => tabKey(event, page)} onClick={() => dispatch({ type: 'open', page })}>{labels[page]}</button>)}</div>
            <div className="v2-panel-controls">
              <button type="button" aria-label={state.panel === 'expanded' ? '恢复普通工作区' : '展开工作区'} aria-pressed={state.panel === 'expanded'} onClick={() => dispatch({ type: 'panel', value: state.panel === 'expanded' ? 'normal' : 'expanded' })}>{state.panel === 'expanded' ? '普通' : '展开'}</button>
              <button type="button" aria-label="收起工作区" aria-expanded="true" onClick={() => { dispatch({ type: 'panel', value: 'collapsed' }); requestAnimationFrame(() => root.current?.querySelector(narrow ? '[data-mobile="chat"]' : '#v2-restore-workspace')?.focus()) }}>收起</button>
            </div>
          </header>
          {workspacePages.map(page => <div key={page} id={'v2-page-' + page} className="v2-tool-page" role="tabpanel" tabIndex={0} aria-labelledby={'v2-tab-' + page} hidden={state.page !== page} inert={state.page !== page}>{page === 'schedule' ? children : page === 'review' ? review : profile}</div>)}
        </div>
      </aside>
    </div>
  </div>
}
