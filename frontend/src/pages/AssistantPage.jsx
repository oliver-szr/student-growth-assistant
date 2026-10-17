import { useEffect,useState,useRef } from 'react'
import {createAssistantSession,getAssistantSession,sendAssistantMessage,previewAssistant,confirmAssistant,discardAssistant,explainAssistant,createAssistantRun,getAssistantRun,cancelAssistantRun,retryAssistantRun,getAssistantSettings,getGrowthAttention,replanAssistant,expandAssistantScope} from '../api.js'
import {calendarPosition,visibleSchedule,shanghaiTime,manualAction,focusCards,PRIORITIES} from '../assistant.js'
import { UI_COPY, changeSummary } from '../uiCopy.js'
import WorkbenchLayout from '../components/WorkbenchLayout.jsx'
import ChatMessages from '../components/ChatMessages.jsx'
import SafeMessage from '../components/SafeMessage.jsx'
import ScopedChanges from '../components/ScopedChanges.jsx'
import TaskBreakdown from '../components/TaskBreakdown.jsx'
import '../assistant.css'

const STATUS={ready:'待确认',needs_input:'需要补充信息',conflict:'时间冲突',no_plan:'未找到完整方案',stale:'资料已变化，请重新生成',applied:'已采用方案',discarded:'已放弃方案',superseded:'已有更新方案'}
const PHASE={understanding:'AI 正在理解任务和要求',arranging:'正在计算并校验不同安排',recommending:'AI 正在比较并推荐',finished:'本轮处理完成',cancelled:'本轮已取消'}
const weekDays=['周一','周二','周三','周四','周五','周六','周日']
const stamp=value=>shanghaiTime(value).replace('T',' ')
const short=value=>shanghaiTime(value).slice(11)
const CALENDAR_PIXELS_PER_MINUTE=.7

function Calendar({data,offset=0}){
  const [selected,setSelected]=useState(null)
  const dialog=useRef(null)
  useEffect(()=>{if(selected && !dialog.current.open)dialog.current.showModal()},[selected])
  const p=data.proposal
  const changes=new Set(p?.status==='ready'?p.changes.map(c=>c.ref):[])
  const items=[...data.courses,...visibleSchedule(data.confirmed_items,p)]
  const taskSegments=new Map(),segmentLabels=new Map()
  items.filter(x=>x.kind!=='course').forEach(x=>{if(!taskSegments.has(x.ref))taskSegments.set(x.ref,[]);taskSegments.get(x.ref).push(x)})
  taskSegments.forEach(group=>{if(group.length>1)group.sort((a,b)=>a.start_at.localeCompare(b.start_at)).forEach((x,i)=>segmentLabels.set(`${x.ref}:${x.start_at}:${x.end_at}`,`第 ${i+1}/${group.length} 段`))})
  const dates=weekDays.map((_,i)=>new Date(`${data.week_start}T00:00:00+08:00`).getTime()+(i+offset)*86400000).map(t=>shanghaiTime(t).slice(0,10))
  return <><div className="week-scroll"><div className="week-grid">
    <div className="week-axis"><div className="day-heading">时间</div><div className="hours">{Array.from({length:15},(_,i)=><span key={i} style={{top:i*42}}>{String(i+8).padStart(2,'0')}:00</span>)}</div></div>
    {dates.map((date,i)=><div className="day-column" key={date}><div className={`day-heading ${data.settings.now.startsWith(date)?'today':''}`}><strong>{weekDays[i]}</strong><span>{date.slice(5)}</span></div><div className="day-body">
      {items.filter(x=>calendarPosition(x).date===date).map(x=>{const pos=calendarPosition(x),changed=changes.has(x.ref),past=x.end_at<data.settings.now,label=segmentLabels.get(`${x.ref}:${x.start_at}:${x.end_at}`),locked=(p?.tasks||data.tasks).find(t=>t.ref===x.ref)?.profile?.locked;return <button type="button" onClick={()=>setSelected({...x,label,locked,changed})} aria-label={`${x.title} ${short(x.start_at)}至${short(x.end_at)}，查看详情`} key={`${x.ref}:${x.start_at}:${x.end_at}`} className={`calendar-block ${x.kind==='course'?'course':'task'} ${changed?'changed':''} ${past?'past':''} ${pos.height*CALENDAR_PIXELS_PER_MINUTE<32?'short-block':''}`} style={{top:pos.top*CALENDAR_PIXELS_PER_MINUTE,height:pos.height*CALENDAR_PIXELS_PER_MINUTE}} title={`${x.title}\n${short(x.start_at)}–${short(x.end_at)}${label?` · ${label}`:''}`}><span>{short(x.start_at)}–{short(x.end_at)}</span><strong>{x.title}</strong><small>{x.kind==='course'?'课程':`${changed?'待确认':''}${locked?' · 锁定':''}${label?` · ${label}`:''}`}</small></button>})}
    </div></div>)}
  </div></div><dialog ref={dialog} className="schedule-detail" aria-labelledby="schedule-detail-heading" onClose={()=>setSelected(null)}>
    {selected&&<><h3 id="schedule-detail-heading">{selected.title}</h3><p>{stamp(selected.start_at)}–{short(selected.end_at)}</p><div className="detail-tags"><span>{selected.kind==='course'?'课程':selected.changed?'待确认':'正式任务'}</span>{selected.locked&&<span>锁定</span>}{selected.label&&<span>{selected.label}</span>}</div></>}
    <form method="dialog"><button className="button secondary">关闭</button></form>
  </dialog></>
}

export default function AssistantPage({active, requestedAction, onActionHandled,onManagePreferences,taskTools,refreshVersion=0,onPlanConfirmed}){
  const [weekOffset,setWeekOffset]=useState(0)
  const [data,setData]=useState(null),[text,setText]=useState(''),[pending,setPending]=useState(false),[error,setError]=useState(''),[manual,setManual]=useState(false),[view,setView]=useState('chat'),[explanation,setExplanation]=useState(null),[runState,setRunState]=useState(null),[attention,setAttention]=useState(undefined)
  const [form,setForm]=useState({target:'',title:'',minutes:'60',deadline:'',priority:'normal',task_type:'other'})
  const requestId=useRef(null),manualRequest=useRef(null),watchedRun=useRef(null)
  const handledAction=useRef(null)
  async function load(id){const [d,focus]=await Promise.all([getAssistantSession(id),getGrowthAttention().catch(()=>null)]);setData(d);setAttention(focus?focus.items||[]:null);return d}
  useEffect(()=>{let cancelled=false;async function init(){try{const workspace=await getAssistantSettings();const key=`sga-assistant-session:${workspace.workspace_id}:${workspace.week_start}`;let id=localStorage.getItem(key),d;if(id){try{d=await getAssistantSession(id)}catch(e){if(e.status!==404)throw e}}
    if(!d||d.week_start!==workspace.week_start){const s=await createAssistantSession();id=s.id;d=await getAssistantSession(id)}
    const focus=await getGrowthAttention().catch(()=>null)
    if(!cancelled){localStorage.setItem(key,String(d.id));setData(d);setAttention(focus?focus.items||[]:null)}
  }catch(e){if(!cancelled)setError(e.message)}}init();return()=>{cancelled=true}},[])
  useEffect(()=>{if(active&&data)load(data.id).catch(e=>setError(e.message))},[active,refreshVersion])

  useEffect(()=>{const run=data?.runs?.find(x=>x.status==='running');if(!run||watchedRun.current===run.id)return;watchedRun.current=run.id;setRunState(run);setPending(true);pollRun(run.id).finally(()=>setPending(false))},[data?.id])
  useEffect(()=>{if(!data||!requestedAction||handledAction.current===requestedAction.requestKey)return;handledAction.current=requestedAction.requestKey;act(async()=>{if(requestedAction.text){setText(requestedAction.text);const run=await createAssistantRun(data.id,{client_message_id:crypto.randomUUID(),text:requestedAction.text});setRunState(run);watchedRun.current=run.id;await pollRun(run.id);onActionHandled?.();return}const fields={duration_minutes:requestedAction.durationMinutes};await sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`请为“${requestedAction.title}”把预计剩余时间调整为${requestedAction.durationMinutes}分钟，并生成待确认方案。`,actions:[{op:'update',target:`task:${requestedAction.taskId}`,fields}]});onActionHandled?.()})},[data?.id,requestedAction?.requestKey])
  async function act(fn){if(pending)return;setPending(true);setError('');setExplanation(null);try{const result=await fn();await load(data.id);if(result?.status==='applied')onPlanConfirmed?.()}catch(e){setError(e.message);if(data)await load(data.id).catch(()=>{})}finally{setPending(false)}}
  async function pollRun(id){
    const until=Date.now()+270000
    while(Date.now()<until){
      const next=await getAssistantRun(id);setRunState(next)
      if(next.status!=='running'){await load(data.id);if(next.status==='completed'){setText('');requestId.current=null}else if(next.status==='failed')setError(next.error_code==='STALE_CANDIDATE'?'任务或偏好已变化，请重新发送这条需求。':'AI 处理未完成，输入已保留，可重试或改用手动添加。');return next}
      await new Promise(resolve=>setTimeout(resolve,700))
    }
    setError('AI 处理仍在进行。你可以继续等待或取消；输入已保留。')
  }
  async function send(e){
    e.preventDefault();if(!text.trim()||!data||pending)return
    const input=text;requestId.current=requestId.current||crypto.randomUUID();setPending(true);setError('');setRunState({status:'running',phase:'understanding'})
    try{const run=await createAssistantRun(data.id,{client_message_id:requestId.current,text:input});setRunState(run);watchedRun.current=run.id;await pollRun(run.id)}catch(e){setError(e.message);await load(data.id).catch(()=>{})}finally{setPending(false)}
  }
  async function cancelRun(){if(!runState?.id)return;try{const stopped=await cancelAssistantRun(runState.id);setRunState(stopped);await load(data.id)}catch(e){setError(e.message)}}
  async function retryRun(){if(!runState?.id)return;setPending(true);setError('');try{const retried=await retryAssistantRun(runState.id);setRunState(retried);await pollRun(retried.id)}catch(e){setError(e.message)}finally{setPending(false)}}
  function changeForm(v){manualRequest.current=null;setForm(v)}
  function edit(t){manualRequest.current=null;setForm({target:t?.ref||'',title:t?.title||'',minutes:String(t?.duration_minutes||60),deadline:t?.deadline?shanghaiTime(t.deadline):`${data.settings.now.slice(0,10)}T20:00`,priority:t?.priority||'normal',task_type:t?.task_type||'other',splittable:t?.profile?.splittable||false,min_block_minutes:t?.profile?.min_block_minutes||30,max_segments:t?.profile?.max_segments||4});setManual(true);setView('chat')}
  async function manualSubmit(e){
    e.preventDefault()
    const action=manualAction(form)
    if(!manualRequest.current)manualRequest.current={id:crypto.randomUUID(),proposal: data.proposal&&!['applied','discarded','superseded','stale'].includes(data.proposal.status)?data.proposal.id:null,action}
    const req=manualRequest.current
    await act(async()=>{
      if(req.proposal)await previewAssistant(req.proposal,{client_message_id:req.id,actions:[req.action]})
      else await sendAssistantMessage(data.id,{client_message_id:req.id,text:`手动确认任务：${form.title}`,actions:[req.action]})
      manualRequest.current=null;setManual(false)
    })
  }

  if(!data)return <section className="assistant-loading" aria-live="polite">{error||'正在加载课程与任务…'}{error&&<button onClick={()=>location.reload()}>重新加载</button>}</section>
  const p=data.proposal,live=p&&!['applied','discarded','superseded','stale'].includes(p.status),library=live?p.tasks:data.tasks
  const preferenceLabel={balanced:'均衡',preference:'习惯优先',stable:'少改动'}
  const recommendationTitle=p?.recommendation?.source==='user_selected'?'当前选择方案：':p?.recommendation?.source==='program_fallback'?'程序校验方案：':p?.recommendation?.source==='ai'?'AI 推荐方案：':'已校验方案：'
  const focusedTasks=focusCards(attention)
  const categoryName=(key)=>data.task_categories?.find((item)=>item.key===key)?.name||key||'其他'
  return <section className="assistant-workspace" aria-labelledby="planning-heading">
    <div className="growth-page-heading planning-page-heading"><div><h2 id="planning-heading">规划</h2></div></div>
    <TaskBreakdown onCreated={()=>{load(data.id).catch(e=>setError(e.message));onPlanConfirmed?.()}} />
    <section className="today-focus" aria-labelledby="today-focus-heading"><div className="today-focus-intro"><h3 id="today-focus-heading">优先处理</h3></div>{attention===undefined?<p className="today-focus-empty" role="status">正在整理任务轻重缓急…</p>:attention===null?<p className="today-focus-empty" role="status">动态优先级暂时不可用；可以继续查看下面的课程和任务安排。</p>:focusedTasks.length?<ol>{focusedTasks.map(item=><li key={item.task_id} className={`today-focus-item urgency-${item.urgency}`}><div><strong>{item.title}</strong><span className="today-urgency">{item.urgency_label}</span></div><p>截止 {stamp(item.deadline)}</p>{item.available_start_count===0 && <p className="risk-label">无法安排</p>}<p>剩余 {item.remaining_minutes ?? item.duration_minutes ?? data.tasks.find(t=>t.ref===`task:${item.task_id}`)?.duration_minutes ?? '待核对'} 分钟 · {item.importance_label}</p><details><summary>详情</summary><p>{item.reason}</p><small>{item.goal?.title}</small></details></li>)}</ol>:<p className="today-focus-empty">目前没有待处理任务。</p>}</section>
    <WorkbenchLayout view={view} onViewChange={setView} resultLabel="日程" chat={
      <aside className="chat-panel"><div className="panel-heading"><h3>规划助手</h3><button type="button" className="manual-link" disabled={pending} onClick={()=>act(()=>replanAssistant(data.id))}>局部重规划</button><button type="button" className="manual-link preference-entry" onClick={onManagePreferences}>安排偏好</button>{live&&<button type="button" className="manual-link" onClick={()=>{setView('result');requestAnimationFrame(()=>document.getElementById('planning-proposal')?.scrollIntoView({block:'start'}))}}>查看调整</button>}</div>
        <ChatMessages className="chat-messages" revision={data.messages.at(-1)?.id}>{!data.messages.length&&<div className="assistant-bubble"><p>例如：周五20:00前交报告，预计两小时，尽量周四下午做。</p></div>}{data.messages.map(m=><div key={m.id} className={`${m.role}-bubble`}><small>{m.role==='user'?'你':'规划助手'}</small><SafeMessage text={m.text}/></div>)}</ChatMessages>
        {runState?.status==='running'&&<div className="run-progress" role="status"><span>{PHASE[runState.phase]||'正在处理'}</span><button type="button" disabled={!runState?.id} onClick={cancelRun}>取消</button></div>}
        {runState?.status==='failed'&&<div className="run-progress error" role="status"><span>{runState.error_code==='STALE_CANDIDATE'?'资料已变化，请重新发送本轮需求':'AI 服务暂时未完成，可重试；输入已保留'}</span>{runState.error_code!=='STALE_CANDIDATE'&&<button type="button" onClick={retryRun}>重试</button>}</div>}
        {error&&runState?.status!=='failed'&&<p className="assistant-error" role="alert">{error}</p>}
        <form className="chat-compose" onSubmit={send}><label htmlFor="chat-input">任务或调整</label><textarea id="chat-input" value={text} onChange={e=>{setText(e.target.value);requestId.current=null}} disabled={pending} placeholder="输入任务或调整要求" maxLength={2000}/><div><button className="manual-link" type="button" onClick={()=>edit()} disabled={pending}>手动添加</button><button className="button primary" disabled={pending||!text.trim()}>发送</button></div></form>
        {manual&&<form className="manual-task" onSubmit={manualSubmit}><h4>任务信息</h4><label>选择任务<select value={form.target} onChange={e=>{const t=library.find(t=>t.ref===e.target.value);edit(t)}}><option value="">新增任务</option>{library.filter(t=>t.status==='todo').map(t=><option key={t.ref} value={t.ref}>{t.title||'待补充任务'}</option>)}</select></label><label>名称<input required value={form.title} onChange={e=>changeForm({...form,title:e.target.value})}/></label><label>任务类型<select value={form.task_type} onChange={e=>changeForm({...form,task_type:e.target.value})}>{(data.task_categories||[]).filter(item=>item.active).map(item=><option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>剩余时长（分钟）<input type="number" min="5" step="5" required value={form.minutes} onChange={e=>changeForm({...form,minutes:e.target.value})}/></label><label className="split-toggle"><span className="split-toggle-copy"><strong>允许分段安排</strong><small>需要时，可分成几个时段完成</small></span><span className="split-toggle-control"><input type="checkbox" role="switch" aria-label="允许分段安排" checked={Boolean(form.splittable)} onChange={e=>changeForm({...form,splittable:e.target.checked})}/><span className="split-toggle-track" aria-hidden="true"/></span></label>{form.splittable&&<><label>每段至少分钟<input type="number" min="5" step="5" max="840" value={form.min_block_minutes||30} onChange={e=>changeForm({...form,min_block_minutes:Number(e.target.value)})}/></label><label>最多分几段<input type="number" min="1" max="8" value={form.max_segments||4} onChange={e=>changeForm({...form,max_segments:Number(e.target.value)})}/></label></>}<label>截止时间<input type="datetime-local" required value={form.deadline} onChange={e=>changeForm({...form,deadline:e.target.value})}/></label><label>重要程度<select value={form.priority} onChange={e=>changeForm({...form,priority:e.target.value})}>{Object.entries(PRIORITIES).map(([v,t])=><option key={v} value={v}>{t}</option>)}</select></label><div className="button-row"><button className="button primary" disabled={pending}>生成候选</button><button type="button" className="button subtle" onClick={()=>setManual(false)}>收起</button></div></form>}
      </aside>}>
      <div className="schedule-panel"><div className="panel-heading schedule-heading"><h3>{weekOffset?'下周日程':'本周日程'}</h3><div className="week-switch" role="group" aria-label="选择日程周"><button type="button" aria-label="上一周" title="上一周" disabled={weekOffset===0} onClick={()=>setWeekOffset(value=>Math.max(0,value-7))}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></button><span className="week-switch-range" aria-live="polite">{Array.from({length:2},(_,i)=>shanghaiTime(new Date(`${data.week_start}T00:00:00+08:00`).getTime()+(weekOffset+i*6)*86400000).slice(5,10).replace("-",".")).join("–")}</span><button type="button" aria-label="下一周" title="下一周" disabled={weekOffset===7} onClick={()=>setWeekOffset(value=>Math.min(7,value+7))}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg></button></div><div className="calendar-legend"><span className="course-key">固定课程</span><span className="task-key">正式任务</span><span className="change-key">待确认调整</span></div></div><Calendar data={data} offset={weekOffset}/>
      {data.warnings.length>0&&<details className="course-warnings"><summary>课表有 {data.warnings.length} 项待补充</summary>{data.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}</div>
    {p&&<section id="planning-proposal" className={`proposal-panel ${p.status}`} aria-label="本轮方案"><div className="proposal-heading"><h3>{STATUS[p.status]||p.status}</h3><span>{p.window_start && `${p.window_start} 至 ${shanghaiTime(Date.parse(`${p.window_end_exclusive}T00:00:00+08:00`)-86400000).slice(0,10)}`}</span></div>
      {live && !p.change_groups && <p className="proposal-change-count">{changeSummary(p.changes)}</p>}
      {live&&<ScopedChanges proposal={p} pending={pending} onExpand={()=>act(()=>expandAssistantScope(p.id))} onDecline={()=>act(()=>discardAssistant(p.id))}/>}
      {p.questions.map((q,i)=><p key={i}>{q}</p>)}
      {p.status==='stale'&&<p className="diagnostic">任务或课程资料已变化，本轮旧候选已停用。请重新描述修改要求以读取最新资料。</p>}
      {live&&<details><summary>任务信息</summary>{p.actions.map(a=>{const t=p.tasks.find(t=>t.ref===a.target);return t&&<div className="understood-task" key={a.target}><strong>{t.title||'待补充任务'}</strong><span>{categoryName(t.task_type)}　{t.duration_minutes?`${t.duration_minutes} 分钟`:'时长待补充'}　{t.deadline?`截止 ${stamp(t.deadline)}`:'截止待补充'}　{PRIORITIES[t.priority]}</span><button onClick={()=>edit(t)} disabled={pending}>编辑</button></div>})}</details>}
      {live&&p.preference_updates&&<p className="preference-staged">本轮偏好修改仅在采用方案后保存。</p>}
      {live&&p.temporary_preferences&&(p.temporary_preferences.blocked_windows||[]).map((w,i)=><p className="preference-staged" key={`blocked-${i}`}>本轮临时限制：{stamp(w.start_at)}–{short(w.end_at)}，不会写入长期偏好。</p>)}
      {live&&p.temporary_preferences&&(p.temporary_preferences.avoid_windows||[]).map((w,i)=><p className="preference-staged" key={`avoid-${i}`}>本轮临时时段偏好：{stamp(w.start_at)}–{short(w.end_at)}，仅影响这次方案。</p>)}
      {!p.change_groups&&p.changes.length>0&&<ul className="change-list">{p.changes.map(c=><li key={`${c.ref}:${c.after?.start_at||c.before?.start_at}`}><strong>{c.title}</strong><span>{c.kind==='removed'?`${stamp(c.before.start_at)}：从未来日程移除`:<>{c.before?`${(c.before_segments||[c.before]).map(x=>`${stamp(x.start_at)}–${short(x.end_at)}`).join('；')} → `:'新增：'}{(c.after_segments||[c.after]).map(x=>`${stamp(x.start_at)}–${short(x.end_at)}`).join('；')}</>}</span><small>截止 {stamp(c.deadline)}，{PRIORITIES[c.priority]}</small></li>)}</ul>}
      {(p.unmet_preferences||[]).map(u=><p className="diagnostic" key={u.ref}>{u.title}：时间偏好未满足，当前采用其他可行时段，可继续聊天调整。</p>)}
      {p.diagnostics.filter(d=>!p.change_groups||!d.ref).map((d,i)=><p className="diagnostic" key={i}>{d.message}</p>)}
      {p.status==='conflict'&&p.alternatives.map((a,i)=><button key={i} className="button subtle" disabled={pending} onClick={()=>act(()=>previewAssistant(p.id,{alternative_index:i}))}>改为 {stamp(a.start_at)}–{short(a.end_at)}</button>)}
      {p.status==='ready'&&<><div className="candidate-options"><h4>{recommendationTitle}{preferenceLabel[p.selected_strategy]||'综合安排'}</h4>{p.recommendation?.source==='program_fallback'&&<p className="diagnostic">AI 推荐服务暂不可用，当前展示程序校验过的均衡方案。</p>}{p.recommendation?.source==='ai'&&p.recommendation?.reason_text?.map((reason,i)=><span className="reason-chip" key={i}>{reason}</span>)}{(p.candidate_options||[]).map((option,index)=><button type="button" key={option.candidate_id} className={`candidate-option ${p.selected_candidate_id===option.candidate_id?'selected':''}`} aria-pressed={p.selected_candidate_id===option.candidate_id} onClick={()=>act(()=>previewAssistant(p.id,{candidate_id:option.candidate_id}))} disabled={pending}><strong>方案 {index+1} · {preferenceLabel[option.strategy]||'备选方案'}{p.selected_candidate_id===option.candidate_id&&<span className="selected-label">已选</span>}</strong><span>{changeSummary(option.changes)}</span><small>{option.metrics.preference_misses_weight>0 ? '部分偏好未满足' : '偏好已满足'}{option.metrics.deadline_buffer_shortfall_hours>0 ? ' · 截止缓冲不足' : ''}</small></button>)}</div><details className="fact-summary"><summary>方案详情</summary><SafeMessage text={p.summary}/></details><div className="button-row proposal-actions"><button className="button primary" disabled={pending} onClick={()=>act(()=>confirmAssistant(p.id))}>{UI_COPY.adopt}</button><button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>{UI_COPY.discard}</button><button className="button subtle" disabled={pending} onClick={async()=>{setPending(true);try{setExplanation(await explainAssistant(p.id))}catch(e){setError(e.message)}finally{setPending(false)}}}>AI 解释调整</button></div></>}
      {live&&p.status!=='ready'&&<button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>{UI_COPY.discard}</button>}
      {explanation&&<div className="fact-summary">{explanation.source==='ai'?'AI 解释':'事实摘要（AI解释暂不可用）'}：<SafeMessage text={explanation.text}/></div>}
      {p.notices.length>0&&<details><summary>任务与安排提示</summary>{[...new Set(p.notices)].map((n,i)=><p key={i}>{n}</p>)}</details>}
    </section>}
    </WorkbenchLayout>
    <details className="task-memory workspace-details"><summary>任务与执行 · {data.tasks.filter(t=>t.status==='todo').length} 项未完成任务 {live?'· 待确认':''}</summary><h3>任务概览</h3><div className="memory-list">{data.tasks.map(t=><div key={t.ref}><strong>{t.title}</strong><span>{categoryName(t.task_type)}　截止 {stamp(t.deadline)}　剩余 {t.duration_minutes} 分钟　{PRIORITIES[t.priority]}　{t.status==='done'?'已完成':t.status==='cancelled'?'已取消':'待完成'}　{t.profile?.locked?'已锁定':''}</span><button disabled={pending} onClick={()=>edit(t)}>修改</button><button disabled={pending||t.status!=='todo'||t.profile?.locked} onClick={()=>act(()=>replanAssistant(data.id,t.ref))}>重新安排</button><button disabled={pending} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`${t.title}：${t.profile?.locked?'解锁':'锁定'}安排`,actions:[{op:'update',target:t.ref,fields:{profile:{locked:!t.profile?.locked}}}]}))}>{t.profile?.locked?'解锁':'锁定'}</button><button disabled={pending||t.status!=='todo'} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`完成 ${t.title}`,actions:[{op:'update',target:t.ref,fields:{status:'done'}}]}))}>完成</button></div>)}</div><h3>执行记录</h3>{taskTools}</details>
  </section>
}
