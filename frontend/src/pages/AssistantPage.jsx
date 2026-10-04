import { useEffect,useState,useRef } from 'react'
import {createAssistantSession,getAssistantSession,sendAssistantMessage,previewAssistant,confirmAssistant,discardAssistant,explainAssistant,createAssistantRun,getAssistantRun,cancelAssistantRun,retryAssistantRun,getAssistantSettings,getGrowthAttention} from '../api.js'
import {calendarPosition,visibleSchedule,shanghaiTime,manualAction,focusCards,PRIORITIES} from '../assistant.js'
import SafeMessage from '../components/SafeMessage.jsx'
import '../assistant.css'

const STATUS={ready:'待确认方案',needs_input:'需要补充信息',conflict:'时间冲突',no_plan:'未找到完整方案',stale:'资料已变化，请重新生成',applied:'已采用方案',discarded:'已放弃方案',superseded:'已有更新方案'}
const PHASE={understanding:'AI 正在理解任务和要求',arranging:'正在计算并校验不同安排',recommending:'AI 正在比较并推荐',finished:'本轮处理完成',cancelled:'本轮已取消'}
const weekDays=['周一','周二','周三','周四','周五','周六','周日']
const stamp=value=>shanghaiTime(value).replace('T',' ')
const short=value=>shanghaiTime(value).slice(11)
const CALENDAR_PIXELS_PER_MINUTE=.7

function Calendar({data}){
  const p=data.proposal
  const changes=new Set(p?.status==='ready'?p.changes.map(c=>c.ref):[])
  const items=[...data.courses,...visibleSchedule(data.confirmed_items,p)]
  const dates=weekDays.map((_,i)=>new Date(`${data.week_start}T00:00:00+08:00`).getTime()+i*86400000).map(t=>shanghaiTime(t).slice(0,10))
  return <div className="week-scroll"><div className="week-grid">
    <div className="week-axis"><div className="day-heading">时间</div><div className="hours">{Array.from({length:15},(_,i)=><span key={i} style={{top:i*42}}>{String(i+8).padStart(2,'0')}:00</span>)}</div></div>
    {dates.map((date,i)=><div className="day-column" key={date}><div className={`day-heading ${data.settings.now.startsWith(date)?'today':''}`}><strong>{weekDays[i]}</strong><span>{date.slice(5)}</span></div><div className="day-body">
      {items.filter(x=>calendarPosition(x).date===date).map((x,j)=>{const pos=calendarPosition(x),changed=changes.has(x.ref),past=x.end_at<data.settings.now;return <div key={`${x.ref}-${j}`} className={`calendar-block ${x.kind==='course'?'course':'task'} ${changed?'changed':''} ${past?'past':''}`} style={{top:pos.top*CALENDAR_PIXELS_PER_MINUTE,height:pos.height*CALENDAR_PIXELS_PER_MINUTE}} title={`${x.title}\n${short(x.start_at)}–${short(x.end_at)}`}><span>{short(x.start_at)}–{short(x.end_at)}</span><strong>{x.title}</strong><small>{x.kind==='course'?'固定课程':changed?'待确认调整':'正式任务'}</small></div>})}
    </div></div>)}
  </div></div>
}

export default function AssistantPage({active, requestedAction, onActionHandled}){
  const [data,setData]=useState(null),[text,setText]=useState(''),[pending,setPending]=useState(false),[error,setError]=useState(''),[manual,setManual]=useState(false),[view,setView]=useState('chat'),[explanation,setExplanation]=useState(null),[runState,setRunState]=useState(null),[attention,setAttention]=useState(undefined)
  const [form,setForm]=useState({target:'',title:'',minutes:'60',deadline:'',priority:'normal',task_type:'other'})
  const messagesEnd=useRef(null),requestId=useRef(null),manualRequest=useRef(null),watchedRun=useRef(null)
  const handledAction=useRef(null)
  async function load(id){const [d,focus]=await Promise.all([getAssistantSession(id),getGrowthAttention().catch(()=>null)]);setData(d);setAttention(focus?focus.items||[]:null);return d}
  useEffect(()=>{let cancelled=false;async function init(){try{const workspace=await getAssistantSettings();const key=`sga-assistant-session:${workspace.workspace_id}:${workspace.week_start}`;let id=localStorage.getItem(key),d;if(id){try{d=await getAssistantSession(id)}catch(e){if(e.status!==404)throw e}}
    if(!d||d.week_start!==workspace.week_start){const s=await createAssistantSession();id=s.id;d=await getAssistantSession(id)}
    const focus=await getGrowthAttention().catch(()=>null)
    if(!cancelled){localStorage.setItem(key,String(d.id));setData(d);setAttention(focus?focus.items||[]:null)}
  }catch(e){if(!cancelled)setError(e.message)}}init();return()=>{cancelled=true}},[])
  useEffect(()=>{if(active&&data)load(data.id).catch(e=>setError(e.message))},[active])
  useEffect(()=>{messagesEnd.current?.scrollIntoView({block:'nearest'})},[data?.messages.length])
  useEffect(()=>{const run=data?.runs?.find(x=>x.status==='running');if(!run||watchedRun.current===run.id)return;watchedRun.current=run.id;setRunState(run);setPending(true);pollRun(run.id).finally(()=>setPending(false))},[data?.id])
  useEffect(()=>{if(!data||!requestedAction||handledAction.current===requestedAction.requestKey)return;handledAction.current=requestedAction.requestKey;act(async()=>{if(requestedAction.text){setText(requestedAction.text);const run=await createAssistantRun(data.id,{client_message_id:crypto.randomUUID(),text:requestedAction.text});setRunState(run);watchedRun.current=run.id;await pollRun(run.id);onActionHandled?.();return}const fields={duration_minutes:requestedAction.durationMinutes};await sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`请为“${requestedAction.title}”把预计剩余时间调整为${requestedAction.durationMinutes}分钟，并生成待确认方案。`,actions:[{op:'update',target:`task:${requestedAction.taskId}`,fields}]});onActionHandled?.()})},[data?.id,requestedAction?.requestKey])
  async function act(fn){if(pending)return;setPending(true);setError('');setExplanation(null);try{await fn();await load(data.id)}catch(e){setError(e.message);if(data)await load(data.id).catch(()=>{})}finally{setPending(false)}}
  async function pollRun(id){
    const until=Date.now()+270000
    while(Date.now()<until){
      const next=await getAssistantRun(id);setRunState(next)
      if(next.status!=='running'){await load(data.id);if(next.status==='completed'){setText('');requestId.current=null}else if(next.status==='failed')setError(next.error_code==='STALE_CANDIDATE'?'任务或偏好已变化，请重新发送这条需求。':'AI 处理未完成，输入已保留，可重试或改用手动任务卡片。');return next}
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
  function edit(t){manualRequest.current=null;setForm({target:t?.ref||'',title:t?.title||'',minutes:String(t?.duration_minutes||60),deadline:t?.deadline?shanghaiTime(t.deadline):`${data.settings.now.slice(0,10)}T20:00`,priority:t?.priority||'normal',task_type:t?.task_type||'other'});setManual(true);setView('chat')}
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
  const preferenceLabel={balanced:'兼顾习惯与稳定',preference:'更符合个人习惯',stable:'尽量少改原计划'}
  const recommendationTitle=p?.recommendation?.source==='user_selected'?'当前选择方案：':p?.recommendation?.source==='program_fallback'?'程序校验方案：':p?.recommendation?.source==='ai'?'AI 推荐方案：':'已校验方案：'
  const focusedTasks=focusCards(attention)
  const categoryName=(key)=>data.task_categories?.find((item)=>item.key===key)?.name||key||'其他'
  return <section className="assistant-workspace">
    <div className="assistant-top"><div><h2>一起安排这一周</h2><p>说出新任务和时间要求，我会结合已有 DDL 帮你梳理。</p></div><div className="week-label"><strong>{data.week_start} 至 {new Date(new Date(`${data.week_start}T00:00:00+08:00`).getTime()+6*86400000).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})}</strong><span>{data.settings.demo?'演示模式 · 示例任务':'本地任务记忆'}　{stamp(data.settings.now)} 北京时间</span></div></div>
    <section className="today-focus" aria-labelledby="today-focus-heading"><div className="today-focus-intro"><p className="eyebrow">按截止时间、可用时段和重要程度</p><h3 id="today-focus-heading">现在先关注</h3><p>紧急程度会随当前时间和任务变化更新。</p></div>{attention===undefined?<p className="today-focus-empty" role="status">正在整理任务轻重缓急…</p>:attention===null?<p className="today-focus-empty" role="status">动态优先级暂时不可用；可以继续查看下面的课程和任务安排。</p>:focusedTasks.length?<ol>{focusedTasks.map(item=><li key={item.task_id} className={`today-focus-item urgency-${item.urgency}`}><div><strong>{item.title}</strong><span className="today-urgency">{item.urgency_label}</span></div><p>{item.reason}</p><small>重要程度：{item.importance_label}{item.goal?` · 关联目标：${item.goal.title}`:''}</small></li>)}</ol>:<p className="today-focus-empty">目前没有待处理任务。</p>}</section>
    <div className="mobile-switch" role="group" aria-label="切换聊天和周日程"><button type="button" onClick={()=>setView('chat')} aria-pressed={view==='chat'}>聊天</button><button type="button" onClick={()=>setView('calendar')} aria-pressed={view==='calendar'}>周日程</button></div>
    <div className="assistant-columns">
      <aside className={`chat-panel mobile-${view==='chat'?'show':'hide'}`}><div className="panel-heading"><h3>规划助手</h3><span>先预览，再采用</span></div>
        <div className="preference-panel profile-preference-link">安排偏好由“我的档案”统一管理。临时要求仍可直接在聊天中提出，只影响本轮方案。</div>
        <div className="chat-messages" aria-live="polite">{!data.messages.length&&<div className="assistant-bubble"><p>你的课程和已有任务已显示在右侧。</p><p>可以告诉我：“周五20:00前交实验报告，预计两小时，尽量周四下午做。”</p><p>新任务会与已有任务一起考虑，DDL 会随任务保存。</p></div>}{data.messages.map(m=><div key={m.id} className={`${m.role}-bubble`}><small>{m.role==='user'?'你':'规划助手'}</small><SafeMessage text={m.text}/></div>)}<div ref={messagesEnd}/></div>
        {runState?.status==='running'&&<div className="run-progress" role="status"><span>{PHASE[runState.phase]||'正在处理'}</span><button type="button" onClick={cancelRun}>取消本轮</button></div>}
        {runState?.status==='failed'&&<div className="run-progress error" role="status"><span>{runState.error_code==='STALE_CANDIDATE'?'资料已变化，请重新发送本轮需求':'AI 服务暂时未完成，可重试；输入已保留'}</span>{runState.error_code!=='STALE_CANDIDATE'&&<button type="button" onClick={retryRun}>重试</button>}</div>}
        {error&&<p className="assistant-error" role="alert">{error}</p>}
        <form className="chat-compose" onSubmit={send}><label htmlFor="chat-input">新增任务或调整要求</label><textarea id="chat-input" value={text} onChange={e=>{setText(e.target.value);requestId.current=null}} disabled={pending} placeholder="例如：明天中午前交汇报稿，预计一小时，很重要" maxLength={2000}/><div><button className="manual-link" type="button" onClick={()=>edit()} disabled={pending}>手动任务卡片</button><button className="button primary" disabled={pending||!text.trim()}>{pending?'正在理解与安排…':'发送'}</button></div></form>
        {manual&&<form className="manual-task" onSubmit={manualSubmit}><h4>确认任务资料</h4><label>修改哪项任务<select value={form.target} onChange={e=>{const t=library.find(t=>t.ref===e.target.value);edit(t)}}><option value="">新增任务</option>{library.filter(t=>t.status==='todo').map(t=><option key={t.ref} value={t.ref}>{t.title||'待补充任务'}</option>)}</select></label><label>名称<input required value={form.title} onChange={e=>changeForm({...form,title:e.target.value})}/></label><label>任务类型<select value={form.task_type} onChange={e=>changeForm({...form,task_type:e.target.value})}>{(data.task_categories||[]).filter(item=>item.active).map(item=><option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>预计剩余分钟<input type="number" min="30" step="30" required value={form.minutes} onChange={e=>changeForm({...form,minutes:e.target.value})}/></label><label>DDL（北京时间）<input type="datetime-local" required value={form.deadline} onChange={e=>changeForm({...form,deadline:e.target.value})}/></label><label>重要程度<select value={form.priority} onChange={e=>changeForm({...form,priority:e.target.value})}>{Object.entries(PRIORITIES).map(([v,t])=><option key={v} value={v}>{t}</option>)}</select></label><div className="button-row"><button className="button primary" disabled={pending}>生成候选</button><button type="button" className="button subtle" onClick={()=>setManual(false)}>收起</button></div></form>}
      </aside>
      <div className={`schedule-panel mobile-${view==='calendar'?'show':'hide'}`}><div className="panel-heading"><h3>本周日程</h3><div className="calendar-legend"><span className="course-key">固定课程</span><span className="task-key">正式任务</span><span className="change-key">待确认调整</span></div></div><Calendar data={data}/>
      {data.warnings.length>0&&<details className="course-warnings"><summary>课表有 {data.warnings.length} 项待补充</summary>{data.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}</div>
    </div>
    {p&&<section className={`proposal-panel ${p.status}`} aria-label="本轮方案"><div className="proposal-heading"><h3>{STATUS[p.status]||p.status}</h3><span>{live?'尚未修改正式计划':'本轮状态已保存'}</span></div>
      {p.questions.map((q,i)=><p key={i}>{q}</p>)}
      {p.status==='stale'&&<p className="diagnostic">任务或课程资料已变化，本轮旧候选已停用。请重新描述修改要求以读取最新资料。</p>}
      {live&&p.actions.map(a=>{const t=p.tasks.find(t=>t.ref===a.target);return t&&<div className="understood-task" key={a.target}><strong>{t.title||'待补充任务'}</strong><span>{categoryName(t.task_type)}　{t.duration_minutes?`${t.duration_minutes} 分钟`:'时长待补充'}　{t.deadline?`DDL ${stamp(t.deadline)}`:'DDL待补充'}　{PRIORITIES[t.priority]}</span><button onClick={()=>edit(t)} disabled={pending}>修正资料</button></div>})}
      {live&&p.preference_updates&&<p className="preference-staged">本轮偏好修改仅在采用方案后保存。</p>}
      {live&&p.temporary_preferences&&(p.temporary_preferences.blocked_windows||[]).map((w,i)=><p className="preference-staged" key={`blocked-${i}`}>本轮临时限制：{stamp(w.start_at)}–{short(w.end_at)}，不会写入长期偏好。</p>)}
      {live&&p.temporary_preferences&&(p.temporary_preferences.avoid_windows||[]).map((w,i)=><p className="preference-staged" key={`avoid-${i}`}>本轮临时时段偏好：{stamp(w.start_at)}–{short(w.end_at)}，仅影响这次方案。</p>)}
      {p.changes.length>0&&<ul className="change-list">{p.changes.map(c=><li key={c.ref}><strong>{c.title}</strong><span>{c.kind==='removed'?`${stamp(c.before.start_at)}：从未来日程移除`:<>{c.before?`${stamp(c.before.start_at)} → `:'新增：'}{stamp(c.after.start_at)}–{short(c.after.end_at)}</>}</span><small>DDL {stamp(c.deadline)}，{PRIORITIES[c.priority]}</small></li>)}</ul>}
      {(p.unmet_preferences||[]).map(u=><p className="diagnostic" key={u.ref}>{u.title}：时间偏好未满足，当前采用其他可行时段，可继续聊天调整。</p>)}
      {p.diagnostics.map((d,i)=><p className="diagnostic" key={i}>{d.message}</p>)}
      {p.status==='conflict'&&p.alternatives.map((a,i)=><button key={i} className="button subtle" disabled={pending} onClick={()=>act(()=>previewAssistant(p.id,{alternative_index:i}))}>改为 {stamp(a.start_at)}–{short(a.end_at)}</button>)}
      {p.status==='ready'&&<><div className="candidate-options"><h4>{recommendationTitle}{preferenceLabel[p.selected_strategy]||'综合安排'}</h4>{p.recommendation?.source==='program_fallback'&&<p className="diagnostic">AI 推荐服务暂不可用，当前展示程序校验过的均衡方案。</p>}{p.recommendation?.source==='ai'&&p.recommendation?.reason_text?.map((reason,i)=><span className="reason-chip" key={i}>{reason}</span>)}{(p.candidate_options||[]).map(option=><button type="button" key={option.candidate_id} className={`candidate-option ${p.selected_candidate_id===option.candidate_id?'selected':''}`} aria-pressed={p.selected_candidate_id===option.candidate_id} onClick={()=>act(()=>previewAssistant(p.id,{candidate_id:option.candidate_id}))} disabled={pending}><strong>{preferenceLabel[option.strategy]||'备选方案'}</strong><span>{option.changes.length?option.changes.map(c=>c.title+(c.before?'调整':'新增')).join('、'):'保留现有任务时段'}</span><small>偏好不满足 {option.metrics.preference_misses_weight}　落入避开时段 {option.metrics.avoided_tasks_weight}　移动权重 {option.metrics.changed_tasks_weight}　截止缓冲不足 {option.metrics.deadline_buffer_shortfall_hours} 小时</small></button>)}</div><div className="fact-summary"><SafeMessage text={p.summary}/></div><div className="button-row"><button className="button primary" disabled={pending} onClick={()=>act(()=>confirmAssistant(p.id))}>采用方案</button><button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>放弃本轮</button><button className="button subtle" disabled={pending} onClick={async()=>{setPending(true);try{setExplanation(await explainAssistant(p.id))}catch(e){setError(e.message)}finally{setPending(false)}}}>AI 解释调整</button></div></>}
      {live&&p.status!=='ready'&&<button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>放弃本轮</button>}
      {explanation&&<div className="fact-summary">{explanation.source==='ai'?'AI 解释':'事实摘要（AI解释暂不可用）'}：<SafeMessage text={explanation.text}/></div>}
      {p.notices.length>0&&<details><summary>任务与安排提示</summary>{[...new Set(p.notices)].map((n,i)=><p key={i}>{n}</p>)}</details>}
    </section>}
    <details className="task-memory"><summary>任务记忆：{data.tasks.filter(t=>t.status==='todo').length} 项未完成任务 {live?'（本轮草稿尚未保存）':''}</summary><div className="memory-list">{data.tasks.map(t=><div key={t.ref}><strong>{t.title}</strong><span>{categoryName(t.task_type)}　DDL {stamp(t.deadline)}　剩余 {t.duration_minutes} 分钟　{PRIORITIES[t.priority]}　{t.status==='done'?'已完成':t.status==='cancelled'?'已取消':'待完成'}　{t.profile?.locked?'已锁定':''}</span><button disabled={pending} onClick={()=>edit(t)}>修改</button><button disabled={pending} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`${t.title}：${t.profile?.locked?'解锁':'锁定'}安排`,actions:[{op:'update',target:t.ref,fields:{profile:{locked:!t.profile?.locked}}}]}))}>{t.profile?.locked?'解锁':'锁定'}</button><button disabled={pending||t.status!=='todo'} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`完成 ${t.title}`,actions:[{op:'update',target:t.ref,fields:{status:'done'}}]}))}>完成</button></div>)}</div></details>
  </section>
}
