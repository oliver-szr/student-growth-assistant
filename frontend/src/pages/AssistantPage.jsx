import { useEffect,useState,useRef } from 'react'
import {createAssistantSession,getAssistantSession,sendAssistantMessage,previewAssistant,confirmAssistant,discardAssistant,explainAssistant} from '../api.js'
import {calendarPosition,visibleSchedule,shanghaiTime,manualAction,PRIORITIES} from '../assistant.js'
import '../assistant.css'

const STATUS={ready:'待确认方案',needs_input:'需要补充信息',conflict:'时间冲突',no_plan:'未找到完整方案',applied:'已采用方案',discarded:'已放弃方案',superseded:'已有更新方案'}
const weekDays=['周一','周二','周三','周四','周五','周六','周日']
const stamp=value=>shanghaiTime(value).replace('T',' ')
const short=value=>shanghaiTime(value).slice(11)
const key=`sga-assistant-session:${location.host}`

function Calendar({data}){
  const p=data.proposal
  const changes=new Set(p?.status==='ready'?p.changes.map(c=>c.ref):[])
  const items=[...data.courses,...visibleSchedule(data.confirmed_items,p)]
  const dates=weekDays.map((_,i)=>new Date(`${data.week_start}T00:00:00+08:00`).getTime()+i*86400000).map(t=>shanghaiTime(t).slice(0,10))
  return <div className="week-scroll"><div className="week-grid">
    <div className="week-axis"><div className="day-heading">时间</div><div className="hours">{Array.from({length:15},(_,i)=><span key={i} style={{top:i*42}}>{String(i+8).padStart(2,'0')}:00</span>)}</div></div>
    {dates.map((date,i)=><div className="day-column" key={date}><div className={`day-heading ${data.settings.now.startsWith(date)?'today':''}`}><strong>{weekDays[i]}</strong><span>{date.slice(5)}</span></div><div className="day-body">
      {items.filter(x=>calendarPosition(x).date===date).map((x,j)=>{const pos=calendarPosition(x),changed=changes.has(x.ref),past=x.end_at<data.settings.now;return <div key={`${x.ref}-${j}`} className={`calendar-block ${x.kind==='course'?'course':'task'} ${changed?'changed':''} ${past?'past':''}`} style={{top:pos.top*.7,height:pos.height*.7}} title={`${x.title}\n${short(x.start_at)}–${short(x.end_at)}`}><span>{short(x.start_at)}–{short(x.end_at)}</span><strong>{x.title}</strong><small>{x.kind==='course'?'固定课程':changed?'待确认调整':'正式任务'}</small></div>})}
    </div></div>)}
  </div></div>
}

export default function AssistantPage({active}){
  const [data,setData]=useState(null),[text,setText]=useState(''),[pending,setPending]=useState(false),[error,setError]=useState(''),[manual,setManual]=useState(false),[view,setView]=useState('chat'),[explanation,setExplanation]=useState(null)
  const [form,setForm]=useState({target:'',title:'',minutes:'60',deadline:'',priority:'normal'})
  const messagesEnd=useRef(null),requestId=useRef(null),manualRequest=useRef(null)
  async function load(id){const d=await getAssistantSession(id);setData(d);return d}
  useEffect(()=>{let cancelled=false;async function init(){try{let id=localStorage.getItem(key),d;if(id){try{d=await getAssistantSession(id)}catch(e){if(e.status!==404)throw e}}
    if(!d||d.week_start!==d.settings.week_start){const s=await createAssistantSession();id=s.id;d=await getAssistantSession(id)}
    if(!cancelled){localStorage.setItem(key,String(d.id));setData(d)}
  }catch(e){if(!cancelled)setError(e.message)}}init();return()=>{cancelled=true}},[])
  useEffect(()=>{if(active&&data)load(data.id).catch(e=>setError(e.message))},[active])
  useEffect(()=>{messagesEnd.current?.scrollIntoView({block:'nearest'})},[data?.messages.length])
  async function act(fn){if(pending)return;setPending(true);setError('');setExplanation(null);try{await fn();await load(data.id)}catch(e){setError(e.message);if(data)await load(data.id).catch(()=>{})}finally{setPending(false)}}
  async function send(e){e.preventDefault();if(!text.trim()||!data)return;const input=text;requestId.current=requestId.current||crypto.randomUUID();await act(async()=>{await sendAssistantMessage(data.id,{client_message_id:requestId.current,text:input});requestId.current=null;setText('')})}
  function changeForm(v){manualRequest.current=null;setForm(v)}
  function edit(t){manualRequest.current=null;setForm({target:t?.ref||'',title:t?.title||'',minutes:String(t?.duration_minutes||60),deadline:t?.deadline?shanghaiTime(t.deadline):`${data.settings.now.slice(0,10)}T20:00`,priority:t?.priority||'normal'});setManual(true);setView('chat')}
  async function manualSubmit(e){
    e.preventDefault()
    const action=manualAction(form)
    if(!manualRequest.current)manualRequest.current={id:crypto.randomUUID(),proposal: data.proposal&&!['applied','discarded','superseded'].includes(data.proposal.status)?data.proposal.id:null,action}
    const req=manualRequest.current
    await act(async()=>{
      if(req.proposal)await previewAssistant(req.proposal,{client_message_id:req.id,actions:[req.action]})
      else await sendAssistantMessage(data.id,{client_message_id:req.id,text:`手动确认任务：${form.title}`,actions:[req.action]})
      manualRequest.current=null;setManual(false)
    })
  }

  if(!data)return <section className="assistant-loading" aria-live="polite">{error||'正在加载课程与任务…'}{error&&<button onClick={()=>location.reload()}>重新加载</button>}</section>
  const p=data.proposal,live=p&&!['applied','discarded','superseded'].includes(p.status),library=live?p.tasks:data.tasks
  return <section className="assistant-workspace">
    <div className="assistant-top"><div><h2>一起调整这一周</h2><p>说出新任务和时间要求，我会结合已有 DDL 帮你梳理。</p></div><div className="week-label"><strong>{data.week_start} 至 {new Date(new Date(`${data.week_start}T00:00:00+08:00`).getTime()+6*86400000).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})}</strong><span>{data.settings.demo?'演示模式 · 示例任务':'本地任务记忆'}　{stamp(data.settings.now)} 北京时间</span></div></div>
    <div className="mobile-switch"><button onClick={()=>setView('chat')} aria-pressed={view==='chat'}>聊天与方案</button><button onClick={()=>setView('calendar')} aria-pressed={view==='calendar'}>周日程</button></div>
    <div className="assistant-columns">
      <aside className={`chat-panel mobile-${view==='chat'?'show':'hide'}`}><div className="panel-heading"><h3>日程助手</h3><span>先预览，再采用</span></div>
        <div className="chat-messages" aria-live="polite">{!data.messages.length&&<div className="assistant-bubble"><p>你的课程和已有任务已显示在右侧。</p><p>可以告诉我：“周五20:00前交实验报告，预计两小时，尽量周四下午做。”</p><p>新任务会与已有任务一起考虑，DDL 会随任务保存。</p></div>}{data.messages.map(m=><div key={m.id} className={`${m.role}-bubble`}><small>{m.role==='user'?'你':'日程助手'}</small><p>{m.text}</p></div>)}<div ref={messagesEnd}/></div>
        {error&&<p className="assistant-error" role="alert">{error}</p>}
        <form className="chat-compose" onSubmit={send}><label htmlFor="chat-input">新增任务或调整要求</label><textarea id="chat-input" value={text} onChange={e=>{setText(e.target.value);requestId.current=null}} disabled={pending} placeholder="例如：明天中午前交汇报稿，预计一小时，很重要" maxLength={2000}/><div><button className="manual-link" type="button" onClick={()=>edit()} disabled={pending}>手动任务卡片</button><button className="button primary" disabled={pending||!text.trim()}>{pending?'正在理解与安排…':'发送'}</button></div></form>
        {manual&&<form className="manual-task" onSubmit={manualSubmit}><h4>确认任务资料</h4><label>修改哪项任务<select value={form.target} onChange={e=>{const t=library.find(t=>t.ref===e.target.value);edit(t)}}><option value="">新增任务</option>{library.filter(t=>t.status==='todo').map(t=><option key={t.ref} value={t.ref}>{t.title||'待补充任务'}</option>)}</select></label><label>名称<input required value={form.title} onChange={e=>changeForm({...form,title:e.target.value})}/></label><label>预计剩余分钟<input type="number" min="30" step="30" required value={form.minutes} onChange={e=>changeForm({...form,minutes:e.target.value})}/></label><label>DDL（北京时间）<input type="datetime-local" required value={form.deadline} onChange={e=>changeForm({...form,deadline:e.target.value})}/></label><label>重要程度<select value={form.priority} onChange={e=>changeForm({...form,priority:e.target.value})}>{Object.entries(PRIORITIES).map(([v,t])=><option key={v} value={v}>{t}</option>)}</select></label><div className="button-row"><button className="button primary" disabled={pending}>生成候选</button><button type="button" className="button subtle" onClick={()=>setManual(false)}>收起</button></div></form>}
      </aside>
      <div className={`schedule-panel mobile-${view==='calendar'?'show':'hide'}`}><div className="panel-heading"><h3>本周日程</h3><div className="calendar-legend"><span className="course-key">固定课程</span><span className="task-key">正式任务</span><span className="change-key">待确认调整</span></div></div><Calendar data={data}/>
      {data.warnings.length>0&&<details className="course-warnings"><summary>课表有 {data.warnings.length} 项待补充</summary>{data.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}</div>
    </div>
    {p&&<section className={`proposal-panel ${p.status}`} aria-label="本轮方案"><div className="proposal-heading"><h3>{STATUS[p.status]||p.status}</h3><span>{live?'尚未修改正式计划':'本轮状态已保存'}</span></div>
      {p.questions.map((q,i)=><p key={i}>{q}</p>)}
      {live&&p.actions.map(a=>{const t=p.tasks.find(t=>t.ref===a.target);return t&&<div className="understood-task" key={a.target}><strong>{t.title||'待补充任务'}</strong><span>{t.duration_minutes?`${t.duration_minutes} 分钟`:'时长待补充'}　{t.deadline?`DDL ${stamp(t.deadline)}`:'DDL待补充'}　{PRIORITIES[t.priority]}</span><button onClick={()=>edit(t)} disabled={pending}>修正资料</button></div>})}
      {p.changes.length>0&&<ul className="change-list">{p.changes.map(c=><li key={c.ref}><strong>{c.title}</strong><span>{c.kind==='removed'?`${stamp(c.before.start_at)}：从未来日程移除`:<>{c.before?`${stamp(c.before.start_at)} → `:'新增：'}{stamp(c.after.start_at)}–{short(c.after.end_at)}</>}</span><small>DDL {stamp(c.deadline)}，{PRIORITIES[c.priority]}</small></li>)}</ul>}
      {(p.unmet_preferences||[]).map(u=><p className="diagnostic" key={u.ref}>{u.title}：时间偏好未满足，当前采用其他可行时段，可继续聊天调整。</p>)}
      {p.diagnostics.map((d,i)=><p className="diagnostic" key={i}>{d.message}</p>)}
      {p.status==='conflict'&&p.alternatives.map((a,i)=><button key={i} className="button subtle" disabled={pending} onClick={()=>act(()=>previewAssistant(p.id,{alternative_index:i}))}>改为 {stamp(a.start_at)}–{short(a.end_at)}</button>)}
      {p.status==='ready'&&<><p className="fact-summary">{p.summary}</p><div className="button-row"><button className="button primary" disabled={pending} onClick={()=>act(()=>confirmAssistant(p.id))}>采用方案</button><button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>放弃本轮</button><button className="button subtle" disabled={pending} onClick={async()=>{setPending(true);try{setExplanation(await explainAssistant(p.id))}catch(e){setError(e.message)}finally{setPending(false)}}}>AI 解释调整</button></div></>}
      {live&&p.status!=='ready'&&<button className="button subtle" disabled={pending} onClick={()=>act(()=>discardAssistant(p.id))}>放弃本轮</button>}
      {explanation&&<p className="fact-summary">{explanation.source==='ai'?'AI 解释':'事实摘要（AI解释暂不可用）'}：{explanation.text}</p>}
      {p.notices.length>0&&<details><summary>任务与安排提示</summary>{[...new Set(p.notices)].map((n,i)=><p key={i}>{n}</p>)}</details>}
    </section>}
    <details className="task-memory"><summary>任务记忆：{data.tasks.filter(t=>t.status==='todo').length} 项未完成任务 {live?'（本轮草稿尚未保存）':''}</summary><div className="memory-list">{data.tasks.map(t=><div key={t.ref}><strong>{t.title}</strong><span>DDL {stamp(t.deadline)}　剩余 {t.duration_minutes} 分钟　{PRIORITIES[t.priority]}　{t.status==='done'?'已完成':t.status==='cancelled'?'已取消':'待完成'}　{t.profile?.locked?'已锁定':''}</span><button disabled={pending} onClick={()=>edit(t)}>修改</button><button disabled={pending} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`${t.title}：${t.profile?.locked?'解锁':'锁定'}安排`,actions:[{op:'update',target:t.ref,fields:{profile:{locked:!t.profile?.locked}}}]}))}>{t.profile?.locked?'解锁':'锁定'}</button><button disabled={pending||t.status!=='todo'} onClick={()=>act(()=>sendAssistantMessage(data.id,{client_message_id:crypto.randomUUID(),text:`完成 ${t.title}`,actions:[{op:'update',target:t.ref,fields:{status:'done'}}]}))}>完成</button></div>)}</div></details>
  </section>
}
