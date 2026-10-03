import { useState } from 'react'
import TasksPage from './pages/TasksPage.jsx'
import TimeRulesPage from './pages/TimeRulesPage.jsx'
import WeeklyPlanPage from './pages/WeeklyPlanPage.jsx'

export default function App() {
  const [tab, setTab] = useState('tasks')

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="container">
          <p className="eyebrow">大学生成长助手</p>
          <h1>安排好你的一周</h1>
          <p className="subtitle">录入任务、课程和保留时间，查看候选周计划后再确认。</p>
        </div>
      </header>
      <main className="container">
        <nav className="tabs" aria-label="功能导航">
          <button type="button" className={tab === 'tasks' ? 'tab active' : 'tab'} aria-current={tab === 'tasks' ? 'page' : undefined} onClick={() => setTab('tasks')}>任务</button>
          <button type="button" className={tab === 'rules' ? 'tab active' : 'tab'} aria-current={tab === 'rules' ? 'page' : undefined} onClick={() => setTab('rules')}>课程与保留时间</button>
          <button type="button" className={tab === 'plans' ? 'tab active' : 'tab'} aria-current={tab === 'plans' ? 'page' : undefined} onClick={() => setTab('plans')}>周计划</button>
        </nav>
        {tab === 'tasks' && <TasksPage />}
        {tab === 'rules' && <TimeRulesPage />}
        <div hidden={tab !== 'plans'}><WeeklyPlanPage active={tab === 'plans'} /></div>
      </main>
    </div>
  )
}
