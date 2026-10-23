import { lazy,Suspense,useEffect,useRef,useState } from 'react'
import { getCalendarEvents,getGrowthAttention,createAttentionDraft } from '../api.js'
import { focusCards,workDuration,attentionDeadline,recommendationLabel } from '../assistant.js'
import { shiftDate,dayPreviewData } from '../calendar.js'
import { shiftPreviewDate,editKey } from '../workbench.js'
import { Calendar } from './AssistantPage.jsx'
import TaskBreakdown from '../components/TaskBreakdown.jsx'
import EditRecovery,{useEditRecovery} from '../components/EditRecovery.jsx'

const CalendarWorkspace=lazy(()=>import('../components/CalendarWorkspace.jsx'))

// Formal views read workspace facts directly. No session ID or chat proposal
// participates in their loading, errors, date selection or refresh lifecycle.
export default function SchedulePage({settings,active,auxiliaryActive,refreshVersion,taskTools,onDataChanged,onOpenTask,onOpenDraft,renderWorkbench}){
  const today=settings.now.slice(0,10),last=shiftDate(settings.week_start,13)
  const [visited,setVisited]=useState(active),[previewDate,setPreviewDate]=useState(today)
  const [preview,setPreview]=useState(null),[previewError,setPreviewError]=useState(''),[retry,setRetry]=useState(0)
  const [attention,setAttention]=useState(null),[attentionError,setAttentionError]=useState(''),[attentionLoading,setAttentionLoading]=useState(true),[attentionRetry,setAttentionRetry]=useState(0)
  const [drafts,setDrafts]=useState({}),[creating,setCreating]=useState(null),[draftError,setDraftError]=useState('')
  const pending=useRef(null),mounted=useRef(true)
  const pendingKey=editKey(settings.workspace_id,'attention-request')
  useEffect(()=>{mounted.current=true;try{pending.current=JSON.parse(sessionStorage.getItem(pendingKey))}catch{}return()=>{mounted.current=false}},[pendingKey])
  useEditRecovery({workspace:settings.workspace_id,resource:'attention-draft-references',base:'attention-v1',value:{drafts},dirty:Object.keys(drafts).length>0,automatic:true,
    restore:value=>{if(value.drafts&&typeof value.drafts==='object')setDrafts(Object.fromEntries(Object.entries(value.drafts).filter(([task,id])=>/^\d+$/.test(task)&&Number.isSafeInteger(id)&&id>0)))}})
  const recovery=useEditRecovery({workspace:settings.workspace_id,resource:'auxiliary-schedule',base:settings.week_start,
    value:{previewDate},dirty:true,automatic:true,restore:value=>{
      if(typeof value.previewDate==='string'&&value.previewDate>=settings.week_start&&value.previewDate<=last)setPreviewDate(value.previewDate)
    }})
  useEffect(()=>{if(active)setVisited(true)},[active])
  useEffect(()=>{
    if(!active)return
    let alive=true,inflight=false
    const read=async()=>{
      if(inflight||document.hidden)return
      inflight=true;setAttentionLoading(true);setAttentionError('')
      try{const value=await getGrowthAttention();if(alive)setAttention(value)}
      catch(cause){if(alive)setAttentionError(cause.message)}
      finally{inflight=false;if(alive)setAttentionLoading(false)}
    }
    read();const timer=setInterval(read,60000)
    window.addEventListener('focus',read)
    return()=>{alive=false;clearInterval(timer);window.removeEventListener('focus',read)}
  },[active,refreshVersion,attentionRetry])
  async function generate(item,recommendation,retryPending=false){
    if(creating!==null)return
    if(pending.current&&!retryPending){setDraftError('上次生成结果尚未核实，请先重试原请求。');return}
    const request=retryPending?pending.current:{taskId:item.task_id,payload:{client_request_id:crypto.randomUUID(),expected_revision:attention.revision,recommendation_key:recommendation.key}}
    if(!request)return
    pending.current=request;try{sessionStorage.setItem(pendingKey,JSON.stringify(request))}catch{}
    setCreating(request.taskId);setDraftError('')
    try{
      const draft=await createAttentionDraft(request.taskId,request.payload)
      if(!mounted.current)return
      setDrafts(old=>({...old,[request.taskId]:draft.id}));pending.current=null
      try{sessionStorage.removeItem(pendingKey)}catch{}
      onOpenDraft?.(draft.id)
    }catch(cause){
      if(!mounted.current)return
      // A definitive rejection can be retried after a fresh choice. Lost replies
      // keep the same request identity, including across a browser refresh.
      if(cause.status>=400&&cause.status<500){pending.current=null;try{sessionStorage.removeItem(pendingKey)}catch{}}
      setDraftError(cause.message)
      if(cause.status===409)setAttentionRetry(v=>v+1)
    }finally{if(mounted.current)setCreating(null)}
  }
  useEffect(()=>{
    if(!auxiliaryActive)return
    let alive=true;setPreviewError('')
    getCalendarEvents(previewDate,shiftDate(previewDate,1)).then(value=>{if(alive)setPreview({date:previewDate,data:dayPreviewData(value,settings)})}).catch(cause=>{if(alive)setPreviewError(cause.message)})
    return()=>{alive=false}
  },[auxiliaryActive,previewDate,refreshVersion,retry])
  const focused=focusCards(attention?.items)
  const auxiliarySchedule=<section className="schedule-panel v2-day-preview" aria-label="单日日程预览">
    <EditRecovery recovery={recovery} label="辅助日程日期"/>
    <div className="panel-heading v2-preview-heading"><h3>{previewDate===today?'今日日程':'单日日程'}</h3>
      <div className="v2-preview-date"><button type="button" aria-label="辅助日程上一天" disabled={previewDate<=settings.week_start} onClick={()=>setPreviewDate(shiftPreviewDate(previewDate,-1,settings.week_start,last))}>‹</button><label><input aria-label="辅助日程日期" type="date" min={settings.week_start} max={last} value={previewDate} onChange={e=>{if(e.target.value>=settings.week_start&&e.target.value<=last)setPreviewDate(e.target.value)}}/></label><button type="button" aria-label="辅助日程下一天" disabled={previewDate>=last} onClick={()=>setPreviewDate(shiftPreviewDate(previewDate,1,settings.week_start,last))}>›</button></div>
      <button type="button" className="button subtle" onClick={()=>setPreviewDate(today)}>回到今天</button>
    </div>
    {previewError&&<p role="status">{previewError}<button className="button subtle" onClick={()=>setRetry(v=>v+1)}>重试预览</button></p>}
    {preview?.date===previewDate?<Calendar data={preview.data} selectedDate={previewDate} formalOnly/>:!previewError&&<p role="status">正在读取单日日程…</p>}
    <p className="v2-calendar-note">仅显示正式课程与任务；日期与中央日历独立。</p>
  </section>
  return renderWorkbench({auxiliarySchedule,children:<div className="assistant-workspace v2-planning-content">
    {visited&&<Suspense fallback={<p role="status">正在加载完整日历…</p>}><CalendarWorkspace workspace={settings.workspace_id} today={today} active={active} refreshVersion={refreshVersion} onOpenTask={onOpenTask}/></Suspense>}
    <TaskBreakdown active={active} refreshVersion={refreshVersion} recoveryWorkspace={settings.workspace_id} onCreated={onDataChanged}/>
    <section className="today-focus" aria-labelledby="today-focus-heading"><div className="today-focus-intro"><h3 id="today-focus-heading">优先处理</h3></div>
      {attentionError?<p className="error-box" role="alert">{attentionError}<button className="button subtle" onClick={()=>setAttentionRetry(v=>v+1)}>重试任务建议</button></p>:attentionLoading&&!attention?<p role="status" className="today-focus-empty">正在读取任务与可用时间…</p>:focused.length?<ol>{focused.map(item=><li key={item.task_id} className={`today-focus-item urgency-${item.urgency}`} data-attention-task={item.task_id}>
        <div className="attention-title"><button className="attention-task-link" onClick={()=>onOpenTask?.(item.task_id)}>{item.title}</button><span className="today-urgency">{item.urgency_label}</span></div>
        <p className="attention-meta"><time dateTime={item.deadline}>{attentionDeadline(item.deadline,attention.now)}</time><span>预计还需{workDuration(item.remaining_minutes??item.duration_minutes)}</span></p>
        <p className="attention-reason">{item.reason}</p>
        {drafts[item.task_id]?<button className="button secondary" onClick={()=>onOpenDraft?.(drafts[item.task_id])}>查看建议草案</button>:item.recommendations?.length>0&&<div className="attention-options" aria-label={`${item.title}的建议时间`}>{item.recommendations.map(rec=><button className="button secondary" key={rec.key} disabled={creating!==null||attentionLoading} onClick={()=>generate(item,rec)}>生成 {recommendationLabel(rec,attention.now)} 草案</button>)}</div>}
        <details><summary>可用时间与任务详情</summary><p>重要程度：{item.importance_label}{item.goal?`；关联目标：${item.goal.title}`:''}</p><p>{item.free_interval_count}段空闲，共{workDuration(item.free_minutes)}；{item.fitting_interval_count}段可连续排下，{item.available_start_count}个合法连续起点。展示{item.recommendation_count}种建议。</p><p className="helper">{item.count_note}</p>{item.free_intervals?.map(span=><p key={span.start_at}>{recommendationLabel({items:[span]},attention.now)} · {workDuration(span.minutes)}</p>)}</details>
      </li>)}</ol>:<p className="today-focus-empty">目前没有待处理任务。</p>}
      {creating!==null&&<p role="status">正在核对时间并生成草案…</p>}{draftError&&<p className="error-box" role="alert">{draftError}</p>}
      {pending.current&&creating===null&&<button className="button secondary" onClick={()=>generate(null,null,true)}>核实或重试上次生成</button>}
      {focused.some(item=>item.recommendation_count>0)&&<p className="helper">生成后在右侧核对；确认采用才会加入正式日程。</p>}
    </section>
    <details className="task-memory workspace-details"><summary>任务与执行</summary>{taskTools}</details>
  </div>})
}
