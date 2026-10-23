import { shanghaiTime } from './assistant.js'
export function dayPreviewData(snapshot,settings){
  const timed=(snapshot.events||[]).filter(event=>!event.allDay&&['formal_task','course','course_snapshot'].includes(event.kind)).map(event=>({
    ...event,ref:event.task_id?`task:${event.task_id}`:event.id,kind:event.kind==='formal_task'?'task':'course',start_at:event.start,end_at:event.end,
  }))
  return {settings,week_start:settings.week_start,courses:timed.filter(event=>event.kind==='course'),confirmed_items:timed.filter(event=>event.kind==='task'),tasks:[]}
}
export const shiftDate=(date,days)=>new Date(Date.parse(date+'T00:00:00Z')+days*86400000).toISOString().slice(0,10)
export function reviewRange(date,period){
  if(period==='day')return [date,shiftDate(date,1)]
  const day=new Date(date+'T00:00:00Z')
  if(period==='week'){const start=shiftDate(date,-((day.getUTCDay()+6)%7));return [start,shiftDate(start,7)]}
  const first=date.slice(0,7)+'-01';day.setUTCMonth(day.getUTCMonth()+1,1)
  return [first,day.toISOString().slice(0,10)]
}
// Render Shanghai wall time as UTC, avoiding FullCalendar named-zone coercion
// and browser local-zone dependence. API instants and event IDs stay unchanged.
export function calendarEvent(event){
  return {...event,start:event.allDay?event.start:shanghaiTime(event.start)+':00Z',
    end:event.end?shanghaiTime(event.end)+':00Z':undefined,extendedProps:event,
    classNames:['calendar-'+event.kind],editable:false}
}
