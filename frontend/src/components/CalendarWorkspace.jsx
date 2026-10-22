import { useEffect,useRef,useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import multiMonthPlugin from '@fullcalendar/multimonth'
import interactionPlugin from '@fullcalendar/interaction'
import zhCn from '@fullcalendar/core/locales/zh-cn'
import { getCalendarEvents } from '../api.js'
import { calendarEvent } from '../calendar.js'
import { shanghaiTime } from '../assistant.js'
import EditRecovery,{useEditRecovery} from './EditRecovery.jsx'

export default function CalendarWorkspace({workspace,today,active,refreshVersion,proposal,onOpenTask}){
  const container=useRef(null),api=useRef(null),generation=useRef(0),[range,setRange]=useState(null),[data,setData]=useState(null)
  const [view,setView]=useState('timeGridWeek'),[date,setDate]=useState(today),[error,setError]=useState(''),[detail,setDetail]=useState(null)
  const [retry,setRetry]=useState(0),[title,setTitle]=useState('')
  const recovery=useEditRecovery({workspace,resource:'full-calendar',base:today?'calendar-v2':undefined,
    value:{view,date},dirty:true,automatic:true,restore:value=>{
      if(['timeGridDay','timeGridWeek','dayGridMonth','multiMonthYear'].includes(value.view)&&/^20\d\d-\d\d-\d\d$/.test(value.date)){
        setView(value.view);setDate(value.date);api.current?.getApi().changeView(value.view,value.date)
      }}})
  useEffect(()=>{
    if(!active||!range)return
    const token=++generation.current;setError('')
    getCalendarEvents(range.start,range.end).then(value=>{if(generation.current===token)setData(value)}).catch(cause=>{if(generation.current===token)setError(cause.message)})
    return()=>{generation.current++}
  },[active,range?.start,range?.end,refreshVersion,retry])
  useEffect(()=>{if(active)requestAnimationFrame(()=>api.current?.getApi().updateSize())},[active])
  useEffect(()=>{
    let timer
    const observer=new ResizeObserver(()=>{cancelAnimationFrame(timer);timer=requestAnimationFrame(()=>{if(active)api.current?.getApi().updateSize()})})
    observer.observe(container.current)
    return()=>{observer.disconnect();cancelAnimationFrame(timer)}
  },[active])
  const events=(data?.events||[]).map(calendarEvent)
  if(view==='timeGridDay')events.push(...(data?.free||[]).map((free,i)=>({...calendarEvent({...free,id:'free:'+i,allDay:false,kind:'free'}),display:'background',backgroundColor:'#dcf3e8'})))
  if(proposal&&!['applied','discarded','superseded','stale'].includes(proposal.status))events.push(...(proposal.items||[]).map((item,i)=>calendarEvent({id:'candidate:'+proposal.id+':'+i,title:'待确认 · '+item.title,start:item.start_at,end:item.end_at,kind:'candidate',allDay:false})))
  const change=(value,day=date)=>{setView(value);api.current?.getApi().changeView(value,day)}
  return <section ref={container} className="full-calendar panel" aria-label="完整日历">
    <EditRecovery recovery={recovery} label="完整日历状态"/>
    <div className="calendar-toolbar"><div role="group" aria-label="日历四视图">{[['timeGridDay','天'],['timeGridWeek','周'],['dayGridMonth','月'],['multiMonthYear','年']].map(([key,label])=><button className="button subtle" key={key} aria-pressed={view===key} onClick={()=>change(key)}>{label}</button>)}</div>
      <div className="button-row"><button className="button subtle" aria-label="上一段" onClick={()=>api.current?.getApi().prev()}>‹</button><strong>{title}</strong><button className="button subtle" aria-label="下一段" onClick={()=>api.current?.getApi().next()}>›</button></div>
      <label>日历日期<input type="date" min="2000-01-01" max="2100-12-31" value={date} onChange={e=>{if(e.target.value){setDate(e.target.value);api.current?.getApi().gotoDate(e.target.value)}}}/></label>
      <button className="button subtle" onClick={()=>{setDate(today);api.current?.getApi().gotoDate(today)}}>回到今天</button>
    </div>
    {view==='multiMonthYear'&&<div className="year-month-links" aria-label="打开月份">{Array.from({length:12},(_,i)=><button className="button subtle" key={i} onClick={()=>change('dayGridMonth',`${date.slice(0,4)}-${String(i+1).padStart(2,'0')}-01`)}>{i+1}月</button>)}</div>}
    <p className="helper">北京时间 · 正式任务、课程、待确认候选、截止和目标分别标识；浅绿为08–22点可用时段。拖动不会修改日程。</p>
    {error&&<p className="error-box" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试读取</button></p>}
    <FullCalendar ref={api} plugins={[dayGridPlugin,timeGridPlugin,multiMonthPlugin,interactionPlugin]} locale={zhCn} timeZone="UTC" initialDate={today} initialView="timeGridWeek" headerToolbar={false} firstDay={1} height="auto" slotMinTime="00:00:00" slotMaxTime="24:00:00" scrollTime="08:00:00" now={today+'T12:00:00Z'} nowIndicator={false} editable={false} selectable={false} dayMaxEvents={3} events={events} validRange={{start:'2000-01-01',end:'2101-01-01'}}
      datesSet={info=>{setRange(previous=>previous?.start===info.startStr.slice(0,10)&&previous?.end===info.endStr.slice(0,10)?previous:{start:info.startStr.slice(0,10),end:info.endStr.slice(0,10)});setTitle(info.view.title);setView(info.view.type);setDate(info.view.calendar.getDate().toISOString().slice(0,10))}}
      navLinks navLinkDayClick={day=>change('timeGridDay',day.toISOString().slice(0,10))} dateClick={info=>{if(view==='dayGridMonth')change('timeGridDay',info.dateStr)}}
      eventClick={info=>{if(info.event.display!=='background')setDetail(info.event.extendedProps)}} eventDidMount={info=>{info.el.setAttribute('tabindex','0');info.el.setAttribute('role','button');info.el.setAttribute('aria-label',info.event.title);info.el.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();setDetail(info.event.extendedProps)}})}}/>
    {data&&<p className="helper">{data.note}{data.conflicts.length>0?' 当前范围有重叠事项，请核对。':''}</p>}
    {data?.unscheduled_tasks?.length>0&&<details><summary>本范围截止、尚无未来正式安排的任务（{data.unscheduled_tasks.length}{data.unscheduled_has_more?'+':''}）</summary>{data.unscheduled_tasks.map(task=><p key={task.id}>{task.title} · 截止 {shanghaiTime(task.deadline).replace('T',' ')} <button className="button subtle" onClick={()=>onOpenTask?.(task.id)}>查看任务</button></p>)}</details>}
    {detail&&<div className="calendar-event-detail recovery-note" role="region" aria-label="日历事项详情"><h3>{detail.title}</h3><p>{detail.source||'未确认候选'}</p><p>{detail.deadline?shanghaiTime(detail.deadline).replace('T',' '):detail.start}{detail.end?' 至 '+detail.end:''}</p>{detail.task_id&&<button className="button secondary" onClick={()=>onOpenTask?.(detail.task_id)}>查看任务与执行</button>}<button className="button subtle" onClick={()=>setDetail(null)}>关闭详情</button></div>}
  </section>
}
