import { useEffect, useState } from 'react'
import {
  getProfileContext, createGoal, createPreferenceRule, createTaskCategory, exportGrowthData, getGoals, getGrowthProfile,
  getLocalBackups, getPreferenceRules, getTaskCategories, getTaskGrowthContext, getTasks, importGrowthData,
  saveTaskGrowthContext, updateGoal, updatePreferenceRule, updateTaskCategory,
} from '../api.js'
import TimeRulesPage from './TimeRulesPage.jsx'
import WorkspaceChat from '../components/WorkspaceChat.jsx'
import { goalPayload } from '../goals.js'

const emptyGoal = { title: '', motivation: '', priority: 2, metric_kind: 'count', weekly_target: 1, unit_label: '次', due_date: '' }
const emptyRule = { name: '', description: '', kind: 'prefer_time', category_key: '', weekdays: [], start: '08:00', end: '12:00', hours: '24', mode: 'balanced', text: '' }
const ruleLabels = { prefer_time: '适合时段', avoid_time: '尽量避开', deadline_buffer: '截止缓冲', adjustment_mode: '调整取舍', ai_note: 'AI 参考说明' }
const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function describeRule(rule) {
  const parameters = rule.parameters || {}
  const days = rule.weekdays?.length ? ` · ${rule.weekdays.map((day) => dayNames[day - 1]).join('、')}` : ''
  const category = rule.category_name ? `${rule.category_name} · ` : ''
  if (rule.kind === 'prefer_time') return `${category}尽量安排在 ${parameters.start}–${parameters.end}${days}`
  if (rule.kind === 'avoid_time') return `${category || '所有任务 · '}尽量避开 ${parameters.start}–${parameters.end}${days}`
  if (rule.kind === 'deadline_buffer') return `${category || '重要任务 · '}希望在截止前 ${parameters.hours} 小时完成`
  if (rule.kind === 'adjustment_mode') return `当前取舍：${({ balanced: '兼顾习惯与稳定', preference: '优先符合习惯', stable: '尽量少移动已有安排' })[parameters.mode] || parameters.mode}`
  return parameters.text || rule.description || '只供 AI 参考，不直接参与排程'
}

export default function MyProfilePage({ onAdjustTask }) {
  const [profile, setProfile] = useState(null)
  const [goals, setGoals] = useState([])
  const [tasks, setTasks] = useState([])
  const [contexts, setContexts] = useState({})
  const [categories, setCategories] = useState([])
  const [rules, setRules] = useState([])
  const [goalForm, setGoalForm] = useState(emptyGoal)
  const [editingGoalId, setEditingGoalId] = useState(null)
  const [categoryName, setCategoryName] = useState('')
  const [editingCategoryKey, setEditingCategoryKey] = useState(null)
  const [ruleForm, setRuleForm] = useState(emptyRule)
  const [editingRuleId, setEditingRuleId] = useState(null)
  const [showGoalEditor,setShowGoalEditor]=useState(false)
  const [showRuleEditor, setShowRuleEditor] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [backups, setBackups] = useState([])

  async function load() {
    const [snapshot,backupData]=await Promise.all([getProfileContext(),getLocalBackups()])
    setProfile(snapshot.profile);setBackups(backupData.backups||[]);setGoals(snapshot.goals)
    setCategories(snapshot.categories);setRules(snapshot.rules);setTasks(snapshot.tasks.filter(task=>task.status==='todo'))
    setContexts(snapshot.contexts)

  }

  useEffect(() => {
    let active = true
    load().catch((cause) => setError(cause.message)).finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])

  async function runAction(action, success) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await load(); setNotice(success) }
    catch (cause) { setError(cause.message) }
    finally { setBusy(false) }
  }

  async function saveGoal(event) {
    event.preventDefault()
    const payload = goalPayload(goalForm)
    await runAction(async () => {
      if (editingGoalId) await updateGoal(editingGoalId, payload)
      else await createGoal(payload)
      setGoalForm(emptyGoal); setEditingGoalId(null); setShowGoalEditor(false)
    }, '长期目标已保存；现有日程不会因此被直接改动。')
  }

  async function linkTask(task, goalId, family) {
    const current = contexts[task.id] || {}
    await runAction(() => saveTaskGrowthContext(task.id, { family, goal_id: goalId ? Number(goalId) : null, deadline_source: current.deadline_source || 'external' }), `${task.title} 的任务类别与目标关联已保存。`)
  }

  function startNewRule() { setEditingRuleId(null); setRuleForm(emptyRule); setShowRuleEditor(true) }
  function editRule(rule) {
    const parameters = rule.parameters || {}
    setEditingRuleId(rule.id)
    setRuleForm({ name: rule.name, description: rule.description || '', kind: rule.kind, category_key: rule.category_key || '', weekdays: rule.weekdays || [], start: parameters.start || '08:00', end: parameters.end || '12:00', hours: String(parameters.hours ?? 24), mode: parameters.mode || 'balanced', text: parameters.text || '' })
    setShowRuleEditor(true)
    requestAnimationFrame(()=>{const el=document.getElementById('preference-editor');el?.scrollIntoView({block:'nearest'});el?.querySelector('input')?.focus({preventScroll:true})})
  }

  async function saveRule(event) {
    event.preventDefault()
    const parameters = ruleForm.kind === 'prefer_time' || ruleForm.kind === 'avoid_time'
      ? { start: ruleForm.start, end: ruleForm.end }
      : ruleForm.kind === 'deadline_buffer' ? { hours: Number(ruleForm.hours) }
        : ruleForm.kind === 'adjustment_mode' ? { mode: ruleForm.mode } : { text: ruleForm.text }
    const payload = { name: ruleForm.name, description: ruleForm.description, kind: ruleForm.kind,
      category_key: ['prefer_time', 'avoid_time', 'deadline_buffer'].includes(ruleForm.kind) ? (ruleForm.category_key || null) : null,
      weekdays: ruleForm.weekdays.length ? ruleForm.weekdays : null, parameters }
    await runAction(async () => {
      if (editingRuleId) await updatePreferenceRule(editingRuleId, payload)
      else await createPreferenceRule(payload)
      setShowRuleEditor(false); setEditingRuleId(null); setRuleForm(emptyRule)
    }, '安排偏好已保存，之后生成的候选方案会读取这条规则。')
  }

  async function saveCategory(event) {
    event.preventDefault()
    await runAction(async () => {
      if (editingCategoryKey) await updateTaskCategory(editingCategoryKey, { name: categoryName })
      else await createTaskCategory({ name: categoryName })
      setCategoryName(''); setEditingCategoryKey(null)
    }, '任务类别已保存，现有任务和历史记录仍保留稳定关联。')
  }

  async function exportData() {
    setBusy(true); setError(''); setNotice('')
    try {
      const snapshot = await exportGrowthData()
      const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob); const link = document.createElement('a')
      link.href = url; link.download = `student-growth-backup-${new Date().toISOString().slice(0, 10)}.json`; link.click(); URL.revokeObjectURL(url)
      setNotice('已下载本地 JSON 备份。备份中不包含 API 密钥或 .env 配置。')
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }

  async function importDataFile(event) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    if (!window.confirm('导入会替换当前本地任务、目标、偏好、复盘和聊天记录。系统会先创建本地安全备份。确定继续吗？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      await importGrowthData(JSON.parse(await file.text()))
      setNotice('数据已恢复，正在重新载入工作台。'); window.setTimeout(() => window.location.reload(), 500)
    } catch (cause) { setError(cause instanceof SyntaxError ? '这个文件不是有效的 JSON 备份。' : cause.message) }
    finally { setBusy(false) }
  }

  const renderRule = (rule) => <article className={`preference-rule-card ${rule.enabled ? '' : 'rule-disabled'}`} key={rule.id}>
        <div className="preference-rule-copy"><div className="preference-rule-title"><strong>{rule.name}</strong><span className={`badge ${rule.enabled ? 'status-active' : 'status-inactive'}`}>{rule.enabled ? '已启用' : '已停用'}</span>{rule.kind === 'ai_note' && <span className="badge">仅供 AI 参考</span>}{rule.source === 'sample' && <span className="badge">示例</span>}</div><p>{describeRule(rule)}</p><details><summary>详情</summary>{rule.description && <small>{rule.description}</small>}<small>类型：{ruleLabels[rule.kind]} · 来源：{rule.source === 'sample' ? '演示示例' : rule.source === 'ai' ? '你采用的 AI 建议' : '用户确认'} · 更新于 {new Date(rule.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</small></details></div>
        <div className="preference-rule-actions"><button type="button" className="button subtle" disabled={busy} onClick={() => editRule(rule)}>编辑</button><button type="button" className="button subtle" disabled={busy} onClick={() => runAction(() => updatePreferenceRule(rule.id, { enabled: !rule.enabled }), rule.enabled ? '这条偏好已停用，历史记录仍保留。' : '这条偏好已重新启用。')}>{rule.enabled ? '停用' : '启用'}</button></div>
      </article>
  const renderGoal = (goal) => <article className={`goal-card ${goal.status !== 'active' ? 'goal-inactive' : ''}`} key={goal.id}>
        <div className="goal-card-top"><div><span className="goal-priority">{({ 1: '最优先', 2: '重要', 3: '保持推进' })[goal.priority] || '重要'}</span><h4>{goal.title}</h4></div><span className={`badge status-${goal.status === 'active' ? 'active' : 'inactive'}`}>{goal.status === 'active' ? '进行中' : goal.status === 'paused' ? '已暂停' : goal.status === 'completed' ? '已完成' : '已归档'}</span></div>
        <details><summary>详情</summary>{goal.motivation && <p>{goal.motivation}</p>}<span>版本 v{goal.version}</span></details><div className="goal-metric"><span>{({ time: '投入时间', count: '完成次数', deliverable: '明确交付' })[goal.metric_kind]}：每周 {goal.weekly_target} {goal.unit_label}</span>{goal.due_date && <span>目标日期：{goal.due_date}</span>}</div>
        <div className="button-row"><button className="button subtle" disabled={busy} onClick={() => { setEditingGoalId(goal.id); setGoalForm({ ...goal, priority: String(goal.priority), weekly_target: String(goal.weekly_target), due_date: goal.due_date || '' }); setShowGoalEditor(true); requestAnimationFrame(()=>{const el=document.getElementById('goal-editor');el?.scrollIntoView({block:'nearest',behavior:'smooth'});el?.querySelector('input')?.focus({preventScroll:true})}) }}>修改目标</button><select aria-label={`${goal.title}状态`} disabled={busy} value={goal.status} onChange={(event) => runAction(() => updateGoal(goal.id, { status: event.target.value }), '目标状态已更新。')}><option value="active">进行中</option><option value="paused">暂停</option><option value="completed">完成</option><option value="archived">归档</option></select></div>
      </article>
  if (loading) return <p className="state-box">正在读取档案、目标和已确认偏好…</p>

  const weekdays = ruleForm.weekdays
  return <section className="growth-page profile-page" aria-labelledby="profile-heading">
    <div className="growth-page-heading"><div><h2 id="profile-heading">我的档案</h2></div></div>
    <WorkspaceChat scope="profile" onAdjustTask={onAdjustTask} onDraftConfirmed={load}>
    {error && <p className="error-box" role="alert">{error}</p>}{notice && <p className="success-box" role="status">{notice}</p>}

    <section className="growth-section profile-wide">
      <div className="growth-section-heading"><div><h3>安排偏好</h3></div><button className="button secondary" type="button" onClick={startNewRule}>新增偏好</button></div>
      {!rules.length ? <p className="growth-empty">暂无偏好。</p> : <><div className="preference-rule-list">{rules.filter(item=>item.enabled).map(renderRule)}</div><details><summary>已停用</summary><div className="preference-rule-list">{rules.filter(item=>!item.enabled).map(renderRule)}</div></details></>}
      {showRuleEditor && <form id="preference-editor" className="growth-form preference-rule-editor" onSubmit={saveRule}>
        <h4>{editingRuleId ? '编辑偏好规则' : '新增偏好规则'}</h4>
        <div className="growth-form-row"><label>偏好名称<input required maxLength="120" value={ruleForm.name} onChange={(event) => setRuleForm({ ...ruleForm, name: event.target.value })} placeholder="例如：论文写作尽量上午完成" /></label><label>规则类型<select value={ruleForm.kind} onChange={(event) => setRuleForm({ ...ruleForm, kind: event.target.value })}>{Object.entries(ruleLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label></div>
        {['prefer_time', 'avoid_time', 'deadline_buffer'].includes(ruleForm.kind) && <label>适用类别<select value={ruleForm.category_key} onChange={(event) => setRuleForm({ ...ruleForm, category_key: event.target.value })}><option value="">全部任务 / 全局</option>{categories.filter((item) => item.active).map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>}
        {(ruleForm.kind === 'prefer_time' || ruleForm.kind === 'avoid_time') && <><div className="growth-form-row"><label>开始时间<input type="time" required value={ruleForm.start} onChange={(event) => setRuleForm({ ...ruleForm, start: event.target.value })} /></label><label>结束时间<input type="time" required value={ruleForm.end} onChange={(event) => setRuleForm({ ...ruleForm, end: event.target.value })} /></label></div><fieldset className="weekday-picker"><legend>适用星期（不选表示每天）</legend>{dayNames.map((label, index) => <label key={label}><input type="checkbox" checked={weekdays.includes(index + 1)} onChange={(event) => setRuleForm({ ...ruleForm, weekdays: event.target.checked ? [...weekdays, index + 1].sort() : weekdays.filter((day) => day !== index + 1) })} />{label}</label>)}</fieldset></>}
        {ruleForm.kind === 'deadline_buffer' && <label>希望至少提前几小时<input type="number" min="0" max="72" value={ruleForm.hours} onChange={(event) => setRuleForm({ ...ruleForm, hours: event.target.value })} /></label>}
        {ruleForm.kind === 'adjustment_mode' && <label>安排取舍<select value={ruleForm.mode} onChange={(event) => setRuleForm({ ...ruleForm, mode: event.target.value })}><option value="balanced">兼顾习惯、稳定和截止缓冲</option><option value="preference">更符合个人习惯</option><option value="stable">尽量少动已有安排</option></select></label>}
        {ruleForm.kind === 'ai_note' && <label>给档案助手的参考说明<textarea required maxLength="1200" rows="3" value={ruleForm.text} onChange={(event) => setRuleForm({ ...ruleForm, text: event.target.value })} placeholder="例如：临近考试时，我希望优先复习核心课程。" /></label>}
        <label>补充说明<textarea rows="2" maxLength="1000" value={ruleForm.description} onChange={(event) => setRuleForm({ ...ruleForm, description: event.target.value })} placeholder="可选，用于解释这条规则的背景" /></label>
        <div className="button-row"><button className="button primary" disabled={busy}>保存</button><button className="button subtle" type="button" onClick={() => setShowRuleEditor(false)}>取消</button></div>
      </form>}
    </section>

    <section className="growth-section profile-wide">
      <div className="growth-section-heading"><div><h3>长期目标</h3></div><button type="button" className="button secondary" onClick={()=>setShowGoalEditor(v=>!v)}>新增目标</button></div>
      <form hidden={!showGoalEditor} id="goal-editor" onSubmit={saveGoal} className="growth-form">
        <label>目标名称<input required maxLength="160" value={goalForm.title} onChange={(event) => setGoalForm({ ...goalForm, title: event.target.value })} placeholder="例如：每周阅读三篇论文" /></label>
        <label>为什么重要<textarea rows="2" maxLength="2000" value={goalForm.motivation} onChange={(event) => setGoalForm({ ...goalForm, motivation: event.target.value })} placeholder="帮助自己和助手理解这个目标的意义" /></label>
        <div className="growth-form-row"><label>优先顺序<select value={goalForm.priority} onChange={(event) => setGoalForm({ ...goalForm, priority: event.target.value })}><option value="1">最优先</option><option value="2">重要</option><option value="3">保持推进</option></select></label><label>进展方式<select value={goalForm.metric_kind} onChange={(event) => setGoalForm({ ...goalForm, metric_kind: event.target.value, unit_label: event.target.value === 'time' ? '分钟' : event.target.value === 'count' ? '次' : '项' })}><option value="count">完成次数</option><option value="time">投入时间</option><option value="deliverable">明确交付</option></select></label></div>
        <div className="growth-form-row"><label>每周目标<input type="number" min="1" max="100000" value={goalForm.weekly_target} onChange={(event) => setGoalForm({ ...goalForm, weekly_target: event.target.value })} /></label><label>单位<input maxLength="30" value={goalForm.unit_label} onChange={(event) => setGoalForm({ ...goalForm, unit_label: event.target.value })} /></label></div>
        <label>目标日期（可选）<input type="date" value={goalForm.due_date || ''} onChange={(event) => setGoalForm({ ...goalForm, due_date: event.target.value })} /></label>
        <div className="button-row"><button className="button primary" disabled={busy}>{editingGoalId ? '保存目标修改' : '创建目标'}</button>{editingGoalId && <button className="button subtle" type="button" onClick={() => { setEditingGoalId(null); setGoalForm(emptyGoal) }}>取消修改</button>}</div>
      </form>
      {!goals.length ? <p className="growth-empty">暂无目标。</p> : <><div className="goal-list">{goals.filter(item=>item.status==='active').map(renderGoal)}</div><details><summary>其他目标</summary><div className="goal-list">{goals.filter(item=>item.status!=='active').map(renderGoal)}</div></details></>}
    </section>

    <details className="growth-section profile-wide"><summary>类别与关联</summary>
      <div className="growth-section-heading"><div><h3>任务类别与目标关联</h3></div></div>
      <form className="category-add-form" onSubmit={saveCategory}><label>{editingCategoryKey ? '修改类别名称' : '新增类别'}<input required maxLength="80" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="例如：编程、英语、实验" /></label><button className="button secondary" disabled={busy}>{editingCategoryKey ? '保存名称' : '添加类别'}</button>{editingCategoryKey && <button className="button subtle" type="button" onClick={() => { setEditingCategoryKey(null); setCategoryName('') }}>取消</button>}</form>
      <div className="category-list">{categories.map((category) => <article className={`category-row ${category.active ? '' : 'rule-disabled'}`} key={category.key}><div><strong>{category.name}</strong><small>{category.is_default ? '默认类别' : '自定义类别'} · {category.active ? '可用于新任务' : '已停用'}</small></div><div className="button-row"><button className="button subtle" disabled={busy} onClick={() => { setEditingCategoryKey(category.key); setCategoryName(category.name) }}>改名</button><button className="button subtle" disabled={busy || (category.key === 'other' && category.active)} onClick={() => runAction(() => updateTaskCategory(category.key, { active: !category.active }), category.active ? '类别已停用；已有任务及历史仍保留。' : '类别已重新启用。')}>{category.active ? '停用' : '启用'}</button></div></article>)}</div>
      {!tasks.length ? <p className="growth-empty">目前没有待关联的未完成任务。</p> : <div className="task-goal-list">{tasks.map((task) => {
        const context = contexts[task.id] || {}
        return <div className="task-goal-row" key={task.id}><strong>{task.title}</strong><label>任务类别<select value={context.family || 'other'} disabled={busy} onChange={(event) => linkTask(task, context.goal_id || '', event.target.value)}>{categories.filter((item) => item.active || item.key === context.family).map((item) => <option key={item.key} value={item.key}>{item.name}{item.active ? '' : '（已停用）'}</option>)}</select></label><label>关联目标<select value={context.goal_id || ''} disabled={busy} onChange={(event) => linkTask(task, event.target.value, context.family || 'other')}><option value="">暂不关联</option>{goals.filter((goal) => goal.status === 'active').map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select></label></div>
      })}</div>}
    </details>

    <details className="growth-section course-settings profile-wide"><summary><strong>课程与保护时间</strong></summary><TimeRulesPage /></details>
    <details className="growth-section profile-wide"><summary>历史与备份</summary>
      <div className="growth-section-heading"><div><h3>档案历史与数据管理</h3></div></div>
      {!profile?.history?.length ? <p className="growth-empty">尚无资料历史版本。</p> : <details className="insight-history"><summary>查看资料修改版本（{profile.history.length}）</summary><ol className="revision-list">{[...profile.history].reverse().map((revision) => <li key={revision.version}><strong>版本 v{revision.version}</strong><time>{new Date(revision.changed_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</time><p>{revision.direction || '长期方向通过目标管理'}</p></li>)}</ol></details>}
      <div className="button-row"><button className="button secondary" disabled={busy} onClick={exportData}>下载数据备份</button><label className="button subtle file-button">从 JSON 备份恢复<input type="file" accept="application/json,.json" disabled={busy} onChange={importDataFile} /></label></div>
      <p className="helper">应用启动时每天最多自动保存一次 SQLite 安全副本，最多保留 5 份。导入前还会额外保存当前数据库。</p>
      {backups.length ? <ul className="backup-list">{backups.map((backup) => <li key={backup.name}><strong>{backup.name}</strong><span>{Math.ceil(backup.size_bytes / 1024)} KB</span></li>)}</ul> : <p className="growth-empty">尚未生成自动备份；应用下次启动时会检查并创建。</p>}
    </details>
    </WorkspaceChat>
  </section>
}
