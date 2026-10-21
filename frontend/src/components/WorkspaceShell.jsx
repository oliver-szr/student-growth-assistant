import { cloneElement, isValidElement, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { defaultSplitRatio, renderedSplitRatio, splitBounds, toolPlacement, workbenchPanel, workbenchVisibility, workspacePages } from '../workbench.js'

const labels = { home: '首页', schedule: '日程', review: '复盘', profile: '档案' }

// Full tools stay in the primary area; auxiliary previews only read their formal data.
export default function WorkspaceShell({ state, dispatch, chat, children, review, profile, clock, conversation, auxiliarySchedule }) {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches)
  const [gridWidth, setGridWidth] = useState(1440)
  const [auxiliaryTarget, setAuxiliaryTarget] = useState(null)
  const root = useRef(null), grid = useRef(null), lastFocus = useRef(null), drag = useRef(null)
  const panel = workbenchPanel(state)
  const visible = workbenchVisibility(state, narrow)
  const home = state.navigation === 'home'
  const listWidth = !home || panel === 'expanded' ? 0 : state.conversations ? 192 : 44
  const available = Math.max(680, gridWidth - 76 - listWidth - 8)
  const ratio = renderedSplitRatio(state.splitRatio, available)
  const bounds = splitBounds(available)
  const resizable = !narrow && panel === 'normal'
  const controls = 'v2-auxiliary-shared'

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    change()
    return () => media.removeEventListener('change', change)
  }, [])
  useLayoutEffect(() => {
    const measure = () => setGridWidth(grid.current.clientWidth)
    const observer = new ResizeObserver(measure)
    observer.observe(grid.current)
    measure()
    return () => observer.disconnect()
  }, [])
  useLayoutEffect(() => {
    const focused = root.current?.contains(document.activeElement) ? document.activeElement : lastFocus.current
    if (!root.current?.contains(focused) || !focused.closest('[hidden], [inert]')) return
    const target = narrow ? `[data-mobile="${state.mobile}"]` : home ? '#v2-chat' : '#v2-page-' + state.navigation
    root.current.querySelector(target)?.focus()
  }, [state, narrow])
  useEffect(() => { if (!resizable) drag.current = null }, [resizable])

  function navigate(page) {
    dispatch({ type: 'navigate', page })
    requestAnimationFrame(() => root.current?.querySelector(page === 'home' ? '#v2-chat' : '#v2-page-' + page)?.focus())
  }
  function changePanel(value) {
    dispatch({ type: 'panel', value })
    requestAnimationFrame(() => root.current?.querySelector(narrow ? `[data-mobile="${value === 'collapsed' ? 'primary' : 'auxiliary'}"]` : value === 'collapsed' ? '#v2-restore-workspace' : '#v2-tab-' + state.auxiliaryPage)?.focus())
  }
  function tabKey(event, page) {
    const index = workspacePages.indexOf(page)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2
      : event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : null
    if (next === null) return
    event.preventDefault()
    dispatch({ type: 'auxiliary', page: workspacePages[next] })
    root.current.querySelector('#v2-tab-' + workspacePages[next])?.focus()
  }
  function resizeKey(event) {
    const next = event.key === 'ArrowLeft' ? ratio - 0.02 : event.key === 'ArrowRight' ? ratio + 0.02
      : event.key === 'Home' ? bounds.min : event.key === 'End' ? bounds.max : event.key === 'Enter' ? defaultSplitRatio : null
    if (next === null) return
    event.preventDefault()
    dispatch({ type: 'split', value: renderedSplitRatio(next, available) })
  }
  function pointerDown(event) {
    if (event.button !== 0) return
    event.preventDefault()
    event.currentTarget.focus()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { id: event.pointerId, ratio: state.splitRatio }
  }
  function pointerMove(event) {
    if (!resizable || drag.current?.id !== event.pointerId) return
    const offset = event.clientX - grid.current.getBoundingClientRect().left - 76 - listWidth
    dispatch({ type: 'split', value: renderedSplitRatio(offset / available, available) })
  }
  function pointerEnd(event, cancel = false) {
    if (drag.current?.id !== event.pointerId) return
    if (cancel) dispatch({ type: 'split', value: drag.current.ratio })
    drag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return <div ref={root} onFocusCapture={event => { lastFocus.current = event.target }} className="app-shell compact-shell v2-shell" data-navigation={state.navigation} data-panel={panel} data-conversations={visible.conversations ? 'open' : 'closed'} style={{ '--v2-list-width': `${listWidth}px`, '--v2-primary-fr': `${ratio}fr`, '--v2-auxiliary-fr': `${1 - ratio}fr` }}>
    <a className="v2-skip" href={home ? '#v2-chat' : '#v2-page-' + state.navigation} onClick={() => { dispatch({ type: 'mobile', value: 'primary' }); requestAnimationFrame(() => root.current?.querySelector(home ? '#v2-chat' : '#v2-page-' + state.navigation)?.focus()) }}>跳到主体内容</a>
    <div className="v2-mobile-switch" role="group" aria-label="手机工作台视图">
      {['conversations', 'primary', 'auxiliary'].map((surface, i) => <button key={surface} type="button" data-mobile={surface} aria-pressed={state.mobile === surface} onClick={() => dispatch({ type: 'mobile', value: surface })}>{['会话', home ? '聊天' : labels[state.navigation], '辅助栏'][i]}</button>)}
    </div>
    <div ref={grid} className="v2-grid">
      <nav className="v2-navigation" aria-label="主导航">
        <div className="v2-brand" title="个人成长助手" aria-label="个人成长助手">生长</div>
        {['home', ...workspacePages].map((page, i) => <button key={page} type="button" aria-current={state.navigation === page ? 'page' : undefined} onClick={() => navigate(page)}><span aria-hidden="true">{['⌂', '▦', '◷', '◇'][i]}</span>{labels[page]}</button>)}
        <div className="v2-nav-bottom"><a href="?layout=legacy" target="_blank" rel="noopener" title="在新标签页打开旧版">旧版入口</a><span className="v2-account" aria-label="账号区预留">账号预留</span></div>
      </nav>
      <aside id="v2-conversations" className="v2-conversations" aria-label="会话区域" hidden={narrow ? !visible.conversations : !home || panel === 'expanded'} inert={narrow ? !visible.conversations : !home || panel === 'expanded'}>
        <button id="v2-toggle-conversations" className="v2-list-toggle" type="button" aria-label={visible.conversations ? '收起会话列表' : '展开会话列表'} aria-expanded={visible.conversations} aria-controls="v2-conversation-content" onClick={() => dispatch({ type: 'conversations' })}>{visible.conversations ? '会话 ‹' : '›'}</button>
        <div id="v2-conversation-content" hidden={!visible.conversations} inert={!visible.conversations}>
          <button className="button secondary" type="button" disabled aria-describedby="v2-session-note">＋ 新对话</button>
          <label className="v2-search">搜索会话<input type="search" placeholder="搜索会话" disabled aria-describedby="v2-session-note" /></label>
          <p id="v2-session-note" className="helper">新建、搜索与归档将在后续开放。</p>
          <h2>当前对话</h2>
          {conversation ? <button type="button" className="v2-current-conversation" aria-current="true" onClick={() => navigate('home')}>本周规划对话<small>继续当前内容</small></button> : <p className="helper">正在读取对话…</p>}
          <p className="v2-session-empty">其他会话尚未接入</p>
        </div>
      </aside>
      <main id="v2-chat" className="v2-chat" tabIndex={-1} aria-label="主聊天" hidden={!home || !visible.primary} inert={!home || !visible.primary}>
        <header className="v2-chat-heading"><div><p className="eyebrow">个人成长助手</p><h1>从一件事开始</h1></div><span className="workspace-clock">{clock}</span></header>
        <p className="v2-chat-note">当前支持任务规划与调整，自由交流将在后续开放。</p>
        {chat}
      </main>
      <div className="v2-resizer" role="separator" tabIndex={0} hidden={!resizable} inert={!resizable} aria-label="调整主体与辅助栏宽度" aria-orientation="vertical" aria-valuemin={Math.round(bounds.min * 100)} aria-valuemax={Math.round(bounds.max * 100)} aria-valuenow={Math.round(ratio * 100)} aria-valuetext={`主体占 ${Math.round(ratio * 100)}%`} onKeyDown={resizeKey} onDoubleClick={() => dispatch({ type: 'split', value: defaultSplitRatio })} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerEnd} onPointerCancel={event => pointerEnd(event, true)} onLostPointerCapture={() => { drag.current = null }} />
      <aside id="v2-workspace" className="v2-workspace" aria-label="辅助栏控制" hidden={narrow && !visible.auxiliary} inert={narrow && !visible.auxiliary}>
        <button id="v2-restore-workspace" className="v2-workspace-restore" type="button" hidden={visible.auxiliary} aria-label="恢复辅助栏" aria-expanded="false" onClick={() => changePanel('normal')}>‹<span>辅助栏</span></button>
        <header className="v2-workspace-heading" hidden={!visible.auxiliary} inert={!visible.auxiliary}>
          <div className="v2-workspace-tabs" role="tablist" aria-label="辅助栏页签">{workspacePages.map(page => <button key={page} id={'v2-tab-' + page} type="button" role="tab" aria-selected={state.auxiliaryPage === page} aria-controls={controls} tabIndex={state.auxiliaryPage === page ? 0 : -1} onKeyDown={event => tabKey(event, page)} onClick={() => dispatch({ type: 'auxiliary', page })}>{labels[page]}</button>)}</div>
          <div className="v2-panel-controls">
            {!narrow && <button type="button" onClick={() => dispatch({ type: 'split', value: defaultSplitRatio })}>恢复默认宽度</button>}
            <button type="button" aria-label={panel === 'expanded' ? '恢复普通辅助栏' : '展开辅助栏'} aria-pressed={panel === 'expanded'} onClick={() => changePanel(panel === 'expanded' ? 'normal' : 'expanded')}>{panel === 'expanded' ? '普通' : '展开'}</button>
            <button type="button" aria-label="收起辅助栏" aria-expanded="true" aria-controls={controls} onClick={() => changePanel('collapsed')}>收起</button>
          </div>
        </header>
      </aside>
      {workspacePages.map(page => {
        const placement = toolPlacement(state, page)
        const shown = placement !== 'hidden' && visible[placement]
        const content = page === 'schedule' ? children : page === 'review' ? review : profile
        const target = page === state.auxiliaryPage ? auxiliaryTarget : null
        return <section key={page} id={'v2-page-' + page} className="v2-tool-page" data-placement={placement} role="main" tabIndex={-1} aria-labelledby={'v2-primary-' + page} hidden={!shown} inert={!shown}>
          <header className="v2-primary-page-heading"><h1 id={'v2-primary-' + page}>{labels[page]}</h1><span className="workspace-clock">{clock}</span></header>
          {page !== 'schedule' && isValidElement(content) ? cloneElement(content, { auxiliaryTarget: target }) : content}
        </section>
      })}
      <div id="v2-auxiliary-shared" className="v2-tool-page" data-placement="auxiliary" role="tabpanel" aria-labelledby={'v2-tab-' + state.auxiliaryPage} hidden={!visible.auxiliary} inert={!visible.auxiliary}>
        <div hidden={state.auxiliaryPage !== 'schedule'} inert={state.auxiliaryPage !== 'schedule'}>{auxiliarySchedule}</div>
        <div ref={setAuxiliaryTarget} />
      </div>
    </div>
  </div>
}
