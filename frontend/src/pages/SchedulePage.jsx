import { lazy,Suspense,useEffect,useState } from 'react'
import { getCalendarEvents,getGrowthAttention } from '../api.js'
import { focusCards,shanghaiTime } from '../assistant.js'
import { shiftDate,dayPreviewData } from '../calendar.js'
import { shiftPreviewDate } from '../workbench.js'
import { Calendar } from './AssistantPage.jsx'
import TaskBreakdown from '../components/TaskBreakdown.jsx'
import EditRecovery,{useEditRecovery} from '../components/EditRecovery.jsx'

const CalendarWorkspace=lazy(()=>import('../components/CalendarWorkspace.jsx'))

// Formal views read workspace facts directly. No session ID or chat proposal
// participates in their loading, errors, date selection or refresh lifecycle.
export default function SchedulePage({settings,active,auxiliaryActive,refreshVersion,taskTools,onDataChanged,onOpenTask,renderWorkbench}){
  const today=settings.now.slice(0,10),last=shiftDate(settings.week_start,13)
  const [visited,setVisited]=useState(active),[previewDate,setPreviewDate]=useState(today)
  const [preview,setPreview]=useState(null),[previewError,setPreviewError]=useState(''),[retry,setRetry]=useState(0)
  const [attention,setAttention]=useState(undefined)
  const recovery=useEditRecovery({workspace:settings.workspace_id,resource:'auxiliary-schedule',base:settings.week_start,
    value:{previewDate},dirty:true,automatic:true,restore:value=>{
      if(typeof value.previewDate==='string'&&value.previewDate>=settings.week_start&&value.previewDate<=last)setPreviewDate(value.previewDate)
    }})
  useEffect(()=>{if(active)setVisited(true)},[active])
  useEffect(()=>{
    if(!active)return
    let alive=true
    getGrowthAttention().then(value=>{if(alive)setAttention(value.items||[])}).catch(()=>{if(alive)setAttention(null)})
    return()=>{alive=false}
  },[active,refreshVersion])
  useEffect(()=>{
    if(!auxiliaryActive)return
    let alive=true;setPreviewError('')
    getCalendarEvents(previewDate,shiftDate(previewDate,1)).then(value=>{if(alive)setPreview({date:previewDate,data:dayPreviewData(value,settings)})}).catch(cause=>{if(alive)setPreviewError(cause.message)})
    return()=>{alive=false}
  },[auxiliaryActive,previewDate,refreshVersion,retry])
  const focused=focusCards(attention)
  const auxiliarySchedule=<section className="schedule-panel v2-day-preview" aria-label="单日日程预览">
    <EditRecovery recovery={recovery} label="辅助日程日期"/>
    <div className="panel-heading v2-preview-heading"><h3>{previewDate===today?'今日日程':'单日日程'}</h3>
      <div className="v2-preview-date"><button type="button" aria-label="辅助日程上一天" disabled={previewDate<=settings.week_start} onClick={()=>setPreviewDate(shiftPreviewDate(previewDate,-1,settings.week_start,last))}>‹</button><label><input aria-label="辅助日程日期" type="date" min={settings.week_start} max={last} value={previewDate} onChange={e=>{if(e.target.value>=settings.week_start&&e.target.value<=last)setPreviewDate(e.target.value)}}/></label><button type="button" aria-label="辅助日程下一天" disabled={previewDate>=last} onClick={()=>setPreviewDate(shiftPreviewDate(previewDate,1,settings.week_start,last))}>›</button></div>
      <button type="button" className="button subtle" onClick={()=>setPreviewDate(today)}>回到今天</button>
    </div>
    {previewError&&<p role="status">日程预览暂时无法更新。<button className="button subtle" onClick={()=>setRetry(v=>v+1)}>重试预览</button></p>}
    {preview?.date===previewDate?<Calendar data={preview.data} selectedDate={previewDate} formalOnly/>:!previewError&&<p role="status">正在读取单日日程…</p>}
    <p className="v2-calendar-note">仅显示正式课程与任务；日期与中央日历独立。</p>
  </section>
  return renderWorkbench({auxiliarySchedule,children:<div className="assistant-workspace v2-planning-content">
    {visited&&<Suspense fallback={<p role="status">正在加载完整日历…</p>}><CalendarWorkspace workspace={settings.workspace_id} today={today} active={active} refreshVersion={refreshVersion} onOpenTask={onOpenTask}/></Suspense>}
    <TaskBreakdown active={active} refreshVersion={refreshVersion} recoveryWorkspace={settings.workspace_id} onCreated={onDataChanged}/>
    <section className="today-focus" aria-labelledby="today-focus-heading"><div className="today-focus-intro"><h3 id="today-focus-heading">优先处理</h3></div>
      {attention===undefined?<p role="status" className="today-focus-empty">正在整理任务轻重缓急…</p>:attention===null?<p role="status" className="today-focus-empty">动态优先级暂时不可用；日历和任务仍可查看。</p>:focused.length?<ol>{focused.map(item=><li key={item.task_id} className={`today-focus-item urgency-${item.urgency}`}><div><strong>{item.title}</strong><span className="today-urgency">{item.urgency_label}</span></div><p>截止 {shanghaiTime(item.deadline).replace('T',' ')}</p>{item.available_start_count===0&&<p className="risk-label">无法安排</p>}<p>剩余 {item.remaining_minutes??item.duration_minutes??'待核对'} 分钟 · {item.importance_label}</p><details><summary>详情</summary><p>{item.reason}</p><small>{item.goal?.title}</small></details></li>)}</ol>:<p className="today-focus-empty">目前没有待处理任务。</p>}
    </section>
    <details className="task-memory workspace-details"><summary>任务与执行</summary>{taskTools}</details>
  </div>})
}
