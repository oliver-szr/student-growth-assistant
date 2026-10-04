import { useState } from 'react'
import TasksPage from './pages/TasksPage.jsx'
import AssistantPage from './pages/AssistantPage.jsx'
import ReviewPage from './pages/GoalsGrowthPage.jsx'
import MyProfilePage from './pages/MyProfilePage.jsx'

export default function App() {
  const [tab, setTab] = useState('planning')
  const [adjustment, setAdjustment] = useState(null)

  function requestAdjustment(next) {
    setAdjustment({ ...next, requestKey: crypto.randomUUID() })
    setTab('planning')
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="container">
          <p className="eyebrow">个人成长助手</p>
          <h1>规划每一步，复盘每一程</h1>
          <p className="subtitle">安排任务、回看真实进展，并持续靠近个人目标。</p>
        </div>
      </header>
      <main className="container">
        <nav className="tabs" aria-label="功能导航">
          <button type="button" className={tab === 'planning' ? 'tab active' : 'tab'} aria-current={tab === 'planning' ? 'page' : undefined} onClick={() => setTab('planning')}>规划</button>
          <button type="button" className={tab === 'review' ? 'tab active' : 'tab'} aria-current={tab === 'review' ? 'page' : undefined} onClick={() => setTab('review')}>复盘</button>
          <button type="button" className={tab === 'profile' ? 'tab active' : 'tab'} aria-current={tab === 'profile' ? 'page' : undefined} onClick={() => setTab('profile')}>我的档案</button>
        </nav>
        {tab === 'planning' && <>
          <AssistantPage active requestedAction={adjustment} onActionHandled={() => setAdjustment(null)} />
          <details className="workspace-details"><summary><strong>任务与执行</strong><span>查看任务、记录实际投入、完成反馈和可选计时器</span></summary><TasksPage onAdjustTask={requestAdjustment} /></details>
        </>}
        {tab === 'review' && <ReviewPage onAdjustTask={requestAdjustment} />}
        {tab === 'profile' && <MyProfilePage onAdjustTask={requestAdjustment} />}
      </main>
    </div>
  )
}
