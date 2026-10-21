import { useEffect, useReducer, useState } from 'react'
import { getAssistantSettings } from './api.js'
import TasksPage from './pages/TasksPage.jsx'
import AssistantPage from './pages/AssistantPage.jsx'
import ReviewPage from './pages/GoalsGrowthPage.jsx'
import MyProfilePage from './pages/MyProfilePage.jsx'
import WorkspaceShell from './components/WorkspaceShell.jsx'
import ConversationManager from './components/ConversationManager.jsx'
import EditRecovery, { useEditRecovery } from './components/EditRecovery.jsx'
import { initialWorkbench, readSplitRatio, splitPreferenceKey, toolPlacement, workbenchPanel, workbenchReducer, workspaceClock } from './workbench.js'

export default function App() {
  return new URLSearchParams(window.location.search).get('layout') === 'legacy' ? <LegacyApp /> : <WorkspaceApp />
}

function WorkspaceApp() {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbench, initial => {
    try { return { ...initial, splitRatio: readSplitRatio(window.localStorage) } } catch { return initial }
  })
  const [settings, setSettings] = useState(null)
  const [clock, setClock] = useState('')
  const [settingsError,setSettingsError]=useState('')
  const [taskVersion, setTaskVersion] = useState(0)
  const [planningVersion, setPlanningVersion] = useState(0)
  const [adjustment, setAdjustment] = useState(null)
  const layoutRecovery = useEditRecovery({ workspace: settings?.workspace_id, resource: 'layout', base: settings ? 'layout-v1' : undefined,
    value: { navigation: state.navigation, auxiliaryPage: state.auxiliaryPage, panel: state.panel, conversations: state.conversations, mobile: state.mobile }, dirty: true,
    automatic: true, restore: value => dispatch({ type: 'restore', value }) })
  useEffect(() => { getAssistantSettings().then(next => setSettings({ ...next, receivedAt: Date.now() })).catch(cause => setSettingsError(cause.message)) }, [])
  useEffect(() => {
    if (!settings || !Number.isFinite(Date.parse(settings.now))) return
    let timer
    const tick = () => {
      const elapsed = Math.max(0, Date.now() - settings.receivedAt)
      setClock(workspaceClock(settings, elapsed))
      timer = setTimeout(tick, 60000 - (Date.parse(settings.now) + elapsed) % 60000)
    }
    tick()
    return () => clearTimeout(timer)
  }, [settings])
  useEffect(() => {
    try { localStorage.setItem(splitPreferenceKey, String(state.splitRatio)) } catch { /* Optional device preference; layout remains usable. */ }
  }, [state.splitRatio])
  const toolActive = page => toolPlacement(state, page) === 'primary' || (state.auxiliaryPage === page && workbenchPanel(state) !== 'collapsed')
  function requestAdjustment(next) {
    setAdjustment({ ...next, requestKey: crypto.randomUUID() })
    dispatch({ type: 'navigate', page: 'schedule' })
  }
  if (!settings) return <p role="status">{settingsError||'正在读取工作区设置…'}{settingsError&&<button onClick={()=>location.reload()}>重试读取工作区</button>}</p>
  return <ConversationManager key={settings?.workspace_id || 'loading'} workspace={settings?.workspace_id} onOpen={() => dispatch({ type: 'navigate', page: 'home' })}>{({ sidebar, chat: conversationChat, planning, openPlanning }) => <AssistantPage active={state.navigation === 'home' || toolActive('schedule')} observeChat={planning && state.navigation === 'home'} recoveryWorkspace={settings?.workspace_id} fullCalendar={state.navigation === 'schedule'} refreshVersion={planningVersion}
    requestedAction={adjustment} onActionHandled={() => setAdjustment(null)}
    onPlanConfirmed={() => setTaskVersion(value => value + 1)}
    onManagePreferences={() => dispatch({ type: 'navigate', page: 'profile' })}
    onOpenSchedule={() => dispatch({ type: 'navigate', page: 'schedule' })}
    onFocusChat={openPlanning}
    taskTools={<TasksPage recoveryWorkspace={settings?.workspace_id} refreshVersion={taskVersion} onDataChanged={() => setPlanningVersion(value => value + 1)} onAdjustTask={requestAdjustment} />}
    renderWorkbench={({ chat, children, conversation, auxiliarySchedule }) => <WorkspaceShell state={state} dispatch={dispatch} chatNote={planning?'当前支持任务规划与调整，自由交流将在后续开放。':'当前会话用于保存和浏览消息，AI 回复尚未接入。'} conversationContent={<><EditRecovery recovery={layoutRecovery} label="界面状态" />{sidebar}</>} chat={<><div className="v2-chat-surface" hidden={!planning} inert={!planning}>{chat}</div><div className="v2-chat-surface" hidden={planning} inert={planning}>{conversationChat}</div></>} conversation={conversation} auxiliarySchedule={auxiliarySchedule}
      clock={clock}
      review={state.visited.includes('review') && <ReviewPage embedded active={toolActive('review')} refreshVersion={taskVersion} onAdjustTask={requestAdjustment} />}
      profile={state.visited.includes('profile') && <MyProfilePage embedded recoveryWorkspace={settings?.workspace_id} active={toolActive('profile')} refreshVersion={taskVersion} onAdjustTask={requestAdjustment} />}>
      {children}
    </WorkspaceShell>} />}</ConversationManager>
}

function LegacyApp() {
  const [settings,setSettings]=useState(null)
  useEffect(()=>{getAssistantSettings().then(setSettings).catch(()=>{})},[])
  const [taskVersion,setTaskVersion]=useState(0)
  const [planningVersion,setPlanningVersion]=useState(0)
  const [tab, setTab] = useState('planning')
  const [adjustment, setAdjustment] = useState(null)

  function requestAdjustment(next) {
    setAdjustment({ ...next, requestKey: crypto.randomUUID() })
    setTab('planning')
  }

  return (
    <div className="app-shell compact-shell">
      <header className="site-header">
        <div className="container">
          <div className="brand-row"><h1>个人成长助手</h1><span>规划每一步，复盘每一程</span><a href="?">返回新工作台</a></div>
        </div>
      </header>
      <main className="container">
        <div className="navigation-row"><nav className="tabs" aria-label="功能导航">
          <button type="button" className={tab === 'planning' ? 'tab active' : 'tab'} aria-current={tab === 'planning' ? 'page' : undefined} onClick={() => setTab('planning')}>规划</button>
          <button type="button" className={tab === 'review' ? 'tab active' : 'tab'} aria-current={tab === 'review' ? 'page' : undefined} onClick={() => setTab('review')}>复盘</button>
          <button type="button" className={tab === 'profile' ? 'tab active' : 'tab'} aria-current={tab === 'profile' ? 'page' : undefined} onClick={() => setTab('profile')}>我的档案</button>
        </nav>{settings && <span className="workspace-clock">{settings.demo ? '演示 · ' : ''}{settings.now?.slice(0,16).replace('T',' ')} 北京时间</span>}</div>
        {tab === 'planning' && <>
          <AssistantPage active refreshVersion={planningVersion} onPlanConfirmed={()=>setTaskVersion(v=>v+1)} requestedAction={adjustment} onActionHandled={() => setAdjustment(null)} onManagePreferences={()=>setTab('profile')} taskTools={<TasksPage refreshVersion={taskVersion} onDataChanged={()=>setPlanningVersion(v=>v+1)} onAdjustTask={requestAdjustment} />} />
        </>}
        {tab === 'review' && <ReviewPage onAdjustTask={requestAdjustment} />}
        {tab === 'profile' && <MyProfilePage onAdjustTask={requestAdjustment} />}
      </main>
    </div>
  )
}
