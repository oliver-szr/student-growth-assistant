import { useEffect, useState } from 'react'
import { getAssistantSettings } from './api.js'
import TasksPage from './pages/TasksPage.jsx'
import AssistantPage from './pages/AssistantPage.jsx'
import ReviewPage from './pages/GoalsGrowthPage.jsx'
import MyProfilePage from './pages/MyProfilePage.jsx'

export default function App() {
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
          <div className="brand-row"><h1>个人成长助手</h1><span>规划每一步，复盘每一程</span></div>
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
