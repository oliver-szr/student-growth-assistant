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
          <p className="eyebrow">Student Growth Assistant</p>
          <h1>Manage your week</h1>
          <p className="subtitle">Manage your tasks and commitments, then review and confirm a weekly plan.</p>
        </div>
      </header>
      <main className="container">
        <nav className="tabs" aria-label="Sections">
          <button type="button" className={tab === 'tasks' ? 'tab active' : 'tab'} aria-current={tab === 'tasks' ? 'page' : undefined} onClick={() => setTab('tasks')}>Tasks</button>
          <button type="button" className={tab === 'rules' ? 'tab active' : 'tab'} aria-current={tab === 'rules' ? 'page' : undefined} onClick={() => setTab('rules')}>Courses &amp; Protected Time</button>
          <button type="button" className={tab === 'plans' ? 'tab active' : 'tab'} aria-current={tab === 'plans' ? 'page' : undefined} onClick={() => setTab('plans')}>Weekly Plan</button>
        </nav>
        {tab === 'tasks' && <TasksPage />}
        {tab === 'rules' && <TimeRulesPage />}
        <div hidden={tab !== 'plans'}><WeeklyPlanPage active={tab === 'plans'} /></div>
      </main>
    </div>
  )
}
